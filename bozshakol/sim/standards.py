"""Normative quality control inside the twin: the standards as working rules.

PowerQuality (twin pq-01) — ГОСТ 32144-2013 «Нормы качества электрической
энергии в системах электроснабжения общего назначения», network 110–220 kV,
at the point of transfer (ПС 220 кВ):
  * frequency deviation Δf: ±0,2 Гц 95 % / ±0,4 Гц 100 % of a week;
  * voltage deviation δU(−), δU(+): ≤ 10 % for 100 % of a week;
  * total harmonic factor K_U: 2,0 % (95 %) / 3,0 % (100 %), table 4–5;
    5th harmonic K_U(5): 1,5 % (95 %) / ×1,5 (100 %), 7th: 1,0 %, table 1;
  * negative-sequence unbalance K_2U: 2 % (95 %) / 4 % (100 %);
  * flicker: P_st ≤ 1,38, P_lt ≤ 1,0;
  * every quantity averaged over 10-minute intervals, compliance judged on
    a one-week window (1008 intervals).
  The gearless SAG and ball-mill drives (cycloconverters) are the harmonic
  sources; the harmonic filter / compensation bank (ФКУ) is an operator
  control (scenario «ФКУ отключена»).

QCLab (twin lab-01) — sampling and testing of the mill feed and of the
concentrate, one lot = one shift (ГОСТ 14180-80, прил. 2, п. 1):
  * ГОСТ 14180-80: point-sample mass m = Q·b / (3600·v) (ф. 1), slot of a pulp
    sampler b ≥ 4 мм (прил. 2, п. 3), number of point samples for a moving
    stream N = 4V²/Δ² (ф. 3), sampling period T = 60·M/(Q·N) (ф. 5), combined
    sample = m·N (п. 3.7), category of homogeneity and minimum mass after
    reduction m = K·d² (табл. 4, ф. 7); V unknown → 35 % for ore, 5 % for the
    main component of a concentrate (п. 3.5.2);
  * ГОСТ 13170-80: moisture by drying at 105–110 °C, W = (m1−m2)/(m1−m3)·100,
    two parallel determinations, admissible discrepancy by the table of
    п. 4.2, repeat and the 4-result rule otherwise;
  * ГОСТ 24598-81: size analysis of the flotation feed, minimum sample mass
    q = 0,02·d² + 0,5·d (кг, d — мм), sieves with module √2 from 0,04 мм,
    class −0,04 мм by sedimentation, mass loss ≤ 2 % (п. 5.2), yields to 0,1 %;
  * three-product metallurgical balance ε = c(f − t) / (f(c − t)) on the shift
    assays, compared with the plant's own figure.
"""

import collections
import math

from . import params as P

H = 3600.0

# ГОСТ 32144-2013, 110–220 kV
PQ_NORMS = {
    "freq": (0.2, 0.4),        # Гц, 95 % / 100 %
    "volt": (None, 10.0),      # %, 100 %
    "ku": (2.0, 3.0),          # %, табл. 4 / табл. 5
    "ku5": (1.5, 2.25),        # %, табл. 1 and ×1,5
    "ku7": (1.0, 1.5),
    "k2u": (2.0, 4.0),
    "pst": (None, 1.38),
    "plt": (None, 1.0),
}
WEEK_INTERVALS = 1008          # 7 сут × 144 интервала по 10 мин
S_SC_MVA = 3200.0              # short-circuit power of the 220 kV bus (A)

# ГОСТ 13170-80, п. 4.2: admissible discrepancy between parallel determinations
MOIST_TOL = [(1, 0.1), (2, 0.2), (5, 0.3), (10, 0.4), (15, 0.5), (1e9, 0.6)]
# ГОСТ 14180-80, табл. 4: category of homogeneity by V, K and the minimum masses
HOMOGENEITY = [(13, "весьма однородная", 0.06), (20, "однородная", 0.10), (33, "среднеоднородная", 0.15),
               (1e9, "неоднородная", 0.20)]
# ГОСТ 24598-81: sieve series with module √2 from 0.04 mm
SIEVES_MM = [0.04, 0.056, 0.08, 0.112, 0.16, 0.224, 0.315]

SAMPLER_SLOT_MM = 4.0          # прил. 2, п. 3: не менее 4 мм
SAMPLER_SPEED_MS = 0.45        # cutter speed (A)
DELTA_ORE_PCT = 5.0            # admissible relative sampling error of the feed assay, P = 0,95 (A)
MAX_PERIOD_MIN = 30.0          # plant practice: a point sample at least every 30 min (A)
DELTA_CONC_PCT = 1.1           # same for the concentrate: the worked example of ГОСТ 14180 п. 3.6.2
ASSAY_SD_REL = {"feed": 0.02, "conc": 0.006, "tails": 0.04}   # analytical precision (A)


