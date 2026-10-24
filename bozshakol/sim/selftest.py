"""
Regression checks of the model's conservation and limit rules.

    python3 -m sim.selftest        (or: make selftest)

Each check reproduces a defect found in review and asserts it is gone:
crusher pocket and clay hopper never over-filled by simultaneous tipping,
coarse ore stockpile never over-filled by ore on the belt, the capacity
charge counted once, no metal without ore fed, no diesel from an empty
station, no final ГОСТ 32144 verdict before a full one-week window, and
no two waiting trucks parked inside each other.
"""

import sys

from . import params as P
from . import twins as T
from .model import Mine

FAIL = []


def check(ok, msg):
    print(("  ok    " if ok else "  FAIL  ") + msg)
    if not ok:
        FAIL.append(msg)


def crusher_pocket():
    m = Mine(42)
    m.mute = True
    c = m.crusher
    c["pocket"] = 550.0
    trucks = [t for t in m.trucks if t.cls == "785"][:2]
    for tr in trucks:
        tr.dest, tr.payload, tr.state, tr.timer = "crusher", 136.0, "queue_dump", 0.0
    for tr in trucks:
        m._try_dump(tr)
    tipping = sum(1 for tr in trucks if tr.state == "dumping")
    check(tipping == 1, f"crusher: 550 t + two 136 t loads -> {tipping} truck(s) admitted (limit {P.CRUSHER_POCKET_T:.0f} t)")
    m2 = Mine(7)
    peak = clay = 0.0
    for _ in range(int(12 * 3600 / 2)):
        m2.step(2.0)
        peak = max(peak, m2.crusher["pocket"])
        clay = max(clay, m2.clay_plant["hopper"])
    check(peak <= P.CRUSHER_POCKET_T + 1e-6, f"crusher: max pocket over 12 h at 2 s steps {peak:.1f} t <= {P.CRUSHER_POCKET_T:.0f} t")
    check(clay <= P.CLAY_HOPPER_T + 1e-6, f"clay plant: max hopper {clay:.1f} t <= {P.CLAY_HOPPER_T:.0f} t")


def stockpile():
    m = Mine(42)
    m.mute = True
    m.cos["t"] = P.COS_TOTAL_T - 1.0
    m.sag["tph"] = 0.0
    m.control["crusher_down"] = False
    peak = 0.0
    for _ in range(int(2 * 3600 / 10)):
        m.sag["tph"] = 0.0                       # mill off: nothing leaves the stockpile
        m.step(10.0)
        peak = max(peak, m.cos["t"])
    check(peak <= P.COS_TOTAL_T + 1e-6, f"coarse ore stockpile: max {peak:,.0f} t <= {P.COS_TOTAL_T:,.0f} t with the mill stopped")


def capacity_charge():
    m = Mine(42)
    m.reset_kpis()
    k = m.kpi
    k["peak_mw_max"] = 75.0
    k["sim_s"] = 86400.0
    r = m.kpis()
    cap = 75.0 * P.CAPACITY_KZT_PER_MW_DAY / 1e6
    check(abs(r["cost_mkzt"] - cap) < 1e-6, f"capacity charge: cost {r['cost_mkzt']:.3f} M KZT = charge {cap:.3f}")
    check(abs(r["margin_mkzt"] + cap) < 1e-6, f"capacity charge: margin {r['margin_mkzt']:.3f} M KZT = −charge (counted once)")


def no_metal_without_feed():
    m = Mine(42)
    m.mute = True
    m.cos["t"] = 0.0
    m.conveyor.clear()
    m.crusher["pocket"] = 0.0
    m.clay_plant["hopper"] = 0.0
    m.lg_stock["t"] = 0.0
    for tr in m.trucks:
        tr.state, tr.payload = "parked", 0.0
    m.reset_kpis()
    m.step(10.0)
    k = m.kpi
    check(k["mill_t"] + k["clay_proc_t"] == 0 and k["cu_t"] == 0,
          f"metal: empty plant, fed {k['mill_t'] + k['clay_proc_t']:.1f} t -> Cu {k['cu_t'] * 1000:.1f} kg")


def dry_station():
    m = Mine(42)
    m.mute = True
    m.fuel_tank = 0.0
    tr = m.trucks[0]
    tr.fuel = 0.1 * tr.tank
    before = tr.fuel
    tr.state, tr.timer = "refueling", P.REFUEL_S
    m._truck(tr, 1.0)
    check(tr.fuel <= before + 1e-9 and tr.state == "refueling",
          f"diesel: empty station -> tank {before:.0f} -> {tr.fuel:.0f} l, truck {tr.state}")


def empty_tank():
    m = Mine(42)
    m.mute = True
    tr = next(t for t in m.trucks if t.state in ("to_loader", "hauling"))
    tr.fuel = 0.0
    before = tr.pos
    m._truck(tr, 2.0)
    moved = sum((a - b) ** 2 for a, b in zip(tr.pos, before)) ** 0.5
    check(moved == 0.0 and tr.state == "no_fuel", f"diesel: empty tank -> moved {moved:.2f} m in 2 s, truck {tr.state}")


def plan_limits():
    from .forecast import plan_feasible, plan_score
    ok = dict(exposed6_central_mo=2.0, exposed6_east_mo=1.6, month_ore_kt=2700.0, cu_6m_kt=50.0)
    bad = dict(exposed6_central_mo=6.0, exposed6_east_mo=0.4, month_ore_kt=2750.0, cu_6m_kt=60.0)
    check(plan_feasible(ok) and not plan_feasible(bad) and plan_score(ok) > plan_score(bad),
          "plan selection: a plan breaking the 1.5-month limit never outranks one that keeps it, whatever its copper")


def gost_window():
    m = Mine(42)
    m.mute = True
    for _ in range(int(11 * 60 / 10)):
        m.step(10.0)
    c = m.pq.compliance()
    s = {}
    T.standards_features(m, s)
    txt = s["pq-01"].get("compliance", {}).get("value", "")
    check(c["n"] >= 1 and not c["complete"] and txt.startswith("предварительно"),
          f"ГОСТ 32144: {c['n']} of 1008 intervals -> «{txt}»")


WAITING = ("queue_loader", "queue_dump", "standby", "in_workshop", "refueling", "parked")


def no_stacked_trucks():
    """Trucks that stand still (queues, reserve, workshop, fuel bay) each
    keep their own place: none closer than 5 m to another standing truck."""
    import math
    m = Mine(42)
    m.mute = True
    worst, samples = None, 0
    for i in range(int(6 * 3600 / 10)):
        m.step(10)
        if i % 30:
            continue
        samples += 1
        still = [t for t in m.trucks if t.state in WAITING]
        for a in range(len(still)):
            for b in range(a + 1, len(still)):
                d = math.dist(still[a].pos[:2], still[b].pos[:2])
                if worst is None or d < worst[0]:
                    worst = (d, still[a].state, still[b].state)
    d, sa, sb = worst or (99.0, "-", "-")
    check(d >= 5.0, f"trucks: closest two standing trucks over 6 h ({samples} samples) {d:.1f} m apart ({sa} / {sb}) >= 5 m")


def main():
    print("Bozshakol model self-test")
    for f in (crusher_pocket, stockpile, capacity_charge, no_metal_without_feed, dry_station, empty_tank, plan_limits,
              gost_window, no_stacked_trucks):
        f()
    print("selftest: " + ("FAILED" if FAIL else "ok"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
