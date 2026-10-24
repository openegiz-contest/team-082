"""
Condition monitoring of the mobile fleet: what the on-board systems really
measure, and a health index computed from those measurements only.

The simulator keeps a hidden "true" degradation of every machine (Asset.health,
0-100: wear grows with operating hours and load, the failure hazard grows
exponentially with it, service restores it). No real truck has a "health %"
sensor, so the twins do not publish it. They publish what the machine's own
monitoring reports:

  haul trucks (CAT VIMS / Product Link type data, tyre monitoring, oil lab)
    engine coolant temperature, engine oil pressure, exhaust temperature,
    transmission oil temperature, brake (retarder) oil temperature — heats up
    on downhill runs, tyre temperature and pressure, loads above the rated
    payload, active event codes, iron and silicon in the engine oil from the
    last oil sample (taken at every service);
  shovels / loader
    engine coolant, oil pressure, hydraulic oil temperature, peak working
    pressure and relief-valve events (EX3600-6 relief 29.4 MPa — passport),
    iron in the hydraulic oil;
  drills (Sandvik D55SP)
    engine coolant, oil pressure, compressor discharge temperature, delivered
    air pressure (6.9 bar nominal — passport), hydraulic oil temperature.

Each machine has its own weak point (engine, drivetrain and brakes, tyres or
hydraulics — random weights), so the same hidden wear shows in different
signals. The health index (0-100) is estimated from the smoothed deviations
of the signals from their expected values at the current load and ambient
temperature, plus the last oil sample — the way a reliability engineer reads
condition-monitoring data. Predictive maintenance (PdM) decides on this
estimate, not on the hidden truth, so it can be late or early, as in reality.

All nominal values and thresholds are engineering assumptions (A) unless
marked as passport values (S0, sim/equipment.py).
"""

import math
import random

from . import params as P

H = 3600.0

SUBSYS = {
    "truck": ("engine", "drive", "tyres"),
    "loader": ("engine", "hydraulics", "undercarriage"),
    "drill": ("engine", "compressor", "hydraulics"),
}
SUBSYS_RU = {"engine": "двигатель", "drive": "трансмиссия и тормоза", "tyres": "шины", "hydraulics": "гидросистема",
             "undercarriage": "ходовая часть", "compressor": "компрессор"}
RELIEF_MPA = {"Hitachi EX3600-6": 29.4, "CAT 993K": 27.6}   # EX3600-6: passport S0; 993K: (A)
AIR_BAR_NOMINAL = 6.9                                         # D55SP rotary: passport S0
HI_SCALE = 1.25        # max subsystem estimate that corresponds to an index of 0 (calibrated, see SUBMISSION)


def _ema(old, new, dt_s, tau_s):
    if old is None:
        return new
    return old + (new - old) * min(1.0, dt_s / tau_s)


def _init(a, kind, m):
    rng = random.Random(f"cm-{a.id}")
    w = [rng.uniform(0.4, 1.6) for _ in SUBSYS[kind]]
    s = sum(w) / len(w)
    a.cm_rng = rng
    a.cm_w = dict(zip(SUBSYS[kind], [x / s for x in w]))
    a.cm = {}
    # the last assessment before the model start: true wear seen through noise
    a.cm_est = {k: max(0.0, wear_of_w(a, k) * (1 + rng.gauss(0, 0.1))) for k in SUBSYS[kind]}
    a.cm_b = {}
    a.cm_running = False
    a.codes = []
    a.loads = a.overloads = 0
    a.relief_events = 0
    a.prev_z = None
    a.prev_state = None
    a.prev_since_pm = a.since_pm
    a.oil = None
    a.hi = a.health
    _oil_sample(a, kind, m, age_h=rng.uniform(5, P.PM_INTERVAL_H))


def wear_of_w(a, sub):
    return min(1.0, (1 - a.health / 100) * a.cm_w[sub])


def wear_of(a, sub):
    """Hidden wear of one subsystem, 0..1."""
    return min(1.0, (1 - a.health / 100) * a.cm_w[sub])


def dominant(a):
    return max(a.cm_w, key=lambda k: wear_of(a, k))


def _oil_sample(a, kind, m, age_h=0.0):
    rng = a.cm_rng
    sub = "engine" if kind != "loader" else "hydraulics"
    w = wear_of(a, sub)
    a.oil = {"fe": max(2.0, 8 + 70 * w ** 1.5 + rng.gauss(0, 3)), "si": max(2.0, 6 + rng.uniform(0, 12)),
             "age_h": age_h, "at": m.now.strftime("%d.%m %H:%M") if age_h == 0 else "до начала модели"}