def moisture_tolerance(w):
    for hi, tol in MOIST_TOL:
        if w <= hi:
            return tol
    return 0.6


def homogeneity(v):
    for hi, name, k in HOMOGENEITY:
        if v <= hi:
            return name, k
    return HOMOGENEITY[-1][1], HOMOGENEITY[-1][2]


class PowerQuality:
    def __init__(self, rng):
        self.rng = rng
        self.cur = dict(freq=0.0, volt=1.5, ku=1.0, ku5=0.8, ku7=0.55, k2u=0.6, pst=0.35, plt=0.35)
        self.acc = collections.defaultdict(float)
        self.acc_t = 0.0
        self.intervals = collections.deque(maxlen=WEEK_INTERVALS)
        self.f_state = 0.0
        self.dips = 0
        self.last_dip = None
        self.pst_hist = collections.deque(maxlen=12)   # P_lt = cubic mean of 12 P_st (2 h)
        self.prev_drive = None
        self.prev_running = None
        self.violation = None

    def step(self, m, dt_s):
        sag, bm = m.sag, m.bm
        drive = sag["power"] + sum(b["power"] for b in bm)
        filt = bool(m.control.get("harmonic_filter", True))
        rng = self.rng
        # Harmonics from the cycloconverter drives of the gearless mills.
        k_raw = 2.9 * drive / (P.SAG_DRAW_MAX + 2 * 13.0) * (3200.0 / S_SC_MVA)
        k_eff = k_raw * (0.3 if filt else 1.0)
        ku = math.sqrt(0.5 ** 2 + k_eff ** 2) * (1 + rng.gauss(0, 0.04))
        # Frequency: an Ornstein–Uhlenbeck walk of the national grid.
        self.f_state += -self.f_state * dt_s / 600 + rng.gauss(0, 0.012) * math.sqrt(dt_s / 60)
        freq = self.f_state
        # Voltage at the 220 kV point of transfer: load drop, OLTC and the capacitive filter.
        volt = 2.0 - 3.6 * m.energy.get("mw", 70) / 80 + (1.3 if filt else 0.0) + rng.gauss(0, 0.25)
        # Flicker: load swings and mill starts.
        swing = abs(drive - self.prev_drive) if self.prev_drive is not None else 0.0
        self.prev_drive = drive
        running = [sag["state"] == "running" and sag["tph"] > 300] + [b["state"] == "running" and b["power"] > 1 for b in bm]
        started = self.prev_running is not None and any(r and not p for r, p in zip(running, self.prev_running))
        self.prev_running = running
        pst = 0.28 + 0.06 * drive / 50 + min(1.5, 0.5 * swing) + (1.1 if started else 0.0) + abs(rng.gauss(0, 0.03))
        # Voltage dip when a gearless mill is started (A): residual 84–90 %, 0,2–0,6 s.
        if started:
            self.dips += 1
            self.last_dip = (round(rng.uniform(84, 90), 1), round(rng.uniform(0.2, 0.6), 2))
            m.log("warn", f"ПС 220 кВ: провал напряжения при пуске мельницы — остаточное {self.last_dip[0]} %, "
                          f"{self.last_dip[1]} с (ГОСТ 32144, прил. А)", "pq-01")
        self.cur = dict(freq=freq, volt=volt, ku=ku, ku5=0.82 * k_eff + 0.25, ku7=0.55 * k_eff + 0.15,
                        k2u=0.55 + 0.25 * drive / 50 + rng.gauss(0, 0.05), pst=pst)
        # 10-minute aggregation.
        for k, v in self.cur.items():
            self.acc[k] += (abs(v) if k == "freq" else v) * dt_s
        self.acc_t += dt_s
        if self.acc_t >= 600:
            iv = {k: self.acc[k] / self.acc_t for k in self.cur}
            iv["volt_abs"] = abs(iv["volt"])
            self.pst_hist.append(iv["pst"])
            iv["plt"] = (sum(p ** 3 for p in self.pst_hist) / len(self.pst_hist)) ** (1 / 3)
            self.intervals.append(iv)
            self.acc = collections.defaultdict(float)
            self.acc_t = 0.0
            bad, keys = self.check_interval(iv)
            m.kpi["pq_n"] = m.kpi.get("pq_n", 0) + 1
            m.kpi["pq_ok"] = m.kpi.get("pq_ok", 0) + (0 if keys else 1)
            if keys != self.violation:
                if bad:
                    m.log("alarm" if "100 %" in bad else "warn", f"Качество электроэнергии (ГОСТ 32144-2013): {bad}", "pq-01")
                elif self.violation:
                    m.log("info", "Качество электроэнергии вернулось в нормы ГОСТ 32144-2013", "pq-01")
            self.violation = keys

    @staticmethod
    def check_interval(iv):
        msgs, keys = [], []
        if iv["ku"] > PQ_NORMS["ku"][1]:
            msgs.append(f"K_U {iv['ku']:.2f} % > 3,0 % (норма 100 % времени, табл. 5)")
            keys.append("ku100")
        elif iv["ku"] > PQ_NORMS["ku"][0]:
            msgs.append(f"K_U {iv['ku']:.2f} % > 2,0 % (допускается не более 5 % времени недели, табл. 4)")
            keys.append("ku95")
        if iv["ku5"] > PQ_NORMS["ku5"][1]:
            msgs.append(f"K_U(5) {iv['ku5']:.2f} % > 2,25 % (1,5 % × 1,5 — норма 100 % времени, табл. 1)")
            keys.append("ku5_100")
        elif iv["ku5"] > PQ_NORMS["ku5"][0]:
            msgs.append(f"K_U(5) {iv['ku5']:.2f} % > 1,5 % (табл. 1)")
            keys.append("ku5_95")
        if iv["freq"] > PQ_NORMS["freq"][0]:
            msgs.append(f"Δf {iv['freq']:.2f} Гц > 0,2 Гц")
            keys.append("freq")
        if iv["volt_abs"] > PQ_NORMS["volt"][1]:
            msgs.append(f"δU {iv['volt']:.1f} % вне ±10 % (норма 100 % времени)")
            keys.append("volt")
        return ("; ".join(msgs) or None), tuple(keys)

    def compliance(self):
        """Share of the 10-minute intervals of the (up to one-week) window within each norm."""
        ivs = list(self.intervals)
        n = len(ivs)
        if not n:
            return dict(n=0)
        share = lambda key, lim: 100.0 * sum(1 for iv in ivs if iv[key] <= lim) / n  # noqa: E731
        mx = lambda key: max(iv[key] for iv in ivs)  # noqa: E731
        res = dict(
            n=n,
            ku_95=share("ku", PQ_NORMS["ku"][0]), ku_max=mx("ku"),
            ku5_95=share("ku5", PQ_NORMS["ku5"][0]), ku5_max=mx("ku5"),
            freq_95=share("freq", PQ_NORMS["freq"][0]), freq_max=mx("freq"),
            volt_max=mx("volt_abs"), k2u_95=share("k2u", PQ_NORMS["k2u"][0]), k2u_max=mx("k2u"),
            pst_max=mx("pst"), plt_max=mx("plt"),
        )
        ok = (res["ku_95"] >= 95 and res["ku_max"] <= PQ_NORMS["ku"][1] and res["ku5_95"] >= 95
              and res["ku5_max"] <= PQ_NORMS["ku5"][1] and res["freq_95"] >= 95 and res["freq_max"] <= PQ_NORMS["freq"][1]
              and res["volt_max"] <= PQ_NORMS["volt"][1] and res["k2u_95"] >= 95 and res["k2u_max"] <= PQ_NORMS["k2u"][1]
              and res["pst_max"] <= PQ_NORMS["pst"][1] and res["plt_max"] <= PQ_NORMS["plt"][1])
        res["ok"] = ok
        # ГОСТ 32144-2013, п. 4.2: conformity is judged on a full one-week window.
        # Until it is full the result is only a preliminary estimate.
        res["complete"] = n >= WEEK_INTERVALS
        res["coverage_pct"] = 100.0 * n / WEEK_INTERVALS
        return res


