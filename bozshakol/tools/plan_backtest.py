#!/usr/bin/env python3
"""Does the plan the twin recommends hold up on random events it has not seen?

    python3 bozshakol/tools/plan_backtest.py          # 10 unseen seeds, ~3-6 min on 8 cores
    python3 bozshakol/tools/plan_backtest.py 20       # more seeds

"Подобрать план" ranks the candidate plans on ONE set of random numbers
(seed 7 in sim/forecast.py: failures, cycle times, grades) so that the
difference between plans is the effect of the plan, not noise. This check
replays the chosen plan and the current plan from the same mine state on N
other seeds the planner never used, and counts how often each still meets
the hard conditions (>= 1.5 months of exposed ore in each pit in 6 months,
ore to the plant >= 97 % of the plan). It is the table in SUBMISSION.md,
"Behaviour fidelity". Standard library only; no Docker.
"""

import os
import statistics as st
import sys
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim import forecast as F  # noqa: E402
from sim.model import CONTROL_DEFAULTS, Mine  # noqa: E402

KEYS = [("month_ore_kt", "Руда фабрике за месяц, кт", "{:.0f}"),
        ("cu_6m_kt", "Медь за 6 мес с учётом запасов, кт", "{:.2f}"),
        ("exposed6_central_mo", "Вскрытая руда Центрального через 6 мес, мес", "{:.2f}"),
        ("exposed6_east_mo", "Вскрытая руда Восточного через 6 мес, мес", "{:.2f}")]
STATE = None


def _state():
    m = Mine(42)
    m.mute = True
    for _ in range(360):          # 1 h, as the pult does before the first forecast
        m.step(10)
    return m


def _score(args):
    name, ctl = args
    return F.plan_score(F.project(STATE, ctl)), name


def _run(args):
    which, ctl, seed = args
    k = F.project(STATE, ctl, seed=seed)
    return which, seed, {key: k[key] for key, *_ in KEYS}, F.plan_feasible(k)


def _init():
    global STATE
    STATE = _state()


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    seeds = list(range(101, 101 + n))
    cur = dict(CONTROL_DEFAULTS)
    cands = []
    for name, ctl in F.PLAN_CANDIDATES:
        c = dict(cur)
        c.update(ctl)
        cands.append((name, c))
    with Pool(max(1, min(8, (os.cpu_count() or 2) - 1)), initializer=_init) as p:
        best_name = max(p.map(_score, cands))[1]          # the planner's pick on its own seed 7
        best = dict(cands)[best_name]
        print(f"Подбор плана (сид 7) выбрал: «{best_name}»")
        jobs = [(w, c, s) for w, c in (("текущий", cur), ("рекомендованный", best)) for s in seeds]
        res = p.map(_run, jobs)
    print(f"Проверка на {n} новых наборах случайных событий (сиды {seeds[0]}–{seeds[-1]}): среднее (мин–макс)")
    for which in ("текущий", "рекомендованный"):
        rr = [r for r in res if r[0] == which]
        print(f"\n  план: {which}")
        for key, label, fmt in KEYS:
            v = [r[2][key] for r in rr]
            print(f"    {label:46s} {fmt.format(st.mean(v)):>8s} ({fmt.format(min(v))}–{fmt.format(max(v))})")
        print(f"    {'выполняет жёсткие условия':46s} {sum(r[3] for r in rr)} из {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
