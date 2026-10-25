#!/usr/bin/env python3
"""
twinctl — command line access to the Bozshakol twins on a running stand.

    python3 bozshakol/tools/twinctl.py status            # live summary from Ditto
    python3 bozshakol/tools/twinctl.py scenario          # list what-if presets
    python3 bozshakol/tools/twinctl.py scenario heavy_rain
    python3 bozshakol/tools/twinctl.py set rain_mm_h=2 trucks_parked=3
    python3 bozshakol/tools/twinctl.py verify            # end-to-end check
    python3 bozshakol/tools/twinctl.py wait | urls

Standard library only. Credentials and ports come from deploy/compose/.env.
Every value printed here is read from the platform (Ditto REST API, InfluxDB).
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_FILE = os.path.join(ROOT, "deploy", "compose", ".env")
PRESETS = os.path.join(ROOT, "bozshakol", "ui", "presets.json")
NS = "kz.bozshakol"


def load_env():
    env = {}
    try:
        with open(ENV_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k] = v
    except FileNotFoundError:
        pass
    env.update({k: v for k, v in os.environ.items() if k in ("DITTO_PASSWORD", "DITTO_PORT", "INFLUXDB_TOKEN")})
    return env


ENV = load_env()
HOST = ENV.get("OPENEGIZ_PUBLIC_HOST", "localhost")
DITTO = os.environ.get("TWINCTL_DITTO") or f"http://127.0.0.1:{ENV.get('DITTO_PORT', '8080')}/api/2"
INFLUX = f"http://127.0.0.1:{ENV.get('INFLUXDB_PORT', '8086')}"
UI = f"http://127.0.0.1:{ENV.get('BOZSHAKOL_UI_PORT', '8095')}"
AUTH = "Basic " + base64.b64encode(f"ditto:{ENV.get('DITTO_PASSWORD', '')}".encode()).decode()


def http(method, url, body=None, headers=None, timeout=30):
    h = {"Authorization": AUTH} if url.startswith(DITTO) else {}
    h.update(headers or {})
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return resp.status, raw


def ditto_get(path):
    _, raw = http("GET", DITTO + path)
    return json.loads(raw)


def twin(name):
    t = ditto_get(f"/things/{NS}:{name}?fields=features")
    return {k: f.get("properties", {}).get("value") for k, f in t.get("features", {}).items()}


def set_control(values):
    feats = {k: {"properties": {"value": v}} for k, v in values.items()}
    http("PATCH", f"{DITTO}/things/{NS}:control", {"features": feats},
         {"Content-Type": "application/merge-patch+json"})


def presets():
    with open(PRESETS, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_wait(timeout=600):
    """Wait until the model publishes: site twin has a sim_time that moves."""
    t0 = time.time()
    first = None
    sys.stdout.write("Waiting for the Bozshakol model to publish ")
    while time.time() - t0 < timeout:
        try:
            s = twin("site").get("sim_time")
            if first is None and s:
                first = s
            elif s and s != first:
                print(" ready")
                return 0
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            pass
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(3)
    print("\nERROR: the twin model did not publish in time; see: make logs S=bozshakol-twin")
    return 1


def cmd_urls():
    gp = ENV.get("GRAFANA_PASSWORD", ENV.get("GRAFANA_ADMIN_PASSWORD", ""))
    print(f"""
Bozshakol digital twin is running.

  3D control room   http://{HOST}:{ENV.get('BOZSHAKOL_UI_PORT', '8095')}/
  Grafana           http://{HOST}:{ENV.get('GRAFANA_PORT', '3000')}/   (opens the Bozshakol overview; anonymous viewing on;
                    admin / {gp} to edit; folder «Бозшаколь», app OpenEgiz -> Twins)
  Ditto API         http://{HOST}:{ENV.get('DITTO_PORT', '8080')}/api/2/things/{NS}:site   (ditto / {ENV.get('DITTO_PASSWORD', '')})

  Live summary      make twin-status
  What-if           make scenario                 (list)   make scenario P=heavy_rain   make scenario-reset
  End-to-end check  make verify
