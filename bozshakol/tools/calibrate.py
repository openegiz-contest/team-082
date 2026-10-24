#!/usr/bin/env python3
"""Calibration of the model against Bozshakol's published production.

    python3 bozshakol/tools/calibrate.py            # seeds 1 7 42, ~1-2 min on 3+ cores
    python3 bozshakol/tools/calibrate.py 5 6        # other seeds

Runs the baseline (default controls) for 24 h of model time per seed, skips
the first 2 h (start-up of the plant), and compares the daily figures with
KAZ Minerals' FY 2023 results and the range of six published quarters
(Q1 2023 - Q2 2024) [S1]. This is the table in SUBMISSION.md, "Behaviour
fidelity". Needs only the standard library; no Docker.
"""

import os
import statistics as st
import sys
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim.model import Mine  # noqa: E402

# name, FY 2023 [S1], quarter range [S1], format
TARGETS = [
    ("ore_ktd", "Переработка (сульфидная + глинистая), кт/сут", 90.2, (87.6, 98.0), "{:.1f}"),
    ("feed_cu", "Cu в питании, %", 0.42, (0.40, 0.43), "{:.3f}"),
    ("rec_cu", "Извлечение Cu, %", 79.2, (76.8, 80.0), "{:.1f}"),
    ("cu_td", "Медь в концентрате, т/сут", 300.0, (276.0, 309.0), "{:.0f}"),
    ("feed_au", "Au в питании, г/т", 0.22, (0.20, 0.23), "{:.3f}"),
    ("rec_au", "Извлечение Au, %", 53.8, (46.1, 55.5), "{:.1f}"),
]
HOURS, WARMUP_S, DT = 24, 7200, 10.0


def run(seed):
    m = Mine(seed)
    m.mute = True
    sag = clay = cu = feedcu = rec_w = au_in = 0.0
    au0 = None
    for i in range(int(HOURS * 3600 / DT)):
        m.step(DT)
        if i * DT < WARMUP_S:
            continue
        if au0 is None:
            au0 = m.kpi.get("au_oz", 0.0)
        t = m.sag["tph"] * DT / 3600
        sag += t
        clay += m.clay_plant["tph"] * DT / 3600
        feedcu += t * m.cos["cu"]
        au_in += t * m.cos["au"]
        cu += (m.flot["cu_tph"] + m.clay_plant["cu_tph"]) * DT / 3600
        rec_w += t * m.flot["rec"]
    h = HOURS - WARMUP_S / 3600
    au_out = m.kpi.get("au_oz", 0.0) - (au0 or 0.0)
    return dict(ore_ktd=(sag + clay) / h * 24 / 1000, feed_cu=feedcu / sag, rec_cu=rec_w / sag * 100,
                cu_td=cu / h * 24, feed_au=au_in / sag, rec_au=au_out * 31.1035 / max(1.0, au_in) * 100)


def main():
    seeds = [int(a) for a in sys.argv[1:]] or [1, 7, 42]
    with Pool(min(len(seeds), max(1, (os.cpu_count() or 2) - 1))) as p:
        res = p.map(run, seeds)
    print(f"Калибровка: базовый режим, {HOURS} ч модели (первые {WARMUP_S // 3600} ч — пуск), сиды {seeds}")
    print(f"{'показатель':46s} {'модель':>8s} {'разброс':>15s} {'2023':>7s} {'откл.':>7s} {'кварталы':>13s}  в диапазоне")
    ok_all = True
    for key, label, fy, (lo, hi), fmt in TARGETS:
        v = [r[key] for r in res]
        mean = st.mean(v)
        dev = (mean - fy) / fy * 100
        ok = lo <= mean <= hi
        ok_all &= ok
        spread = f"{fmt.format(min(v))}–{fmt.format(max(v))}"
        print(f"{label:46s} {fmt.format(mean):>8s} {spread:>15s} {fmt.format(fy):>7s} {dev:+6.1f}% "
              f"{fmt.format(lo) + '–' + fmt.format(hi):>13s}  {'да' if ok else 'НЕТ'}")
    print("итог: " + ("все показатели в диапазоне кварталов" if ok_all else "есть показатели вне диапазона"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
