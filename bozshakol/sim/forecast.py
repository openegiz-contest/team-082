"""
What-if forecaster.

When the operator changes the scenario, a forked process copies the live
mine state and plays it forward twice for the forecast horizon: once with
the baseline control settings and once with the current ones. Both runs use
the same random seed (common random numbers), so the difference between them
is the effect of the scenario, not noise.
"""

import copy
import os
import multiprocessing as mp
import time

from .model import COMMAND_KEYS, CONTROL_DEFAULTS

HORIZON_H = 48.0
STEP_S = 20.0

KPI_LABELS = {
    "margin_mkzt": ("Операционная маржа", "млн ₸"),
    "cu_t": ("Медь в концентрате", "т"),
    "ore_t": ("Руда добыта", "т"),
    "waste_t": ("Вскрыша", "т"),
    "cos_end_kt": ("Склад крупного дробления в конце", "кт"),
    "mill_t": ("Переработка ОФ", "т"),
    "moved_t": ("Горная масса", "т"),
    "feed_grade": ("Содержание Cu в питании", "%"),
    "recovery": ("Извлечение Cu", "%"),
    "kwh_t": ("Удельный расход э/э", "кВт·ч/т"),
    "diesel_l": ("Дизельное топливо", "л"),
    "cost_mkzt": ("Затраты (э/э + ДТ + ВВ)", "млн ₸"),
    "cost_kzt_t_cu": ("Затраты на 1 т меди", "₸/т"),
    "co2_t": ("Выбросы CO₂", "т"),
    "fleet_avail": ("КТГ самосвалов", "%"),
    "queue_min": ("Ожидание у экскаватора", "мин"),
    "inband_pct": ("Время в коридоре качества", "%"),
    "failures": ("Отказы техники", "шт"),
    "cas_alerts": ("Срабатывания CAS", "шт"),
    "pq_ok_pct": ("Время в нормах ГОСТ 32144 (э/э)", "%"),
    # monthly planning: 48 h rates carried to a month and to six months
    "month_ore_kt": ("Руда за месяц (темп 48 ч)", "кт"),
    "month_cu_t": ("Медь за месяц (темп 48 ч)", "т"),
    "ore_east_pct": ("Доля руды Восточного карьера", "%"),
    "strip_central": ("Вскрыша/руда, Центральный", "т/т"),
    "strip_east": ("Вскрыша/руда, Восточный", "т/т"),
    "exposed6_central_mo": ("Вскрытая руда Центрального через 6 мес", "мес"),
    "exposed6_east_mo": ("Вскрытая руда Восточного через 6 мес", "мес"),
    "cu_6m_kt": ("Медь за 6 мес с учётом вскрытых запасов", "кт"),
    "ore_short_6m_kt": ("Недобор руды за 6 мес: нет вскрытой", "кт"),
}


FRAME_H = 4.0
DOWN = ("breakdown", "towing", "in_workshop", "down", "mantle_change")


def frame(m):
    """Spatial state of the forecast at one moment: per-twin values the 3D
    control room draws on the scene (cumulative from the forecast start)."""
    k = m.kpi
    trucks = m.trucks
    f = {
        "cos-01": {"v": round(m.cos["t"] / 1000, 1)},
        "lg-01": {"v": round(m.lg_stock["t"] / 1000, 1)},
        "wd-01": {"v": round(k["waste_t_central"] / 1000, 1)},
        "wd-02": {"v": round(k["waste_t_east"] / 1000, 1)},
        "pit-central": {"v": round(m.exposed_months("central"), 2)},
        "pit-east": {"v": round(m.exposed_months("east"), 2)},
        "sag-01": {"v": round(k["mill_t"] / 1000, 1), "s": m.sag.get("state", "running")},
        "th-c": {"v": round(k["cu_t"], 0)},
        "cp-01": {"v": round(k["clay_proc_t"] / 1000, 1)},
        "ss-220": {"v": round(k["mwh"], 0)},
        "fs-01": {"v": round(k["diesel_all_l"] / 1000, 1)},
        "gc-01": {"v": round(m.crusher.get("pocket", 0) / 7, 0), "s": m.crusher["state"]},
        "haulage": {"v": sum(1 for t in trucks if t.state not in DOWN and t.state not in ("standby", "parked", "to_park")),
                    "down": sum(1 for t in trucks if t.state in DOWN),
                    "queue": sum(1 for t in trucks if t.state in ("queue_loader", "queue_dump"))},
    }
    for ld in m.loaders.values():
        f[ld.id] = {"v": round(k[f"dug_{ld.id}"] / 1000, 1), "s": ld.state}
    return f


def project(mine, control, hours=HORIZON_H, step=STEP_S, seed=7, frames=None):
    m = copy.deepcopy(mine)
    m.mute = True
    m.reseed(seed)
    m.apply_control(control, quiet=True)
    m.reset_kpis()
    n = int(hours * 3600 / step)
    every = int(FRAME_H * 3600 / step)
    if frames is not None:
        frames.append(frame(m))
    for i in range(n):
        m.step(step)
        if frames is not None and (i + 1) % every == 0:
            frames.append(frame(m))
    return m.kpis()


