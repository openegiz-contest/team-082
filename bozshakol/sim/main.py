#!/usr/bin/env python3
"""
Bozshakol twin runtime.

- advances the coupled mine model in (accelerated) real time;
- publishes every twin's features as Eclipse Ditto protocol "modify"
  commands to MQTT (telemetry/<twin>), exactly like a field gateway would;
- reads the operator's scenario settings from the Ditto twin
  kz.bozshakol:control (written by the 3D control room, the CLI or the
  OpenEgiz Grafana app) and applies them to the model;
- recomputes the 48-hour what-if forecast after every scenario change and
  publishes it to the twin kz.bozshakol:whatif.

The runtime never writes to InfluxDB: history flows MQTT -> Ditto ->
Telegraf -> InfluxDB through the platform.
"""

import argparse
import base64
import json
import logging
import math
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request

from . import twins as T
from .forecast import Forecaster, Planner, scenario_differs
from .model import COMMAND_KEYS, CONTROL_DEFAULTS, Mine, clamp

log = logging.getLogger("bozshakol")

FAST_KINDS = ("ht-", "sh-", "ld-", "dr-", "wt-", "lv-", "p-0")
FAST_NAMES = {"site", "haulage", "gc-01", "sag-01", "cos-01", "fl-r", "fl-c", "ss-220", "energy", "gm-01", "safety"}


class ControlPoller(threading.Thread):
    """Polls the control twin in Ditto (the operator's what-if settings)."""

    def __init__(self, url, user, password, period=2.0):
        super().__init__(daemon=True)
        self.url = f"{url.rstrip('/')}/api/2/things/{T.tid('control')}/features"
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.period = period
        self.latest = None
        self.ok = False
        self.stop = False

    def run(self):
        warned = False
        while not self.stop:
            try:
                req = urllib.request.Request(self.url, headers={"Authorization": self.auth})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.load(resp)
                self.latest = {k: v.get("properties", {}).get("value") for k, v in data.items()
                               if k in CONTROL_DEFAULTS}
                self.ok = True
                warned = False
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                self.ok = False
                if not warned:
                    log.warning("control twin not readable yet (%s); retrying", exc)
                    warned = True
            time.sleep(self.period)


def ditto_modify(name, features):
    return json.dumps({
        "topic": f"{T.NS}/{name}/things/twin/commands/modify",
        "path": "/features",
        "value": {k: {"properties": v} for k, v in features.items()},
    }, ensure_ascii=False)