""")
    return 0


def fmt(v, n=1):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:,.{n}f}".replace(",", " ")
    return str(v)


def cmd_status():
    site, hl, gc, sag, wf, ctl = (twin(x) for x in ("site", "haulage", "gc-01", "sag-01", "whatif", "control"))
    print(f"Бозшаколь · {site.get('sim_time')} · смена {site.get('shift')} · ×{site.get('sim_speed')}")
    print(f"  Сценарий: {wf.get('scenario')}  (preset={ctl.get('preset')})")
    print(f"  ЗИФ {fmt(site.get('mill_tph'), 0)} т/ч · Cu в питании {fmt(site.get('feed_grade'), 3)} % · "
          f"извлечение {fmt(site.get('recovery'))} % · медь {fmt(site.get('cu_tph'), 2)} т/ч "
          f"(план {fmt(site.get('cu_plan_pct'), 0)} %)")
    print(f"  ККД-1 {gc.get('state')} {fmt(gc.get('throughput'), 0)} т/ч · МПСИ {fmt(sag.get('power_mw'))} МВт, "
          f"{fmt(sag.get('specific_energy'), 2)} кВт·ч/т · нагрузка {fmt(site.get('power_mw'))} МВт · ДТ "
          f"{fmt(site.get('diesel_lph'), 0)} л/ч")
    print(f"  Самосвалы: на линии {site.get('trucks_working')} из {hl.get('trucks_total')}, груженых {hl.get('trucks_loaded')}, "
          f"порожних {hl.get('trucks_empty')}, в очередях {hl.get('trucks_queued')}, в ремонте {hl.get('trucks_down')}, "
          f"КТГ {fmt(site.get('fleet_availability'))} %")
    loaders = ditto_get(f"/things?ids={','.join(f'{NS}:{x}' for x in ('sh-01', 'sh-02', 'sh-03', 'ld-01'))}&fields=thingId,features")
    for t in loaders:
        f = {k: v["properties"]["value"] for k, v in t["features"].items()}
        print(f"    {t['thingId'].split(':')[1].upper()}: {f.get('state_ru')}, блок {f.get('block')} "
              f"({fmt(f.get('block_grade'), 3)} % Cu), очередь {f.get('queue')}")
    print(f"  Тревоги: {site.get('alarms_active')}")
    try:
        evs = json.loads(site.get("events") or "[]")[:6]
    except ValueError:
        evs = []
    for e in evs:
        print(f"    {e['t']} [{e['lvl']}] {e['msg']}")
    print(f"  Прогноз 48 ч ({wf.get('status')}, от {wf.get('computed_at')}):")
    for k, label in (("margin_mkzt", "маржа, млн ₸"), ("cu_t", "медь, т"), ("mill_t", "переработка, т"),
                     ("diesel_l", "ДТ, л"), ("fleet_avail", "КТГ, %"), ("failures", "отказы")):
        if f"base_{k}" in wf:
            print(f"    {label:16s} {fmt(wf[f'base_{k}'])} → {fmt(wf[f'scen_{k}'])}  ({fmt(wf[f'delta_{k}'])} %)")
    return 0


def cmd_scenario(name=None):
    pr = presets()
    if not name:
        print("What-if presets (make scenario P=<name>):")
        for k, p in pr.items():
            print(f"  {k:16s} {p['title']}  {json.dumps(p['set'], ensure_ascii=False)}")
        return 0
    if name not in pr:
        print(f"unknown preset {name!r}; run without a name for the list", file=sys.stderr)
        return 2
    defaults = ditto_get(f"/things/{NS}:site?fields=attributes/control_defaults")["attributes"]["control_defaults"]
    vals = {k: v for k, v in defaults.items() if k not in ("sim_speed", "blast_now")}
    vals.update(pr[name]["set"])
    vals["preset"] = name
    set_control(vals)
    print(f"Scenario '{name}': {pr[name]['title']}")
    print(f"  {pr[name]['why']}")
    print("  The model applies it within ~3 s; the 48 h forecast is ready in ~10-20 s (make twin-status).")
    return 0


def cmd_set(pairs):
    vals = {"preset": "manual"}
    for p in pairs:
        k, v = p.split("=", 1)
        try:
            vals[k] = json.loads(v)
        except ValueError:
            vals[k] = v
    set_control(vals)
    print("set:", vals)
    return 0


def influx_count():
    # A light query: three twins (site, haulage, the crusher) over 3 minutes. Counting
    # every series of all 113 twins makes InfluxDB scan thousands of series.
    flux = ('from(bucket: "default") |> range(start: -3m) '
            '|> filter(fn: (r) => r._measurement == "mqtt_consumer" and '
            '(r.thingId == "kz.bozshakol:site" or r.thingId == "kz.bozshakol:haulage" or r.thingId == "kz.bozshakol:gc-01")) '
            '|> group() |> count()')
    _, raw = http("POST", f"{INFLUX}/api/v2/query?org=opentwins", json.dumps({"query": flux, "type": "flux"}).encode(),
                  {"Authorization": f"Token {ENV.get('INFLUXDB_TOKEN', '')}", "Content-Type": "application/json",
                   "Accept": "application/csv"}, timeout=60)
    rows = [r for r in raw.decode().splitlines() if r and not r.startswith("#") and "_value" not in r]
    total = 0
    for r in rows:
        try:
            total += int(r.split(",")[-1])
        except ValueError:
            pass
    return total


def cmd_verify():
    ok = True

    def check(name, fn):
        nonlocal ok
        try:
            msg = fn()
            print(f"  ok    {name}: {msg}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            ok = False
            print(f"  FAIL  {name}: {exc}")

    print("Bozshakol end-to-end check")
    cat = []

    def twins_exist():
        nonlocal cat
        cat = ditto_get(f"/things/{NS}:site?fields=attributes/catalog")["attributes"]["catalog"]
        ids = ",".join(f"{NS}:{c['id']}" for c in cat)
        got = ditto_get(f"/things?ids={ids}&fields=thingId,attributes/_parents,attributes/type")
        assert len(got) == len(cat), f"{len(got)} of {len(cat)} twins in Ditto"
        children = sum(1 for g in got if g.get("attributes", {}).get("_parents") == f"{NS}:site")
        assert children == len(cat) - 1, f"only {children} twins are children of {NS}:site"
        type_ids = sorted({g["attributes"]["type"] for g in got if g.get("attributes", {}).get("type")})
        types = ditto_get(f"/things?ids={','.join(type_ids)}&fields=thingId,attributes/_isType")
        assert len(types) == len(type_ids) and all(t["attributes"]["_isType"] is True for t in types), \
            f"{len(types)} of {len(type_ids)} types in Ditto"
        return (f"{len(got)} twins in Ditto, {children} are children of {NS}:site, "
                f"all instantiate {len(types)} OpenTwins types")

    def model_runs():
        a = twin("site")["sim_time"]
        time.sleep(6)
        b = twin("site")["sim_time"]
        assert a != b, "sim_time did not advance"
        return f"model time {a} -> {b} (MQTT -> Ditto live)"

    def history():
        n = influx_count()
        assert n > 50, f"only {n} points"
        return f"{n} points from site, haulage and gc-01 in InfluxDB over the last 3 min (Ditto -> Telegraf -> InfluxDB)"

    def ui():
        st, raw = http("GET", UI + "/")
        assert st == 200 and b"app.js" in raw
        st, raw = http("GET", UI + f"/ditto/api/2/things/{NS}:site?fields=attributes/name")
        assert st == 200
        return f"3D control room and its Ditto proxy answer on {UI}"

    def scenario_round_trip():
        before = twin("gc-01")["state"]
        cmd_scenario("crusher_outage")
        deadline = time.time() + 40
        state = before
        while time.time() < deadline:
            time.sleep(3)
            state = twin("gc-01")["state"]
            if state == "down":
                break
        lg = twin("lg-01").get("stock_kt")
        cmd_scenario("baseline")
        assert state == "down", f"crusher state stayed {state}"
        time.sleep(4)
        after = twin("gc-01")["state"]
        return f"crusher_outage: gc-01 {before} -> down (LG stockpile {lg} kt), reset -> {after}"

    check("twins", twins_exist)
    check("model", model_runs)
    check("history", history)
    check("ui", ui)
    check("what-if", scenario_round_trip)
    print("verify:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "status":
            return cmd_status()
        if cmd == "scenario":
            return cmd_scenario(rest[0] if rest else None)
        if cmd == "set":
            return cmd_set(rest)
        if cmd == "verify":
            return cmd_verify()
        if cmd == "wait":
            return cmd_wait()
        if cmd == "urls":
            return cmd_urls()
    except urllib.error.URLError as exc:
        print(f"ERROR: platform not reachable ({exc}). Is the stand up? make bozshakol", file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