def baseline_control(control):
    base = dict(CONTROL_DEFAULTS)
    base["sim_speed"] = control.get("sim_speed", base["sim_speed"])
    base["blast_now"] = control.get("blast_now", 0)
    base["plan_optimize"] = control.get("plan_optimize", 0)
    return base


def _worker(mine, control, conn):
    t0 = time.time()
    try:
        fb, fs = [], []
        base = project(mine, baseline_control(control), frames=fb)
        scen = project(mine, control, frames=fs)
        conn.send({"ok": True, "baseline": base, "scenario": scen, "control": control,
                   "frames": {"step_h": FRAME_H, "baseline": fb, "scenario": fs},
                   "at": mine.now.isoformat(), "calc_s": time.time() - t0})
    except Exception as exc:  # noqa: BLE001 - report any failure to the parent
        conn.send({"ok": False, "error": repr(exc)})
    finally:
        conn.close()


def scenario_differs(control):
    base = baseline_control(control)
    return any(control.get(k) != base[k] for k in base if k not in COMMAND_KEYS)


class Forecaster:
    def __init__(self):
        self.proc = None
        self.conn = None
        self.pending = False
        self.result = None
        self.started_at = None
        self.ctx = mp.get_context("fork")

    @property
    def busy(self):
        return self.proc is not None

    def request(self, mine):
        if self.busy:
            self.pending = True
            return
        parent, child = self.ctx.Pipe(duplex=False)
        self.conn = parent
        self.proc = self.ctx.Process(target=_worker, args=(mine, dict(mine.control), child), daemon=True)
        self.proc.start()
        child.close()
        self.started_at = time.time()
        self.pending = False

    def poll(self, mine):
        """Returns a new result dict when one has arrived, else None."""
        if not self.busy:
            if self.pending:
                self.request(mine)
            return None
        got = None
        if self.conn.poll():
            try:
                got = self.conn.recv()
            except EOFError:
                got = {"ok": False, "error": "forecast process ended without a result"}
        elif not self.proc.is_alive():
            got = {"ok": False, "error": "forecast process died"}
        elif time.time() - self.started_at > 120:
            self.proc.kill()
            got = {"ok": False, "error": "forecast timed out"}
        if got is None:
            return None
        self.proc.join(timeout=1)
        self.proc = None
        self.conn = None
        if got.get("ok"):
            self.result = got
        if self.pending:
            self.request(mine)
        return got


# ---------------------------------------------------------------------------
# Monthly plan auto-selection
# ---------------------------------------------------------------------------
# The planning meeting's levers. Each candidate is a full allocation; the
# planner plays every one forward from the same copy of the mine, with the same
# random numbers, and ranks them.
PLAN_KEYS = ("east_ore_share", "trucks_east", "trucks_777_east", "waste_central_tph", "waste_east_tph")
PLAN_CANDIDATES = [
    ("Больше вскрыши на обоих, 777D на Восточный", dict(east_ore_share=0.30, trucks_east=4, trucks_777_east=3, waste_central_tph=2400, waste_east_tph=1000)),
    ("Восточный: меньше руды, больше вскрыши", dict(east_ore_share=0.25, trucks_east=4, trucks_777_east=3, waste_central_tph=2300, waste_east_tph=1000)),
    ("Центральный: вскрыша вперёд", dict(east_ore_share=0.30, trucks_east=3, trucks_777_east=2, waste_central_tph=2800, waste_east_tph=800)),
    ("Восточный: руда и вскрыша вместе", dict(east_ore_share=0.35, trucks_east=5, trucks_777_east=3, waste_central_tph=2200, waste_east_tph=1100)),
    ("Ровно по плану 70/30", dict(east_ore_share=0.30, trucks_east=4, trucks_777_east=2, waste_central_tph=2600, waste_east_tph=800)),
    ("Нажать на Восточный", dict(east_ore_share=0.45, trucks_east=7, trucks_777_east=2, waste_central_tph=1900, waste_east_tph=500)),
    ("Вся вскрыша на Восточный", dict(east_ore_share=0.25, trucks_east=3, trucks_777_east=4, waste_central_tph=2600, waste_east_tph=1200)),
]
PLAN_MIN_MONTHS = 1.5     # exposed ore each pit must keep after six months (A)
PLAN_ORE_SHARE = 0.97     # month ore at least 97 % of the plant plan


def plan_feasible(k):
    """Hard limits of the planning meeting: each pit keeps at least
    PLAN_MIN_MONTHS of exposed ore after six months, and the plant gets at least
    PLAN_ORE_SHARE of its month ore plan."""
    from . import params as P
    low = min(k.get("exposed6_central_mo", 0.0), k.get("exposed6_east_mo", 0.0))
    return low >= PLAN_MIN_MONTHS and k.get("month_ore_kt", 0.0) >= PLAN_ORE_SHARE * P.ORE_PLAN_KT_MONTH