def scenario_label(control):
    diffs = [f"{k}={v}" for k, v in control.items()
             if k not in COMMAND_KEYS and v != CONTROL_DEFAULTS[k]]
    preset = control.get("preset", "baseline")
    if not diffs:
        return "базовый режим"
    return f"{preset}: " + ", ".join(diffs)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "localhost"))
    p.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    p.add_argument("--ditto-url", default=os.environ.get("DITTO_URL", "http://localhost:8080"))
    p.add_argument("--ditto-user", default=os.environ.get("DITTO_USER", "ditto"))
    p.add_argument("--ditto-password", default=os.environ.get("DITTO_PASSWORD", ""))
    p.add_argument("--seed", type=int, default=int(os.environ.get("SIM_SEED", "42")))
    p.add_argument("--fast", type=float, default=float(os.environ.get("PUBLISH_FAST_S", "2.5")))
    p.add_argument("--slow", type=float, default=float(os.environ.get("PUBLISH_SLOW_S", "10")))
    p.add_argument("--dry-run", action="store_true", help="print one snapshot and exit")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    mine = Mine(args.seed)
    if args.dry_run:
        snap = T.snapshot(mine)
        for name, fs in snap.items():
            print(ditto_modify(name, fs)[:300])
        print(f"{len(snap)} twins")
        return 0

    import paho.mqtt.client as mqtt  # imported here so --dry-run needs no broker library

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bozshakol-twin-{os.getpid()}")
    client.reconnect_delay_set(1, 30)
    for _ in range(60):
        try:
            client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
            break
        except OSError as exc:
            log.warning("MQTT %s:%s not reachable (%s), retrying", args.mqtt_host, args.mqtt_port, exc)
            time.sleep(2)
    else:
        log.error("giving up on MQTT")
        return 1
    client.loop_start()

    poller = ControlPoller(args.ditto_url, args.ditto_user, args.ditto_password)
    poller.start()
    fc = Forecaster()
    fc.request(mine)
    planner = Planner()
    plan_seen = int(mine.control.get("plan_optimize", 0))
    plan_feats = T.plan_features(None, "нет")
    whatif = T.whatif_features(None, "расчёт", scenario_label(mine.control))
    forecast_due = None
    last_forecast = time.monotonic()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    last = time.monotonic()
    last_pub = {"fast": 0.0, "slow": 0.0}
    sent_cache = {}
    sent_at = {}
    published = 0
    log.info("Bozshakol twin: %d trucks, %d loaders, %d drills; publishing to mqtt://%s:%s",
             len(mine.trucks), len(mine.loaders), len(mine.drills), args.mqtt_host, args.mqtt_port)

    while not stop.is_set():
        now = time.monotonic()
        elapsed = min(now - last, 2.0)
        last = now
        # Operator scenario.
        if poller.latest:
            changed = mine.apply_control(poller.latest)
            if [c for c in changed if c not in COMMAND_KEYS]:
                forecast_due = now + 2.0
                whatif = T.whatif_features(fc.result, "расчёт", scenario_label(mine.control))
        if forecast_due and now >= forecast_due:
            fc.request(mine)
            forecast_due = None
            last_forecast = now
        if now - last_forecast > 600 and not fc.busy:
            fc.request(mine)
            last_forecast = now
        if int(mine.control.get("plan_optimize", 0)) < plan_seen:
            plan_seen = int(mine.control.get("plan_optimize", 0))
        if int(mine.control.get("plan_optimize", 0)) > plan_seen:
            plan_seen = int(mine.control["plan_optimize"])
            planner.request(mine)
            plan_feats = {**plan_feats, **T.plan_features(None, "подбор")}
            log.info("plan auto-selection requested")
        pres = planner.poll(mine)
        if pres is not None:
            plan_feats = T.plan_features(pres, "готов" if pres.get("ok") else "ошибка")
            if pres.get("ok"):
                log.info("plan auto-selection ready in %.1fs: %s", pres["calc_s"],
                         next(o["name"] for o in pres["options"] if o["best"]))
            else:
                log.warning("plan auto-selection failed: %s", pres.get("error"))
        res = fc.poll(mine)
        if res is not None:
            if res.get("ok"):
                status = "готов" if not fc.busy else "расчёт"
                whatif = T.whatif_features(res, status, scenario_label(res["control"]))
                diff = scenario_differs(res["control"])
                log.info("forecast ready in %.1fs (%s): Cu %.0f -> %.0f t",
                         res["calc_s"], "scenario" if diff else "baseline",
                         res["baseline"]["cu_t"], res["scenario"]["cu_t"])
            else:
                log.warning("forecast failed: %s", res.get("error"))
        # Advance the model.
        speed = clamp(float(mine.control.get("sim_speed") or 10), 1.0, 120.0)
        sim_dt = elapsed * speed
        n = max(1, math.ceil(sim_dt / 2.0))
        for _ in range(n):
            mine.step(sim_dt / n)
        # Publish.
        groups = []
        if now - last_pub["fast"] >= args.fast:
            groups.append("fast")
            last_pub["fast"] = now
        if now - last_pub["slow"] >= args.slow:
            groups.append("slow")
            last_pub["slow"] = now
        if groups:
            snap = T.snapshot(mine, {**whatif, **plan_feats})
            for name, fs in snap.items():
                fast = name in FAST_NAMES or name.startswith(FAST_KINDS)
                if ("fast" if fast else "slow") not in groups:
                    continue
                payload = ditto_modify(name, fs)
                if sent_cache.get(name) == payload and now - sent_at.get(name, 0) < 60:
                    continue
                client.publish(f"telemetry/{name}", payload, qos=0)
                sent_cache[name] = payload
                sent_at[name] = now
                published += 1
            try:
                with open("/tmp/heartbeat", "w") as fh:
                    fh.write(str(time.time()))
            except OSError:
                pass
        if published and published % 2000 < 40 and "slow" in groups:
            log.info("sim %s | mill %.0f t/h, Cu %.2f t/h, rec %.1f%% | %s | control %s",
                     mine.now.strftime("%d.%m %H:%M"), mine.sag["tph"], mine.flot["cu_tph"],
                     mine.flot["rec"] * 100, scenario_label(mine.control),
                     "ok" if poller.ok else "unreachable")
        stop.wait(max(0.05, 0.5 - (time.monotonic() - now)))

    poller.stop = True
    client.loop_stop()
    client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