def _codes(a, kind):
    c = a.cm
    out = []
    if not a.cm_running:
        return [("OIL-FE", 2, "железо в масле выше нормы")] if a.oil and a.oil["fe"] > 55 else []
    if c.get("coolant", 0) > 104:
        out.append(("E360", 2, "перегрев ОЖ двигателя"))
    if 0 < c.get("oil_kpa", 999) < 230:
        out.append(("E100", 3, "низкое давление масла двигателя"))
    if kind == "truck":
        if c.get("brake_c", 0) > 115:
            out.append(("E880", 2, "перегрев масла тормозов"))
        if c.get("trans_c", 0) > 110:
            out.append(("E445", 2, "перегрев масла трансмиссии"))
        if c.get("tyre_c", 0) > 82:
            out.append(("T210", 1, "высокая температура шин"))
        if 0 < c.get("tyre_kpa", 999) < 610:
            out.append(("T120", 2, "низкое давление в шине"))
    if kind == "loader" and c.get("hyd_c", 0) > 82:
        out.append(("H330", 2, "перегрев гидравлического масла"))
    if kind == "drill":
        if c.get("comp_c", 0) > 118:
            out.append(("C510", 2, "высокая температура компрессора"))
        if 0 < c.get("air_bar", 99) < 6.0:
            out.append(("C520", 1, "давление воздуха ниже номинала"))
    if a.oil and a.oil["fe"] > 55:
        out.append(("OIL-FE", 2, "железо в масле выше нормы"))
    return out


def _estimate(a, kind, base):
    """Subsystem condition estimates (0 good .. ~1 worn) from signal deviations, smoothed."""
    c = a.cm
    est = {}
    pos = lambda x: max(0.0, x)
    e = [pos((c["coolant"] - base["coolant"]) / 18) ** (1 / 1.5), pos((base["oil_kpa"] - c["oil_kpa"]) / 170) ** (1 / 1.3)]
    if a.oil and kind != "loader":
        e.append(pos((a.oil["fe"] - 8) / 70) ** (1 / 1.5))
    est["engine"] = sum(e) / len(e)
    if kind == "truck":
        est["drive"] = pos((c["trans_c"] - base["trans_c"]) / 30) ** (1 / 1.4)
        est["tyres"] = 0.5 * pos((c["tyre_c"] - base["tyre_c"]) / 15) + \
            0.5 * pos((690 + 0.3 * (c["tyre_c"] - 40) - c["tyre_kpa"]) / 41)
    elif kind == "loader":
        h = [pos((c["hyd_c"] - base["hyd_c"]) / 25) ** (1 / 1.3)]
        if a.oil:
            h.append(pos((a.oil["fe"] - 8) / 70) ** (1 / 1.5))
        est["hydraulics"] = sum(h) / len(h)
        est["undercarriage"] = pos((c["vib"] - base["vib"]) / 6)
    else:
        est["compressor"] = 0.5 * pos((c["comp_c"] - base["comp_c"]) / 25) + 0.5 * pos((AIR_BAR_NOMINAL - c["air_bar"]) / 0.8)
        est["hydraulics"] = pos((c["hyd_c"] - base["hyd_c"]) / 25) ** (1 / 1.3)
    return est