def plan_score(k):
    """Ranking: copper over six months net of the ore lost when a pit's exposed
    ore runs out (cu_6m_kt). Among plans that break the limits (used only when no
    plan keeps them) the one closest to the limits ranks first."""
    from . import params as P
    if plan_feasible(k):
        return k.get("cu_6m_kt", 0.0)
    low = min(k.get("exposed6_central_mo", 0.0), k.get("exposed6_east_mo", 0.0))
    ore_ratio = k.get("month_ore_kt", 0.0) / P.ORE_PLAN_KT_MONTH
    return -(max(0.0, PLAN_MIN_MONTHS - low) + 10.0 * max(0.0, PLAN_ORE_SHARE - ore_ratio))


def plan_candidates(control):
    """The current allocation and every listed alternative that differs from it."""
    cur = {k: control[k] for k in PLAN_KEYS}
    cands = [("Текущая расстановка", dict(control))]
    for name, alloc in PLAN_CANDIDATES:
        if all(abs(float(alloc[k]) - float(cur[k])) < 1e-9 for k in PLAN_KEYS):
            continue
        c = dict(control)
        c.update(alloc)
        cands.append((name, c))
    return cands


def _plan_one(mine, name, ctl, conn):
    try:
        k = project(mine, ctl, hours=HORIZON_H, step=STEP_S, seed=7)
        keep = ("cu_t", "margin_mkzt", "month_ore_kt", "month_cu_t", "cu_6m_kt", "ore_short_6m_kt",
                "exposed6_central_mo", "exposed6_east_mo", "traj_central", "traj_east", "diesel_l", "queue_min")
        conn.send({"ok": True, "name": name, "control": {kk: ctl[kk] for kk in PLAN_KEYS},
                   "kpi": {kk: k.get(kk) for kk in keep}, "score": plan_score(k), "feasible": plan_feasible(k)})
    except Exception as exc:  # noqa: BLE001
        conn.send({"ok": False, "name": name, "error": repr(exc)})
    finally:
        conn.close()


class Planner:
    """Plays every candidate plan forward in its own forked process (as the
    forecaster does), at most one per CPU at a time, and ranks them. Each
    process starts from the same copy of the mine and the same random seed."""

    def __init__(self):
        self.ctx = mp.get_context("fork")
        self.queue = []
        self.running = []
        self.done = []
        self.started_at = None
        self.mine_at = None
        self.result = None
        self.limit = max(1, min(8, (os.cpu_count() or 2) - 1))   # one candidate per spare core, at most 8

    @property
    def busy(self):
        return bool(self.queue or self.running)

    def request(self, mine):
        for proc, _, _ in self.running:
            proc.kill()
        self.queue = list(plan_candidates(dict(mine.control)))
        self.running, self.done = [], []
        self.snapshot = copy.deepcopy(mine)     # every candidate starts from this same state
        self.mine_at = mine.now.isoformat()
        self.started_at = time.time()

    def _launch(self, mine):
        while self.queue and len(self.running) < self.limit:
            name, ctl = self.queue.pop(0)
            parent, child = self.ctx.Pipe(duplex=False)
            proc = self.ctx.Process(target=_plan_one, args=(mine, name, ctl, child), daemon=True)
            proc.start()
            child.close()
            self.running.append((proc, parent, name))

    def poll(self, mine):
        if not self.busy:
            return None
        self._launch(self.snapshot)
        still = []
        for proc, conn, name in self.running:
            got = None
            if conn.poll():
                try:
                    got = conn.recv()
                except EOFError:
                    got = {"ok": False, "name": name, "error": "ended without a result"}
            elif not proc.is_alive():
                got = {"ok": False, "name": name, "error": "process died"}
            elif time.time() - self.started_at > 900:
                proc.kill()
                got = {"ok": False, "name": name, "error": "timed out"}
            if got is None:
                still.append((proc, conn, name))
            else:
                proc.join(timeout=1)
                self.done.append(got)
        self.running = still
        if self.busy:
            return None
        opts = [o for o in self.done if o.get("ok")]
        if not opts:
            return {"ok": False, "error": "; ".join(f"{o['name']}: {o.get('error')}" for o in self.done)}
        # Hard limits first: the best plan is chosen among the plans that keep
        # them; only when none does, the closest one is shown, flagged as such.
        feas = [i for i, o in enumerate(opts) if o["feasible"]]
        pool = feas or list(range(len(opts)))
        best = max(pool, key=lambda i: (opts[i]["feasible"], opts[i]["score"]))
        for i, o in enumerate(opts):
            o["best"] = i == best
            o["score"] = round(o["score"], 2)
            o.pop("ok", None)
        self.result = {"ok": True, "options": opts, "at": self.mine_at, "calc_s": time.time() - self.started_at,
                       "min_months": PLAN_MIN_MONTHS, "ore_share": PLAN_ORE_SHARE, "any_feasible": bool(feas)}
        return self.result