class QCLab:
    """Shift sampling plan, assays, moisture and size analysis of the plant."""

    def __init__(self, rng):
        self.rng = rng
        self.acc = self._empty()
        self.last = None          # results of the last closed shift
        self.shifts = 0

    @staticmethod
    def _empty():
        return dict(t=0.0, mill_t=0.0, cu_t=0.0, conc_t=0.0, conc_cu_t=0.0, tails_t=0.0, tails_cu_t=0.0,
                    rec_w=0.0, grades=[], clay_w=0.0, p80_w=0.0, rain_w=0.0, acc_g=0.0, acc_gt=0.0)

    def step(self, m, dt_s):
        a = self.acc
        dth = dt_s / H
        sag, f, cos = m.sag, m.flot, m.cos
        t = sag["tph"] * dth
        a["t"] += dt_s
        a["mill_t"] += t
        a["cu_t"] += t * cos["cu"] / 100
        a["conc_t"] += f["conc_tph"] * dth
        a["conc_cu_t"] += f["conc_tph"] * dth * f["conc_grade"] / 100
        tails = max(sag["tph"] - f["conc_tph"], 0) * dth
        a["tails_t"] += tails
        a["tails_cu_t"] += tails * f["tails_cu"] / 100
        a["rec_w"] += t * f["rec"]
        a["clay_w"] += t * cos["clay"]
        a["p80_w"] += t * m.p80
        a["rain_w"] += dt_s * m.wx.get("rain", 0.0)
        # 10-minute composite grades for the coefficient of variation (ГОСТ 14180, прил. 1)
        a["acc_g"] += t * cos["cu"]
        a["acc_gt"] += t
        if a["t"] - 600 * len(a["grades"]) >= 600 and a["acc_gt"] > 0:
            a["grades"].append(a["acc_g"] / a["acc_gt"])
            a["acc_g"] = a["acc_gt"] = 0.0

    def plan(self, q_tph, lot_t, grades, conc_lot_t, conc_tph):
        """Sampling plan by ГОСТ 14180-80 for the mill feed and for the concentrate lot."""
        if len(grades) >= 6:
            mean = sum(grades) / len(grades)
            sd = math.sqrt(sum((g - mean) ** 2 for g in grades) / (len(grades) - 1))
            v = max(3.0, sd / mean * 100)
            v_src = f"по {len(grades)} 10-минутным пробам смены (прил. 1)"
        else:
            v = 35.0
            v_src = "неизвестен → 35 % для руды (п. 3.5.2)"
        q = max(q_tph, 1.0)
        m_point = q * SAMPLER_SLOT_MM / (3600 * SAMPLER_SPEED_MS)                   # ф. (1), кг твёрдого
        n_min = max(1, math.ceil(4 * v ** 2 / DELTA_ORE_PCT ** 2))                    # ф. (3)
        hours = lot_t / q if lot_t > 0 else 12.0
        n = max(n_min, math.ceil(hours * 60 / MAX_PERIOD_MIN))                         # practice: not rarer than 30 min (A)
        period = 60 * lot_t / (q * n) if lot_t > 0 else 0.0                            # ф. (5), мин
        cat, k = homogeneity(v)
        n_conc = max(1, math.ceil(4 * 5.0 ** 2 / DELTA_CONC_PCT ** 2))                 # V = 5 % (п. 3.5.2)
        return dict(v=v, v_src=v_src, m_point=m_point, n=n, n_min=n_min, period=period, combined=m_point * n, category=cat, k=k,
                    m_min_20=k * 20 ** 2, m_min_10=k * 10 ** 2, m_min_3=k * 3 ** 2,
                    n_conc=n_conc, period_conc=60 * conc_lot_t / (max(conc_tph, 0.1) * n_conc) if conc_lot_t > 0 else 0.0)

    def moisture(self, w_true):
        """ГОСТ 13170-80: two parallel determinations, repeat when the discrepancy is too large."""
        rng = self.rng
        d = [w_true + rng.gauss(0, 0.12) for _ in range(2)]
        tol = moisture_tolerance(w_true)
        repeated = False
        if abs(d[0] - d[1]) > tol:
            repeated = True
            d += [w_true + rng.gauss(0, 0.12) for _ in range(2)]
            if abs(d[2] - d[3]) <= tol:
                final = (d[2] + d[3]) / 2
            else:
                s = sorted(d)
                final = (s[1] + s[2]) / 2          # drop max and min of the four
        else:
            final = (d[0] + d[1]) / 2
        return dict(final=round(final, 1), d1=round(d[0], 2), d2=round(d[1], 2), tol=tol, repeated=repeated)

    @staticmethod
    def sieve(p80_um, clay):
        """ГОСТ 24598-81: yields of the √2 classes of the flotation feed (Rosin–Rammler, n = 0,9)."""
        n = 0.9
        x63 = p80_um / 1000 / math.log(5) ** (1 / n)
        F = lambda x: 1 - math.exp(-(x / x63) ** n)  # noqa: E731
        slimes_boost = max(0.0, clay - 0.05) * 0.6
        passing = [min(1.0, F(s) + slimes_boost * (1 - F(s))) for s in SIEVES_MM]
        yields = {}
        prev = 1.0
        for s, p in reversed(list(zip(SIEVES_MM, passing))):
            yields[s] = prev - p
            prev = p
        yields[0.0] = passing[0]          # −0,04 мм: sedimentation (п. 4.3)
        d_max = SIEVES_MM[-1]
        for s, p in zip(SIEVES_MM, passing):
            if p >= 0.95:
                d_max = s
                break
        return dict(yields=yields, minus_008=passing[2] * 100, minus_004=passing[0] * 100, plus_0224=(1 - passing[5]) * 100,
                    q_min=0.02 * d_max ** 2 + 0.5 * d_max, d_max=d_max)

    def close_shift(self, m, shift_id):
        a = self.acc
        if a["mill_t"] < 500:
            self.acc = self._empty()
            return
        rng = self.rng
        f_true = a["cu_t"] / a["mill_t"] * 100
        c_true = a["conc_cu_t"] / max(a["conc_t"], 1e-6) * 100
        t_true = a["tails_cu_t"] / max(a["tails_t"], 1e-6) * 100
        fa = f_true * (1 + rng.gauss(0, ASSAY_SD_REL["feed"]))
        ca = c_true * (1 + rng.gauss(0, ASSAY_SD_REL["conc"]))
        ta = t_true * (1 + rng.gauss(0, ASSAY_SD_REL["tails"]))
        eps_lab = ca * (fa - ta) / (fa * (ca - ta)) * 100 if fa > ta and ca > ta else 0.0
        eps_plant = a["rec_w"] / a["mill_t"] * 100
        clay = a["clay_w"] / a["mill_t"]
        p80 = a["p80_w"] / a["mill_t"]
        rain_h = a["rain_w"] / max(a["t"], 1)
        hours = a["t"] / H
        q = a["mill_t"] / max(hours, 1e-6)
        plan = self.plan(q, a["mill_t"], a["grades"], a["conc_t"], a["conc_t"] / max(hours, 1e-6))
        w_conc_true = min(13.0, max(7.0, 8.6 + 9 * max(0.0, clay - 0.05) + 0.012 * (165 - p80)))
        w_ore_true = min(9.0, max(2.0, 3.2 + 6 * clay + 0.5 * rain_h))
        wc = self.moisture(w_conc_true)
        wo = self.moisture(w_ore_true)
        sv = self.sieve(p80, clay)
        self.last = dict(shift=shift_id, hours=hours, mill_t=a["mill_t"], conc_t=a["conc_t"],
                         feed=fa, conc=ca, tails=ta, eps_lab=eps_lab, eps_plant=eps_plant, plan=plan,
                         w_conc=wc, w_ore=wo, conc_wet_t=a["conc_t"] / (1 - wc["final"] / 100), sieve=sv, p80=p80)
        self.shifts += 1
        m.log("info", f"ОТК (ГОСТ 14180/13170/24598), смена {shift_id}: {plan['n']} точечных проб по {plan['m_point']:.1f} кг; "
                      f"Cu питание {fa:.3f} %, конц. {ca:.1f} %, хвосты {ta:.3f} %; ε по 3 продуктам {eps_lab:.1f} % "
                      f"(фабрика {eps_plant:.1f} %); влага конц. {wc['final']:.1f} %; −0,08 мм {sv['minus_008']:.1f} %", "lab-01")
        if wc["repeated"]:
            m.log("info", f"ОТК: расхождение параллельных определений влаги {abs(wc['d1'] - wc['d2']):.2f} % > {wc['tol']} % — "
                          "повторное определение (ГОСТ 13170, п. 4.2)", "lab-01")
        if abs(eps_lab - eps_plant) > 2.5:
            m.log("warn", f"ОТК: невязка металлургического баланса {eps_lab - eps_plant:+.1f} п.п. — проверить пробоотбор "
                          "и аналитику", "lab-01")
        if sv["minus_004"] > 45:
            m.log("warn", f"ОТК: шламов −0,04 мм {sv['minus_004']:.1f} % — переизмельчение/глина, риск потерь меди", "lab-01")
        self.acc = self._empty()

    def live(self, m):
        """Plan for the current (open) shift."""
        a = self.acc
        hours = max(a["t"] / H, 1e-6)
        q = m.sag["tph"]
        lot = q * 12.0
        return self.plan(q, lot, a["grades"], max(a["conc_t"] / hours, 0.1) * 12, max(a["conc_t"] / hours, 0.1))