def _update(a, kind, m, dt_s, load, running, extra):
    if not hasattr(a, "cm"):
        _init(a, kind, m)
    rng = a.cm_rng
    amb = m.wx["temp"]
    c = a.cm
    we = wear_of(a, "engine")
    tau = 15 * 60
    base = {"coolant": 82 + 12 * load + 0.15 * max(0.0, amb - 20) if running else amb + 40,
            "oil_kpa": 400 - 40 * (1 - load) if running else 0.0}
    c["coolant"] = _ema(c.get("coolant"), base["coolant"] + (18 * we ** 1.5 if running else 0) + rng.gauss(0, 0.4), dt_s, tau)
    c["oil_kpa"] = _ema(c.get("oil_kpa"), max(0.0, base["oil_kpa"] - (170 * we ** 1.3 if running else 0) + rng.gauss(0, 5)), dt_s, 60)
    if kind == "truck":
        wd, wt = wear_of(a, "drive"), wear_of(a, "tyres")
        c["exhaust_c"] = _ema(c.get("exhaust_c"), (430 + 180 * load + 70 * we if running else amb + 20) + rng.gauss(0, 4), dt_s, 120)
        base["trans_c"] = 75 + 20 * load if running else amb + 25
        c["trans_c"] = _ema(c.get("trans_c"), base["trans_c"] + (30 * wd ** 1.4 if running else 0) + rng.gauss(0, 0.5), dt_s, 20 * 60)
        # brakes / retarder: heat from the potential energy dissipated on downhill runs
        z = a.pos[2] if a.pos else 0.0
        descent = max(0.0, (a.prev_z - z) / dt_s) if a.prev_z is not None else 0.0
        a.prev_z = z
        mass_t = a.empty + a.payload
        p_ret_kw = mass_t * 9.81 * descent
        c["brake_c"] = _ema(c.get("brake_c"), amb + 35 + 0.035 * p_ret_kw * (1 + 0.8 * wd) + rng.gauss(0, 0.5), dt_s, 8 * 60)
        speed = getattr(a, "v", 0.0)
        base["tyre_c"] = amb + 20 + 0.9 * speed * (0.6 + 0.8 * a.payload / max(1.0, a.cap))
        c["tyre_c"] = _ema(c.get("tyre_c"), base["tyre_c"] + 15 * wt + rng.gauss(0, 0.5), dt_s, 40 * 60)
        c["tyre_kpa"] = _ema(c.get("tyre_kpa"), 690 * (1 - 0.06 * wt) + 0.3 * (c["tyre_c"] - 40) + rng.gauss(0, 2), dt_s, 10 * 60)
        # payload policy: count each completed load (the passport payload is the reference)
        if a.prev_state == "loading" and a.state != "loading" and a.payload > 1:
            a.loads += 1
            if a.payload > a.cap:
                a.overloads += 1
        a.prev_state = a.state
    elif kind == "loader":
        wh, wu = wear_of(a, "hydraulics"), wear_of(a, "undercarriage")
        relief = RELIEF_MPA.get(a.model, 28.0)
        base["hyd_c"] = 55 + 20 * load if running else amb + 15
        c["hyd_c"] = _ema(c.get("hyd_c"), base["hyd_c"] + (25 * wh ** 1.3 if running else 0) + rng.gauss(0, 0.5), dt_s, 20 * 60)
        peak = (0.72 + 0.2 * load + 0.08 * wh) * relief + rng.gauss(0, 0.4) if extra.get("digging") else 0.25 * relief
        c["hyd_mpa"] = min(relief, peak)
        if peak >= relief and extra.get("digging"):
            a.relief_events += 1
        base["vib"] = 4 + 3 * load if running else 0.5
        c["vib"] = _ema(c.get("vib"), base["vib"] + 6 * wu + rng.gauss(0, 0.2), dt_s, 10 * 60)
    else:
        wc, wh = wear_of(a, "compressor"), wear_of(a, "hydraulics")
        base["comp_c"] = 85 + 25 * load if running else amb + 10
        c["comp_c"] = _ema(c.get("comp_c"), base["comp_c"] + (25 * wc if running else 0) + rng.gauss(0, 0.5), dt_s, 10 * 60)
        c["air_bar"] = (AIR_BAR_NOMINAL * (1 - 0.12 * wc) + rng.gauss(0, 0.04)) if extra.get("drilling") else 0.0
        if not extra.get("drilling"):
            c["air_bar_last"] = c.get("air_bar_last", AIR_BAR_NOMINAL)
        else:
            c["air_bar_last"] = c["air_bar"]
        base["hyd_c"] = 50 + 15 * load if running else amb + 10
        c["hyd_c"] = _ema(c.get("hyd_c"), base["hyd_c"] + (25 * wh ** 1.3 if running else 0) + rng.gauss(0, 0.5), dt_s, 20 * 60)
    # expected (healthy) values filtered with the same time constants as the signals
    lag = {"coolant": tau, "oil_kpa": 60, "trans_c": 20 * 60, "tyre_c": 40 * 60, "hyd_c": 20 * 60, "vib": 10 * 60, "comp_c": 10 * 60}
    for k, v in base.items():
        a.cm_b[k] = _ema(a.cm_b.get(k), v, dt_s, lag.get(k, tau))
    base = dict(a.cm_b)
    a.cm_running = running
    # oil sample at every service (since_pm is reset by the workshop / field service)
    if a.since_pm < a.prev_since_pm - 1e-6:
        _oil_sample(a, kind, m)
        # post-service diagnostics re-establish the condition estimate
        a.cm_est = {k: max(0.0, wear_of(a, k) * (1 + rng.gauss(0, 0.1))) for k in SUBSYS[kind]}
    a.prev_since_pm = a.since_pm
    if a.oil:
        a.oil["age_h"] += dt_s / H
    # estimates are updated only while the machine runs (signals at idle say little)
    if running:
        if kind == "drill" and not extra.get("drilling"):
            c_air = c["air_bar"]
            c["air_bar"] = c.get("air_bar_last", AIR_BAR_NOMINAL)
            est = _estimate(a, kind, base)
            c["air_bar"] = c_air
        else:
            est = _estimate(a, kind, base)
        for k, v in est.items():
            a.cm_est[k] = _ema(a.cm_est.get(k), v, dt_s, 2 * H)
    worst = max(a.cm_est.values()) if a.cm_est else 0.0
    a.hi = max(0.0, min(100.0, 100 * (1 - worst / HI_SCALE)))
    new_codes = _codes(a, kind)
    if not m.mute:
        old = {x[0] for x in a.codes}
        for code, lvl, text in new_codes:
            if code not in old and lvl >= 2:
                m.log("warn", f"{a.id.upper()}: код {code} — {text} (индекс техсостояния {a.hi:.0f} %)", a.id)
    a.codes = new_codes


