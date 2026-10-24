#!/usr/bin/env python3
"""
Development stand without Docker: a minimal in-memory imitation of the Ditto
REST API (the endpoints the twin uses), the real twin runtime (MQTT replaced
by direct application of the Ditto protocol messages it publishes), and a
static server for the 3D control room with the same /ditto/ proxy path as
the production nginx.

    python3 bozshakol/tools/devstand.py --port 8095

Only for development and screenshots. The real stand is `make bozshakol`.
"""

import argparse
import json
import os
import sys
import threading
import types
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STORE = {}
LOCK = threading.Lock()


def apply_modify(msg):
    topic = msg["topic"].split("/")
    thing = f"{topic[0]}:{topic[1]}"
    with LOCK:
        t = STORE.setdefault(thing, {"thingId": thing, "attributes": {}, "features": {}})
        if msg["path"] == "/features":
            t["features"] = msg["value"]


class FakeClient:
    def __init__(self, *a, **k):
        pass

    def reconnect_delay_set(self, *a):
        pass

    def connect(self, *a, **k):
        return 0

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def publish(self, topic, payload, qos=0):
        apply_modify(json.loads(payload))


def install_fake_paho():
    paho = types.ModuleType("paho")
    mqtt = types.ModuleType("paho.mqtt")
    client = types.ModuleType("paho.mqtt.client")
    client.Client = FakeClient
    client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
    paho.mqtt = mqtt
    mqtt.client = client
    sys.modules.update({"paho": paho, "paho.mqtt": mqtt, "paho.mqtt.client": client})


def pick(obj, fields):
    if not fields:
        return obj
    out = {}
    for f in fields.split(","):
        parts = f.split("/")
        src, dst = obj, out
        for i, p in enumerate(parts):
            if not isinstance(src, dict) or p not in src:
                break
            if i == len(parts) - 1:
                dst[p] = src[p]
            else:
                src = src[p]
                dst = dst.setdefault(p, {})
    return out


def merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            merge(a[k], v)
        elif v is None:
            a.pop(k, None)
        else:
            a[k] = v


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "ui"), **k)

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ditto(self, method):
        u = urllib.parse.urlparse(self.path)
        path = u.path[len("/ditto"):]
        q = urllib.parse.parse_qs(u.query)
        parts = path.strip("/").split("/")  # api 2 things <id> ...
        body = None
        if method in ("PUT", "PATCH"):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"null")
        with LOCK:
            if parts[:3] == ["api", "2", "things"] and len(parts) == 3 and method == "GET":
                ids = q.get("ids", [""])[0].split(",")
                return self._json(200, [pick(STORE[i], q.get("fields", [""])[0]) for i in ids if i in STORE])
            if parts[:3] == ["api", "2", "things"] and len(parts) >= 4:
                tid = parts[3]
                rest = parts[4:]
                if method == "PUT" and not rest:
                    STORE[tid] = {"thingId": tid, **body}
                    return self._json(201, STORE[tid])
                if tid not in STORE:
                    return self._json(404, {"error": "things:thing.notfound"})
                t = STORE[tid]
                if method == "PATCH" and not rest:
                    merge(t, body)
                    return self._json(204, {})
                if method == "GET":
                    node = t
                    for p in rest:
                        node = node.get(p, {}) if isinstance(node, dict) else {}
                    return self._json(200, pick(node, q.get("fields", [""])[0]) if not rest else node)
                if method == "PUT" and rest[:1] == ["features"] and rest[-2:] == ["properties", "value"]:
                    t["features"].setdefault(rest[1], {"properties": {}})["properties"]["value"] = body
                    return self._json(204, {})
        return self._json(404, {"error": "unsupported in devstand", "path": path})

    def do_GET(self):
        if self.path.startswith("/ditto/"):
            return self._ditto("GET")
        return super().do_GET()

    def do_PUT(self):
        return self._ditto("PUT")

    def do_PATCH(self):
        return self._ditto("PATCH")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--speed", type=int, default=10)
    ap.add_argument("--warmup-min", type=float, default=0)
    args = ap.parse_args()
    install_fake_paho()
    from sim import main as runtime
    from sim import setup_twins, twins as T

    # Same declarative files as the real stand (bozshakol/twins/), loaded by setup_twins.
    for thing_id, body in list(setup_twins.load("types.json").items()) + list(setup_twins.load("twins.json").items()):
        STORE[thing_id] = {"thingId": thing_id, **json.loads(json.dumps(body))}
    STORE[T.tid("control")]["features"]["sim_speed"]["properties"]["value"] = args.speed
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["DITTO_URL"] = f"http://127.0.0.1:{args.port}/ditto"
    os.environ.setdefault("DITTO_PASSWORD", "x")
    print(f"devstand on http://127.0.0.1:{args.port}/", flush=True)
    sys.argv = [sys.argv[0]]
    runtime.main()


if __name__ == "__main__":
    main()
