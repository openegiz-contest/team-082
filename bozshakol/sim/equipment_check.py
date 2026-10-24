"""
Consistency check: passports (sim/equipment.py) vs the simulator (sim/params.py).

    python3 -m sim.equipment_check          # static checks + 6 h of simulation

The passport, the twin attributes and the simulator must describe one and the
same configuration. Exit code 1 on any mismatch.
"""
import sys

from . import params as P
from .equipment import PASSPORTS, BY_MODEL, spec


def _range(v):
    lo, hi = str(v).replace("…", "–").split("–")
    return float(lo), float(hi)


def static_checks():
    errs = []

    def check(ok, msg):
        if not ok:
            errs.append(msg)

    for model, t in P.TRUCK_MODELS.items():
        pid = BY_MODEL[model]
        check(t["payload"] == spec(pid, "payload_t"), f"{model}: payload {t['payload']} != passport")
        check(t["tank"] == spec(pid, "tank_l"), f"{model}: tank {t['tank']} != passport")
        check(abs(t["gmw"] * 1000 - spec(pid, "gmw_kg")) < 1, f"{model}: GMW != passport")
        check(t["empty"] + t["payload"] <= t["gmw"], f"{model}: empty + payload > GMW")
    for ld in P.LOADERS:
        pid = BY_MODEL[ld["model"]]
        lo, hi = _range(spec(pid, "bucket_m3"))
        check(lo <= ld["bucket"] <= hi, f"{ld['id']}: bucket {ld['bucket']} outside passport {lo}-{hi} m3")
        if "rated_t" in PASSPORTS[pid]["specs"]:
            check(ld.get("rated_t") == spec(pid, "rated_t"), f"{ld['id']}: rated load not taken from passport")
    lo, hi = _range(spec("sandvik-d55sp", "hole_mm"))
    check(lo <= P.HOLE_D_M * 1000 <= hi, "D55SP: hole diameter outside passport")
    check(P.SAG_MW == spec("abb-gmd-sag", "drive_mw"), "SAG drive != ABB 28 MW")
    check(P.BM_MW == spec("abb-gmd-ball", "drive_mw"), "Ball mill drive != ABB 22 MW")
    check(P.SAG_DRAW_MAX <= P.SAG_MW and P.BM_DRAW <= P.BM_MW, "mill draw above installed drive")
    check(P.CRUSHER_KW == spec("metso-mkiii-60-89", "power_kw"), "crusher kW != Metso MKIII 60-89")
    check(P.FLOT_VOL_M3 == spec("metso-tankcell-e300", "line_m3"), "rougher volume != 8 x e300")
    check(abs(P.WATER_TRUCK_M3 * 1000 - spec("cat-777-water", "tank_l")) < 1, "water tank != 75,700 L")
    check(P.DUST_MIN_TEMP_C == _range(spec("tsi-dusttrak-8543", "temp_c"))[0], "DustTrak temperature limit")
    check(P.CONVEYOR_TPH <= spec("takraf-belt", "family_tph_max"), "conveyor above TAKRAF family limit")
    return errs


def dynamic_checks(hours=6.0):
    from .model import Mine
    m = Mine(42)
    errs, worst = [], {}
    for _ in range(int(hours * 360)):
        m.step(10.0)
        for t in m.trucks:
            gross = t.empty + t.payload
            worst[t.model] = max(worst.get(t.model, 0.0), gross)
        if m.gas["co"] > 2000:
            errs.append("CO above the X-am 8000 range")
    for model, g in worst.items():
        gmw = P.TRUCK_MODELS[model]["gmw"]
        if g > gmw + 1e-6:
            errs.append(f"{model}: gross {g:.1f} t > GMW {gmw} t")
        print(f"  {model}: max gross {g:.1f} t of GMW {gmw} t")
    ld = m.loaders["ld-01"]
    avg = ld.tonnes / max(1, ld.passes)
    rated = spec("cat-993k", "rated_t")
    print(f"  CAT 993K: {ld.passes} passes, mean {avg:.1f} t per pass (rated load {rated} t)")
    if avg > rated:
        errs.append("CAT 993K: mean pass above rated load")
    return errs


def main():
    errs = static_checks()
    print(f"static: {'ok' if not errs else 'FAIL'}")
    if "--static" not in sys.argv:
        errs += dynamic_checks()
    for e in errs:
        print("  ERROR", e)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