def ensure(a, kind, m):
    if not hasattr(a, "cm"):
        _init(a, kind, m)
    return a


def update_all(m, dt_s):
    for t in m.trucks:
        running = t.state not in ("in_workshop", "breakdown", "towing", "parked", "standby", "idle")
        load = getattr(t, "power_frac", 0.1) if t.state in ("to_loader", "hauling", "to_fuel", "to_workshop", "to_park") else 0.15
        _update(t, "truck", m, dt_s, min(1.0, load), running, {})
    for ld in m.loaders.values():
        digging = ld.state == "loading"
        running = ld.state not in ("breakdown", "maintenance", "down")
        load = min(1.0, getattr(ld, "dig_rate", 0.0) / 1.2) if digging else 0.1
        _update(ld, "loader", m, dt_s, load, running, {"digging": digging})
    for d in m.drills:
        drilling = d.state == "drilling"
        running = d.state not in ("breakdown", "maintenance", "idle")
        _update(d, "drill", m, dt_s, 0.85 if drilling else 0.3, running, {"drilling": drilling})


def features(a, kind, feat, r):
    """Twin features (measured signals, codes, oil sample, computed index)."""
    c = a.cm
    fs = {"cm_engine_coolant": feat(r(c.get("coolant", 0)), "°C"),
          "cm_engine_oil_pressure": feat(r(c.get("oil_kpa", 0), 0), "кПа")}
    if kind == "truck":
        fs.update({
            "cm_exhaust_temp": feat(r(c.get("exhaust_c", 0), 0), "°C"),
            "cm_transmission_oil": feat(r(c.get("trans_c", 0)), "°C"),
            "cm_brake_oil": feat(r(c.get("brake_c", 0)), "°C"),
            "cm_tyre_temp": feat(r(c.get("tyre_c", 0)), "°C"),
            "cm_tyre_pressure": feat(r(c.get("tyre_kpa", 0), 0), "кПа"),
            "cm_loads": feat(a.loads, "шт"),
            "cm_overload_share": feat(r(a.overloads / a.loads * 100 if a.loads else 0.0), "%"),
        })
    elif kind == "loader":
        fs.update({
            "cm_hydraulic_oil": feat(r(c.get("hyd_c", 0)), "°C"),
            "cm_hydraulic_pressure": feat(r(c.get("hyd_mpa", 0)), "МПа"),
            "cm_relief_events": feat(a.relief_events, "шт"),
            "cm_vibration": feat(r(c.get("vib", 0)), "мм/с"),
        })
    else:
        fs.update({
            "cm_compressor_temp": feat(r(c.get("comp_c", 0)), "°C"),
            "cm_air_pressure": feat(r(c.get("air_bar", 0), 2), "бар"),
            "cm_hydraulic_oil": feat(r(c.get("hyd_c", 0)), "°C"),
        })
    if a.oil:
        fs["cm_oil_fe"] = feat(r(a.oil["fe"], 0), "ppm")
        fs["cm_oil_si"] = feat(r(a.oil["si"], 0), "ppm")
        fs["cm_oil_sample_age"] = feat(r(a.oil["age_h"], 0), "ч")
    fs["cm_codes"] = feat("; ".join(f"{c_} L{l}: {t}" for c_, l, t in a.codes) or "нет")
    fs["cm_codes_count"] = feat(len(a.codes), "шт")
    fs["cm_weak_point"] = feat(SUBSYS_RU[max(a.cm_est, key=a.cm_est.get)] if a.cm_est and max(a.cm_est.values()) > 0.15 else "не выявлено")
    fs["health"] = feat(r(a.hi), "%")
    return fs
