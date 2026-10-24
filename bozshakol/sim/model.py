"""
Coupled process model of the Bozshakol open pit and concentrator.

    block model -> drill (MWD) -> charge -> blast (Kuz-Ram) -> dig (loaders)
      -> dispatch (blend / min-queue / fixed) -> haul (rimpull, rolling
      resistance, fuel) -> gyratory crusher -> overland conveyor -> coarse ore
      stockpile -> SAG (power-limited) -> ball mills (Bond) -> flotation
      (kinetic recovery, clay penalty) -> concentrate / tailings / water
    + energy (electric + diesel, time-of-use tariff, peak demand, CO2)
    + reliability (health, hazard, PM / PdM / reactive, workshop bays)
    + safety (blast exclusion and fumes, dust plume, slope radar with the
      inverse-velocity method, proximity / collision avoidance, weather)

Everything is deterministic for a given seed and control state, so the
what-if forecaster can run baseline and scenario on common random numbers.
"""

import collections
import datetime as dt
import math
import random

from . import ml as ML
from . import params as P
from .geometry import FACILITIES, Network
from .realdata import RealData
from .standards import PowerQuality, QCLab
from . import condition as CM

H = 3600.0

CONTROL_DEFAULTS = {
    "preset": "baseline",
    "trucks_parked": 0,
    "loader_down": "none",
    "crusher_down": False,
    "powder_factor": P.DESIGN_PF,
    "grade_target": P.GRADE_TARGET,
    "dispatch_policy": "blend",
    "rain_mm_h": 0.0,
    "road_closed": "none",
    "speed_limit_kmh": 50,
    "peak_shaving": False,
    "harmonic_filter": True,
    "maintenance_strategy": "preventive",
    "sim_speed": 10,
    "blast_now": 0,
    # Monthly planning: equipment allocation between the two pits (S13: Central
    # and East pits feed one plant). Shares and rates are what the planning
    # meeting decides; the twin shows the month and the exposed ore it leaves.
    "east_ore_share": P.PITS["east"]["ore_share"],
    "trucks_east": P.TRUCKS_EAST_785,
    "trucks_777_east": P.TRUCKS_EAST_777,
    "waste_central_tph": P.WASTE_RATE_TPH,
    "waste_east_tph": P.WASTE_RATE_EAST_TPH,
    "plan_optimize": 0,          # counter: each increment asks the twin to pick a monthly plan
}

# Control keys that are commands, not scenario settings.
COMMAND_KEYS = ("sim_speed", "blast_now", "plan_optimize", "preset")

PIT_RU = {k: g["name"] for k, g in P.PITS.items()}

STATE_RU = {
    "to_loader": "порожний рейс", "queue_loader": "очередь у экскаватора", "spotting": "установка под погрузку",
    "loading": "погрузка", "hauling": "груженый рейс", "queue_dump": "очередь на разгрузку", "dumping": "разгрузка",
    "to_fuel": "на АЗС", "refueling": "заправка", "to_workshop": "в ремзону", "in_workshop": "ТО/ремонт",
    "breakdown": "отказ на линии", "towing": "буксировка", "standby": "резерв (нет фронта работ)",
    "to_park": "вывод в резерв", "parked": "резерв (сценарий)", "idle": "ожидание",
    "no_fuel": "нет топлива (ждёт заправщик)", "to_reserve": "в резерв (нет фронта работ)",
}


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def feat(value, unit=None):
    if isinstance(value, float):
        value = round(value, 3)
    d = {"value": value}
    if unit:
        d["unit"] = unit
    return d


# ---------------------------------------------------------------------------
# Geology: a deterministic grade / hardness field around a porphyry core
# ---------------------------------------------------------------------------
MATERIAL = {
    # mean grades of the faces, calibrated so that the blended feed matches S1 FY 2023 (0.42 % Cu, 0.22 g/t Au)
    "ore": dict(cu=0.378, au=0.184, clay=0.05, ucs=118.0, bwi=14.8, rho=2.68),
    "ore_hg": dict(cu=0.567, au=0.240, clay=0.04, ucs=128.0, bwi=15.4, rho=2.72),
    "clay": dict(cu=0.40, au=0.167, clay=0.32, ucs=42.0, bwi=11.5, rho=2.30),
    "waste": dict(cu=0.05, au=0.03, clay=0.08, ucs=105.0, bwi=14.0, rho=2.62),
}


def geo_field(x, y, z, salt):
    """Smooth pseudo-random field in [-1, 1] (sum of incommensurate waves)."""
    return (0.45 * math.sin(x / 173.0 + 1.3 * salt) * math.cos(y / 211.0 - salt)
            + 0.35 * math.sin((x + y) / 97.0 + 2.1 * salt)
            + 0.20 * math.cos(z / 41.0 + x / 301.0 + salt))


# Real geology: the GeoMet drill-hole dataset (Zenodo 7051975, CC BY 4.0),
# interpolated by a gradient-boosting model into a 3D grid over the pit
# (ml/train.py), gives every block its relative Cu and Au grade and, through a
# ridge model trained on comminution tests, its relative hardness. The level
# stays calibrated on Bozshakol (S1): the factors are normalised to 1 over the
# pit volume, so the dataset sets the *spatial pattern*, Bozshakol the level.
_GEO = {}


def _geo_raw(x, y, z):
    g = ML.geomet()
    if g is None:
        return None
    s = g[0].at(x, y, z)
    t = ML.hardness_index(s)
    return dict(cu=s["Cu ppm"] ** GEO_EXP_CU, au=s["Au ppm"] ** GEO_EXP_AU, t=t, assay=s)


def geomet_factors(x, y, z, spur=None):
    """Relative Cu, Au and hardness factors at a pit position, plus raw assays.

    Normalised along the loader's face (spur): the material type and its grade
    level stay calibrated on Bozshakol, the variation as the face advances
    comes from the real drill holes."""
    raw = _geo_raw(x, y, z)
    if raw is None:
        return None
    key = None
    if spur is not None:
        a, b = spur.point_at(0), spur.point_at(spur.length)
        key = tuple(round(v) for v in (*a, *b))
    if key not in _GEO:
        pts = [spur.point_at(spur.length * k / 39) for k in range(40)] if spur is not None else \
            [((P.PIT_A - 200) * math.cos(t / 40 * 6.283), (P.PIT_B - 150) * math.sin(t / 40 * 6.283), -90.0) for t in range(40)]
        rs = [_geo_raw(*p) for p in pts]
        _GEO[key] = (sum(r["cu"] for r in rs) / 40, sum(r["au"] for r in rs) / 40, sum(r["t"] for r in rs) / 40)
    ncu, nau, nt = _GEO[key]
    damp = lambda v, k: 1 + k * (v - 1)  # noqa: E731 - composites vs 60-80 kt blocks
    return dict(cu=clamp(damp(raw["cu"] / ncu, 0.5), 0.7, 1.35), au=clamp(damp(raw["au"] / nau, 0.5), 0.7, 1.4),
                hard=clamp(damp(nt / max(raw["t"], 0.05), 0.8), 0.8, 1.25), t_index=raw["t"], assay=raw["assay"])


GEO_EXP_CU = 0.3      # damped: drill-hole composites vary more than 60-80 kt blocks
GEO_EXP_AU = 0.3


class Block:
    _seq = 0

    def __init__(self, slot, loader, spur, dist, material, rng, pf, bench):
        Block._seq += 1
        self.slot = slot
        self.loader = loader
        self.spur = spur
        self.dist = dist
        self.bench = bench
        self.material = material
        m = MATERIAL[material]
        x, y, z = spur.point_at(dist)
        self.pos = (x, y, z)
        f = geo_field(x, y, z, 0.7)
        g = geo_field(x, y, z, 2.9)
        self.code = f"{bench * 15:03d}-{Block._seq:03d}"
        geo = geomet_factors(x, y, z, spur) if material != "waste" else None
        self.geo = geo
        if geo:
            self.cu = max(0.02, m["cu"] * geo["cu"] * (1 + rng.gauss(0, 0.04)))
            self.au = max(0.01, m["au"] * geo["au"] * (1 + rng.gauss(0, 0.04)))
            self.ucs = max(20.0, m["ucs"] * geo["hard"] ** 0.8 * (1 + 0.05 * g + rng.gauss(0, 0.04)))
            self.bwi = m["bwi"] * geo["hard"] ** 0.4
        else:
            self.cu = max(0.02, m["cu"] * (1 + 0.28 * f + rng.gauss(0, 0.05)))
            self.au = max(0.01, m["au"] * (1 + 0.25 * f + rng.gauss(0, 0.05)))
            self.ucs = max(20.0, m["ucs"] * (1 + 0.18 * g + rng.gauss(0, 0.05)))
            self.bwi = m["bwi"] * (1 + 0.10 * g)
        self.clay = clamp(m["clay"] * (1 + 0.4 * g + rng.gauss(0, 0.08)), 0.0, 0.6)
        self.rho = m["rho"]
        self.tonnes = rng.uniform(60e3, 90e3) if material != "clay" else rng.uniform(40e3, 60e3)
        self.remaining = self.tonnes
        self.state = "planned"
        self.holes_drilled = 0
        self.holes_charged = 0
        self.ucs_mwd = None
        self.x50 = self.x80 = None
        self.blast_t = None
        self.design(pf)

    def design(self, pf):
        """Pattern from the powder factor: tighter pattern for a higher PF."""
        col = (P.BENCH_H + P.SUBDRILL - P.STEMMING) * math.pi / 4 * P.HOLE_D_M ** 2 * P.EXPLOSIVE_DENSITY * 1000
        self.q_hole = 0.9 * col
        area = self.q_hole / (pf * P.BENCH_H)
        self.burden = math.sqrt(area / 1.15)
        self.spacing = 1.15 * self.burden
        self.pf = pf
        vol = self.tonnes / self.rho
        self.holes_total = max(10, int(math.ceil(vol / (area * P.BENCH_H))))

    def recharge(self, pf):
        """Holes already drilled: only the charge per hole can change (column-limited)."""
        col = (P.BENCH_H + P.SUBDRILL - P.STEMMING) * math.pi / 4 * P.HOLE_D_M ** 2 * P.EXPLOSIVE_DENSITY * 1000
        q = min(col, pf * self.burden * self.spacing * P.BENCH_H)
        self.q_hole = q
        self.pf = q / (self.burden * self.spacing * P.BENCH_H)

    def fragment(self, rng):
        """Kuz-Ram (Cunningham): mean size x50 and x80, metres."""
        a = 3.0 + 0.05 * self.ucs
        x50_cm = a * self.pf ** -0.8 * self.q_hole ** (1 / 6) * (115.0 / P.EXPLOSIVE_RWS) ** (19 / 30)
        x50_cm *= rng.uniform(0.93, 1.07)
        n = 1.35
        self.x50 = x50_cm / 100
        self.x80 = self.x50 * (math.log(5) / math.log(2)) ** (1 / n)

    @property
    def explosive_kg(self):
        return self.holes_total * self.q_hole


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
class Asset:
    kind = "asset"

    def __init__(self, uid, rng):
        self.id = uid
        self.rng = random.Random(f"{uid}-{rng.random()}")
        self.health = rng.uniform(28, 95)
        self.engine_h = rng.uniform(2000, 30000)
        self.since_pm = rng.uniform(0, P.PM_INTERVAL_H)
        self.avail = 0.9
        self.maint_due = None
        self.failures = 0

    def hazard(self):
        return P.LAMBDA_BASE * math.exp(P.HAZARD_SLOPE * (1 - self.health / 100))

    def p_fail_24h(self):
        return 1 - math.exp(-self.hazard() * 24 * 0.75)

    def p_fail_24h_est(self):
        """Failure probability estimated from the condition-monitoring index (what the
        reliability engineer can see), not from the hidden true wear."""
        hi = getattr(self, "hi", self.health)
        return 1 - math.exp(-P.LAMBDA_BASE * math.exp(P.HAZARD_SLOPE * (1 - hi / 100)) * 24 * 0.75)

    def cm_text(self):
        hi = getattr(self, "hi", None)
        return f"индекс техсостояния {hi:.0f} % по данным мониторинга" if hi is not None else ""

    def wear(self, dt, stress, _rng, kind):
        rng = self.rng
        dth = dt / H
        self.engine_h += dth
        self.since_pm += dth
        self.health = max(0.0, self.health - P.WEAR_PER_H[kind] * stress * dth)
        return rng.random() < self.hazard() * dth


class Truck(Asset):
    kind = "truck"

    def __init__(self, uid, model, rng):
        super().__init__(uid, rng)
        self.model = model
        spec = P.TRUCK_MODELS[model]
        self.cls = spec["class_"]
        self.cap = spec["payload"]
        self.empty = spec["empty"]
        # 10/10/20 overload up to 5 % on average, but never above the passport GMW.
        self.max_load = min(self.cap * 1.05, spec["gmw"] - self.empty)
        self.p_kw = spec["p_kw"]
        self.vmax = spec["vmax"]
        self.tank = spec["tank"]
        self.fuel = rng.uniform(0.35, 0.95) * self.tank
        self.state = "idle"
        self.timer = 0.0
        self.payload = 0.0
        self.grade = 0.0
        self.mat = None
        self.pit = "central"
        self.lot = None
        self.route = None
        self.d = 0.0
        self.v = 0.0
        self.pos = FACILITIES["workshop"]
        self.heading = 0.0
        self.edge = None
        self.loader = None
        self.dest = None
        self.home = None
        self.group = "central"
        self.prev_state = None
        self.trips = 0
        self.tonnes = 0.0
        self.cycle_start = 0.0
        self.last_cycle = 0.0
        self.queue_start = 0.0
        self.last_queue = 0.0
        self.lph = 0.0
        self.cas = False
        self.cas_until = 0.0
        self.after_dump = None
        self.repair_left = 0.0
        self.parked = False


class Loader(Asset):
    kind = "loader"

    def __init__(self, spec, rng):
        super().__init__(spec["id"], rng)
        self.spec = spec
        self.model = spec["model"]
        self.material = spec["material"]
        self.queue = collections.deque()
        self.truck = None
        self.state = "waiting"
        self.timer = 0.0
        self.block = None
        self.dist = 0.0
        self.pos = (0, 0, 0)
        self.passes = 0
        self.tonnes = 0.0
        self.busy_s = 0.0
        self.total_s = 0.0
        self.lph = 0.0
        self.down = None
        self.hold = None
        self.repair_left = 0.0
        self.assigned = 0.0
        self.dig_rate = 0.0


class Drill(Asset):
    kind = "drill"

    def __init__(self, uid, rng):
        super().__init__(uid, rng)
        self.state = "idle"
        self.block = None
        self.timer = 0.0
        self.hole_time = 0.0
        self.pos = (0, 0, 0)
        self.route = None
        self.d = 0.0
        self.rop = 0.0
        self.pulldown = 0.0
        self.torque = 0.0
        self.se = 0.0
        self.ucs_est = 0.0
        self.metres = 0.0
        self.lph = 0.0
        self.repair_left = 0.0


class Mover:
    """Light vehicle / water truck: follows routes, no payload."""

    def __init__(self, uid, start):
        self.id = uid
        self.pos = start
        self.route = None
        self.d = 0.0
        self.v = 0.0
        self.heading = 0.0
        self.state = "parked"
        self.timer = 0.0
        self.target = None
        self.edge = None


# ---------------------------------------------------------------------------
# The mine
# ---------------------------------------------------------------------------
class Mine:
    def __init__(self, seed=42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.net = Network()
        self.t = 0.0
        self.start = dt.datetime.fromisoformat(P.SIM_START)
        self.control = dict(CONTROL_DEFAULTS)
        self.events = collections.deque(maxlen=40)
        self.kpi = collections.defaultdict(float)
        self.shift_kpi = collections.defaultdict(float)
        self.shift_id = self._shift_id()
        self.wx = dict(temp=6.0, wind=5.0, wind_dir=240.0, rain=0.0, humidity=65.0)
        self.roads = {r: dict(moisture=0.3, traffic=0.0, passes=0, status="open", rr_add=0.0)
                      for r in {e.road for e in self.net.edges.values()}}
        self.restricted = set()
        self.closed = set()
        self.closed_spurs = set()
        self.mute = False
        self.realdata = RealData()
        self.pq = PowerQuality(random.Random(seed * 7 + 1))
        self.qc = QCLab(random.Random(seed * 7 + 2))
        self.realdata.update(0.0)
        self.blast = None
        self.last_blast_t = None
        self.blasts = 0
        self.blast_req_seen = 0
        self.workshop = dict(bays=[], queue=collections.deque(), done=0, mttr_sum=0.0)
        self.dispatch_log = collections.deque(maxlen=400)
        self.plan_t0 = 0.0
        self._build_pit()
        self._build_plant()
        self._build_fleet()
        self._build_safety()
        self.log("info", "Цифровой двойник запущен: начало смены, режим «базовый»", "site")

    # -- helpers -------------------------------------------------------------
    @property
    def now(self):
        return self.start + dt.timedelta(seconds=self.t)

    def hour(self):
        n = self.now
        return n.hour + n.minute / 60 + n.second / 3600

    def _shift_id(self):
        n = self.start + dt.timedelta(seconds=self.t)
        h = n.hour
        day = n.date() if h >= P.SHIFT_STARTS[0] else (n - dt.timedelta(days=1)).date()
        return f"{day.isoformat()} {'день' if P.SHIFT_STARTS[0] <= h < P.SHIFT_STARTS[1] else 'ночь'}"

    def log(self, level, msg, twin=None):
        if self.mute:
            return
        self.events.appendleft({"t": self.now.strftime("%d.%m %H:%M"), "lvl": level, "msg": msg, "twin": twin or ""})

    def tariff(self):
        h = self.hour()
        for zone, (a, b, price) in P.TARIFF.items():
            if (a <= h < b) if a < b else (h >= a or h < b):
                return zone, price
        return "day", P.TARIFF["day"][2]

    # -- construction --------------------------------------------------------
    def _build_pit(self):
        self.loaders = {}
        self.blocks = []
        slot = 0
        for spec in P.LOADERS:
            ld = Loader(spec, self.rng)
            ld.pit = spec.get("pit", "central")
            spur = self.net.edges[f"spur-{spec['id']}"]
            ld.spur = spur
            n_slots = 2 if spec["material"] in ("waste", "clay") else 3
            ld.next_dist = 60.0
            ld.slots = []
            for i in range(n_slots):
                slot += 1
                b = Block(slot, ld.id, spur, ld.next_dist, spec["material"], self.rng, self.control["powder_factor"],
                          spec["bench"])
                ld.next_dist += 115.0
                ld.slots.append(b)
                self.blocks.append(b)
            first, second = ld.slots[0], ld.slots[1]
            first.state = "mining"
            first.remaining = first.tonnes * self.rng.uniform(0.55, 0.85)
            first.holes_drilled = first.holes_charged = first.holes_total
            first.fragment(self.rng)
            # Next block: drilled, waiting for the charging crew (so a powder
            # factor change still reaches it); clay block already charged for
            # the 12:00 blast window.
            second.state = "charged" if spec["material"] == "clay" else "drilled"
            second.holes_drilled = second.holes_total
            second.holes_charged = second.holes_total if second.state == "charged" else 0
            if n_slots == 3:
                third = ld.slots[2]
                third.state = "drilling"
                third.holes_drilled = int(third.holes_total * self.rng.uniform(0.2, 0.6))
            ld.block = first
            ld.dist = first.dist - 25.0
            ld.pos = spur.point_at(ld.dist)
            self.loaders[ld.id] = ld
        self.drills = [Drill(f"dr-{i + 1:02d}", self.rng) for i in range(P.N_DRILLS)]
        # Idle rigs wait on the surface beside the Central pit exit, not in mid-air over the pit.
        for i, d in enumerate(self.drills):
            d.pos = (1160.0 + 40.0 * i, 170.0, 0.0)
        targets = [b for b in self.blocks if b.state == "drilling"] + [b for b in self.blocks if b.state == "planned"]
        for d, b in zip(self.drills, targets):
            d.block = b
            d.state = "drilling"
            d.pos = self._hole_pos(b, b.holes_drilled)
            d.hole_time = self._hole_time(d, b)
        self.charging = None
        plan = P.ORE_PLAN_KT_MONTH * 1000
        self.pits = {k: dict(exposed_t=P.EXPOSED_MONTHS_START[k] * plan * g["ore_share"], ore_t=0.0, waste_t=0.0,
                             warned=False)
                     for k, g in P.PITS.items()}
        self.lg_stock = dict(t=420e3, cu=0.17, clay=0.06, au=0.06, ucs=110.0, bwi=14.5)
        self.dump_t = 0.0
        self.dump_e_t = 0.0

    def _build_fleet(self):
        self.trucks = []
        n = 0
        for model, count in (("CAT 785C", P.N_785), ("CAT 777D", P.N_777)):
            for _ in range(count):
                n += 1
                self.trucks.append(Truck(f"ht-{n:02d}", model, self.rng))
        homes = ["sh-01"] * 5 + ["sh-02"] * 4 + ["sh-03"] * 6 + ["sh-04"] * 5
        for tr, home in zip([t for t in self.trucks if t.cls == "785"], homes):
            tr.home = home
        self._assign_pits()
        # Spread the fleet over the haul cycle so the stand is busy at once.
        for i, tr in enumerate(self.trucks):
            ld = self.loaders[tr.home]
            if i % 3 == 0:
                tr.pos = self.net.nodes["J1"]
                self._send_to_loader(tr, ld, start="J1")
                tr.d = tr.route.length * self.rng.uniform(0.1, 0.9)
            elif i % 3 == 1:
                tr.loader = ld.id
                tr.pos = ld.pos
                tr.state = "queue_loader"
                ld.queue.append(tr)
            else:
                tr.payload = tr.cap * 0.98
                tr.grade = MATERIAL[ld.material]["cu"]
                tr.mat = ld.material
                tr.pit = ld.pit
                tr.lot = self._lot_from(ld.block, tr.payload, tr.grade)
                self._send_to_dest(tr, start=(ld.spur.id, ld.dist))
                tr.d = tr.route.length * self.rng.uniform(0.1, 0.9)
            tr.cycle_start = -self.rng.uniform(300, 1200)
        self.wt = Mover("wt-01", self.net.nodes["J1"])
        self.wt.water = P.WATER_TRUCK_M3
        self.wt.loop = ["J1", "crusher", "J2", "J1", "J3", "dump", "J3", "J1", "b0", "b5", "b0", "J1", "J2", "J4", "e0", "e3", "e0", "J4", "dump_e", "J4", "J2", "J1"]
        self.wt.li = 0
        self.lvs = {"lv-01": Mover("lv-01", self.net.nodes["J1"]), "lv-02": Mover("lv-02", self.net.nodes["J3"])}
        self.lvs["lv-02"].faces = list(self.loaders)
        self.lvs["lv-02"].fi = 0
        self.fuel_tank = 320.0  # m3 diesel at the fuel station
        self.fuel_pumps = []

    def _build_plant(self):
        self.crusher = dict(state="running", pocket=350.0, lot=dict(cu=0.42, clay=0.05, au=0.21, ucs=118.0,
                                                                      bwi=14.8, x80=0.7),
                            tph=0.0, total=0.0, wear=80.0, down_left=0.0, dumps=collections.deque(), slots=2,
                            reclaim=0.0)
        self.conveyor = collections.deque()  # (arrival time, tonnes, lot)
        self.cos = dict(t=18000.0, cu=0.42, clay=0.055, au=0.21, bwi=14.7, f80=135.0)
        self.sag = dict(tph=3150.0, power=24.5, e=7.9, liner=63.0, t80=1900.0, state="running", speed=74.0)
        self.bm = [dict(id="bm-01", power=13.0, state="running"), dict(id="bm-02", power=13.0, state="running")]
        self.flot = dict(rec=0.765, k=0.16, tau=20.0, conc_grade=22.0, cu_tph=9.8, conc_tph=44.0, tails_cu=0.10,
                         xanthate=28.0, air=1.0)
        self.p80 = 150.0
        self.conv_tph = 0.0
        self.clay_plant = dict(hopper=150.0, tph=0.0, rec=0.62, lot=dict(cu=0.40, clay=0.32, au=0.167), cu_tph=0.0)
        self.tsf = dict(volume=41.5e6, freeboard=3.2, reclaim=0.0)
        self.thick = dict(c_ud=64.0, t_ud=57.0, ntu=35.0, floc=18.0)
        self.water = dict(fresh=0.0, reclaim=0.0)
        self.energy = dict(mw=0.0, peak_mw=0.0, cost=0.0, mwh=0.0, diesel_l=0.0, co2=0.0, breakdown={})
        self.feed_hist = collections.deque()

    def _build_safety(self):
        self.radar = [dict(id="W1", theta=1.25, base=0.6, p=0.0, v=0.6, disp=0.0, hist=collections.deque(maxlen=16),
                           level="green", ttf=-1.0),
                      dict(id="W2", theta=1.62, base=1.1, p=0.0, v=1.1, disp=0.0, hist=collections.deque(maxlen=16),
                           level="green", ttf=-1.0),
                      dict(id="W3", theta=2.05, base=0.8, p=0.0, v=0.8, disp=0.0, hist=collections.deque(maxlen=16),
                           level="green", ttf=-1.0)]
        for s in self.radar:
            k = 6
            a, b = P.PIT_A - P.BENCH_STEP * k, P.PIT_B - P.BENCH_STEP * k
            s["pos"] = (a * math.cos(s["theta"]), b * math.sin(s["theta"]), -P.BENCH_H * k)
        self.radar_sample_t = 0.0
        self.dust = {k: 25.0 for k in ("dm-01", "dm-02", "dm-03")}
        self.plume = None
        self.gas = dict(co=2.0, no2=0.1, pos=FACILITIES["dm-01"], status="open")
        self.cas_pairs = {}
        self.people = {
            "p-01": dict(role="Бригада взрывников", pos=(0, 0, 0), lv="lv-01", ppe="ok"),
            "p-02": dict(role="Электрик ОФ", pos=FACILITIES["sag"], lv=None, ppe="ok"),
            "p-03": dict(role="Геолог ГРК (опробование)", pos=(0, 0, 0), lv="lv-02", ppe="ok"),
            "p-04": dict(role="Маркшейдер", pos=FACILITIES["radar"], lv=None, ppe="ok"),
        }

    # -- control ---------------------------------------------------------------
    def apply_control(self, new, quiet=False):
        changed = []
        for k, default in CONTROL_DEFAULTS.items():
            if k not in new:
                continue
            v = new[k]
            try:
                if isinstance(default, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
                elif isinstance(default, int):
                    v = int(float(v))
                elif isinstance(default, float):
                    v = float(v)
                else:
                    v = str(v)
            except (TypeError, ValueError):
                continue
            if self.control.get(k) != v:
                changed.append((k, self.control.get(k), v))
                self.control[k] = v
        for k, old, v in changed:
            if k == "powder_factor":
                v = clamp(v, 0.35, 1.2)
                self.control[k] = v
                for b in self.blocks:
                    if b.state in ("planned",) or (b.state == "drilling" and b.holes_drilled == 0):
                        b.design(v)
                    elif b.state in ("drilling", "drilled") or (b.state == "charging" and b.holes_charged < 1):
                        b.recharge(v)
            if k == "blast_now" and v > self.blast_req_seen:
                self.blast_req_seen = v
                if not quiet:
                    self._start_blast(manual=True)
                continue
            if k in ("sim_speed", "plan_optimize"):
                continue
            if not quiet:
                self.log("warn" if k != "preset" else "info", f"Сценарий: {k} = {v} (было {old})", "control")
        if changed:
            self._apply_parking()
            if any(c[0] in ("trucks_east", "trucks_777_east") for c in changed):
                self._assign_pits()
        return [c[0] for c in changed]

    def _assign_pits(self):
        """Truck groups per pit: the last `trucks_east` CAT 785C work in the
        East pit, the rest in the Central one; CAT 777D keep their loader's pit."""
        n_e = int(clamp(self.control["trucks_east"], 0, P.N_785))
        t785 = [t for t in self.trucks if t.cls == "785"]
        central_homes = (["sh-01"] * 5 + ["sh-02"] * 4 + ["sh-03"] * 6) * 2
        for i, tr in enumerate(t785):
            east = i >= len(t785) - n_e
            tr.group = "east" if east else "central"
            if east:
                tr.home = "sh-04"
            elif tr.home not in self.loaders or self.loaders[tr.home].pit != "central":
                tr.home = central_homes[i % len(central_homes)]
        # CAT 777D: the last `trucks_777_east` work the East waste with EX-01, the
        # rest the clay face with the 993K (S2 lists 777D in the fleet; split (A)).
        t777 = [t for t in self.trucks if t.cls == "777"]
        n7 = int(clamp(self.control["trucks_777_east"], 0, max(0, len(t777) - 1)))
        for i, tr in enumerate(t777):
            tr.home = "ex-01" if i >= len(t777) - n7 else "ld-01"
            tr.group = self.loaders[tr.home].pit

    def _apply_parking(self):
        want = int(clamp(self.control["trucks_parked"], 0, len(self.trucks) - 2))
        parked = [t for t in self.trucks if t.parked]
        if len(parked) < want:
            # Take the 785Cs with the lowest health out of service.
            # Spread the shortage over both pits in proportion to their fleets.
            t785 = [t for t in self.trucks if t.cls == "785"]
            rank = {}
            for g in ("central", "east"):
                grp = sorted([t for t in t785 if t.group == g], key=lambda t: t.id, reverse=True)
                for i, t in enumerate(grp):
                    rank[t.id] = (i + 0.5) / len(grp)
            cands = sorted([t for t in t785 if not t.parked], key=lambda t: (rank[t.id], t.id))
            for t in cands[: want - len(parked)]:
                t.parked = True
                self.log("warn", f"{t.id.upper()} выводится в резерв (сценарий)", t.id)
        elif len(parked) > want:
            for t in parked[: len(parked) - want]:
                t.parked = False
                if t.state == "parked":
                    t.state = "idle"
                self.log("info", f"{t.id.upper()} возвращён на линию", t.id)

    # -- the step ----------------------------------------------------------------
    def step(self, dt_s):
        self.t += dt_s
        sid = self._shift_id()
        if sid != self.shift_id:
            self.qc.close_shift(self, self.shift_id)
            self.log("info", f"Пересменка: итоги смены {self.shift_id} — руда в ЗИФ "
                             f"{self.shift_kpi['mill_t'] / 1000:.1f} кт, медь {self.shift_kpi['cu_t']:.0f} т", "site")
            self.shift_id = sid
            self.shift_kpi = collections.defaultdict(float)
        self.realdata.update(self.t, None if self.mute else self.log)
        self._weather(dt_s)
        self._roads(dt_s)
        self._safety_slope(dt_s)
        self._blasting(dt_s)
        self._drills(dt_s)
        for ld in self.loaders.values():
            self._loader(ld, dt_s)
        for tr in self.trucks:
            self._truck(tr, dt_s)
        self._water_truck(dt_s)
        self._light_vehicles(dt_s)
        self._proximity()
        self._plant(dt_s)
        self._workshop(dt_s)
        CM.update_all(self, dt_s)
        self._dust_gas(dt_s)
        self._energy(dt_s)
        self.pq.step(self, dt_s)
        self.qc.step(self, dt_s)
        self.kpi["sim_s"] += dt_s

    # -- weather and roads ---------------------------------------------------------
    def _weather(self, dt_s):
        rng = self.rng
        h = self.hour()
        w = self.wx
        w["rain"] = max(0.0, float(self.control["rain_mm_h"]))
        w["temp"] = 5.5 + 6.0 * math.sin(2 * math.pi * (h - 9) / 24) - (1.5 if w["rain"] > 0 else 0)
        w["wind"] = clamp(w["wind"] + rng.gauss(0, 0.25) * math.sqrt(dt_s / 10) + 0.002 * (6 - w["wind"]) * dt_s / 10,
                          0.5, 16.0)
        if w["rain"] > 2:
            w["wind"] = max(w["wind"], 7.0)
        w["wind_dir"] = (w["wind_dir"] + rng.gauss(0, 1.0) * math.sqrt(dt_s / 10)) % 360
        target_h = 95.0 if w["rain"] > 0 else 60.0 - 15 * math.sin(2 * math.pi * (h - 9) / 24)
        w["humidity"] += (target_h - w["humidity"]) * min(1.0, dt_s / 1800)

    def _roads(self, dt_s):
        w = self.wx
        evap = 0.30 * (1 + 0.06 * max(w["temp"], -5)) * (1 + 0.08 * w["wind"]) * (0.4 if w["humidity"] > 85 else 1)
        closed = set()
        rc = self.control["road_closed"]
        if rc and rc != "none":
            closed.add(rc)
        for rid, r in self.roads.items():
            if w["rain"] > 0.2:
                r["moisture"] = min(1.0, r["moisture"] + 0.6 * w["rain"] * dt_s / H)
            else:
                r["moisture"] = max(0.0, r["moisture"] - r["moisture"] * evap * dt_s / H)
            r["rr_add"] = 0.010 * r["moisture"] + (0.006 * min(w["rain"], 10) if w["rain"] > 1 else 0.0)
            r["traffic"] *= math.exp(-dt_s / 1800)
            r["status"] = "closed" if rid in closed else ("restricted" if rid in self.restricted else "open")
        self.closed = closed | self.closed_spurs

    # -- slope radar ---------------------------------------------------------------
    def _safety_slope(self, dt_s):
        dth = dt_s / H
        rain = self.wx["rain"]
        restricted, closed_spurs = set(), set()
        for s in self.radar:
            s["p"] = max(0.0, s["p"] + (0.075 * rain - 0.15 * s["p"]) * dth)
            v = s["base"] * (1 + 3.0 * s["p"]) ** 1.6
            s["v"] = max(0.05, v * (1 + self.rng.gauss(0, 0.03)))
            s["disp"] += s["v"] * dth / 24
            old = s["level"]
            s["level"] = "red" if s["v"] > 15 else "amber" if s["v"] > 5 else "green"
            if s["level"] != old:
                lvl = "alarm" if s["level"] == "red" else "warn" if s["level"] == "amber" else "info"
                self.log(lvl, f"Радар SR-01, сектор {s['id']}: скорость смещения {s['v']:.1f} мм/сут — "
                              f"{ {'red': 'КРАСНЫЙ уровень', 'amber': 'жёлтый уровень', 'green': 'норма'}[s['level']] }",
                         "sr-01")
            if s["level"] in ("amber", "red"):
                restricted.add("road-ramp")
            if s["level"] == "red":
                for ld in self.loaders.values():
                    if math.dist(ld.pos[:2], s["pos"][:2]) < 380:
                        closed_spurs.add(ld.spur.id)
        if self.t - self.radar_sample_t >= 900:
            self.radar_sample_t = self.t
            for s in self.radar:
                s["hist"].append((self.t / H, s["v"]))
                s["ttf"] = self._inverse_velocity(s["hist"])
        self.restricted = restricted
        newly = closed_spurs - self.closed_spurs
        for sp in newly:
            self.log("alarm", f"Запрет работ под бортом: {sp.replace('spur-', '').upper()} остановлен", "sr-01")
        for sp in self.closed_spurs - closed_spurs:
            self.log("info", f"Работы под бортом возобновлены: {sp.replace('spur-', '').upper()}", "sr-01")
        self.closed_spurs = closed_spurs

    @staticmethod
    def _inverse_velocity(hist):
        """Fukuzono inverse-velocity method: time until 1/v reaches zero."""
        pts = list(hist)[-6:]
        if len(pts) < 4 or pts[-1][1] <= pts[0][1] * 1.15:
            return -1.0
        xs = [p[0] for p in pts]
        ys = [1 / p[1] for p in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx == 0:
            return -1.0
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        if slope >= 0:
            return -1.0
        t0 = mx - my / slope
        return max(0.0, t0 - xs[-1])

    # -- drill and blast ---------------------------------------------------------
    def _hole_pos(self, b, i):
        cols = max(4, int(round(math.sqrt(b.holes_total * 1.6))))
        r, c = divmod(i, cols)
        ex, ey = b.spur.point_at(min(b.spur.length, b.dist + 1))[:2]
        bx, by, bz = b.pos
        tx, ty = ex - bx, ey - by
        n = math.hypot(tx, ty) or 1
        tx, ty = tx / n, ty / n
        nx, ny = -ty, tx
        along = (c - cols / 2) * b.spacing * 0.9
        across = (r - 2) * b.burden * 0.9
        return bx + tx * along + nx * across, by + ty * along + ny * across, bz

    def _hole_time(self, d, b):
        ucs = b.ucs * (1 + d.rng.gauss(0, 0.06))
        d.rop = P.ROP_REF * (110.0 / ucs) ** 0.9 * (0.85 + 0.15 * d.health / 100)
        d.pulldown = 300 + 1.4 * ucs
        d.torque = 4.0 + 0.055 * ucs
        area = math.pi / 4 * P.HOLE_D_M ** 2
        rop_ms = d.rop / H
        se = (d.pulldown * 1e3 / area + 2 * math.pi * (90 / 60) * d.torque * 1e3 / (area * rop_ms)) / 1e6
        d.se = se
        d.ucs_est = se * 0.205
        depth = P.BENCH_H + P.SUBDRILL
        return depth / d.rop * H + P.HOLE_MOVE_S

    def _drill_target(self, drill):
        """Next block to drill: the area with the thinnest blasted inventory."""
        busy = {d.block for d in self.drills if d is not drill and d.block is not None}
        cands = [b for b in self.blocks if b.state in ("planned", "drilling") and b not in busy]
        if not cands:
            return None

        def inventory(b):
            ld = self.loaders[b.loader]
            ready = sum(x.remaining for x in ld.slots if x.state in ("mining", "blasted", "charged", "drilled"))
            rate = {"ore": 1600, "ore_hg": 1000, "waste": 1900, "clay": 600}[ld.material]
            return ready / rate + (0 if b.state == "drilling" else 0.5)

        return min(cands, key=inventory)

    def _drills(self, dt_s):
        for d in self.drills:
            d.lph = 0.0
            if d.state in ("breakdown", "maintenance"):
                d.repair_left -= dt_s
                d.avail += (0 - d.avail) * dt_s / (24 * H)
                if d.repair_left <= 0:
                    d.health = 95.0 if d.state == "breakdown" else min(95.0, d.health + 40)
                    d.since_pm = 0.0
                    d.state = "idle"
                    self.log("info", f"{d.id.upper()} вернулся в работу после ремонта", d.id)
                continue
            d.avail += (1 - d.avail) * dt_s / (24 * H)
            if self._in_blast_zone(d.pos) and self.blast and self.blast["phase"] == "clearing":
                d.state = "blast_standby"
                continue
            if d.state == "blast_standby":
                d.state = "drilling" if d.block else "idle"
            if self._maint_due(d):
                d.state = "maintenance"
                d.repair_left = (P.PDM_DURATION_H if self.control["maintenance_strategy"] == "predictive"
                                 else P.PM_DURATION_H) * H
                self.log("info", f"{d.id.upper()}: плановое ТО на месте", d.id)
                continue
            if d.state == "idle" or d.block is None or d.block.state not in ("planned", "drilling"):
                b = self._drill_target(d)
                if b is None:
                    d.state = "idle"
                    d.block = None
                    d.lph = 15.0
                    continue
                d.block = b
                start = d.pos
                d.route = self.net.route(self._nearest_loc(start), (b.spur.id, b.dist), closed=self.closed)
                d.d = 0.0
                d.state = "moving" if d.route else "drilling"
                if b.state == "planned":
                    b.state = "drilling"
                d.hole_time = self._hole_time(d, b)
                d.timer = 0.0
            if d.state == "moving":
                d.d += 2.8 / 3.6 * dt_s
                x, y, z, *_ = d.route.at(d.d)
                d.pos = (x, y, z)
                d.lph = 55.0
                if d.d >= d.route.length:
                    d.state = "drilling"
                continue
            # drilling
            b = d.block
            d.timer += dt_s
            d.lph = 150.0
            if d.wear(dt_s, 1.0 + 0.004 * (b.ucs - 110), self.rng, "drill"):
                d.state = "breakdown"
                d.failures += 1
                d.repair_left = d.rng.uniform(*P.REPAIR_H) * H
                self.log("alarm", f"Отказ бурового станка {d.id.upper()} на блоке {b.code}: "
                                  f"{CM.SUBSYS_RU[CM.dominant(d)] if hasattr(d, 'cm') else 'узел'}; {d.cm_text()}", d.id)
                continue
            while d.timer >= d.hole_time and b.holes_drilled < b.holes_total:
                d.timer -= d.hole_time
                b.holes_drilled += 1
                d.metres += P.BENCH_H + P.SUBDRILL
                ue = d.ucs_est
                b.ucs_mwd = ue if b.ucs_mwd is None else 0.9 * b.ucs_mwd + 0.1 * ue
                d.pos = self._hole_pos(b, b.holes_drilled)
                d.hole_time = self._hole_time(d, b)
            if b.holes_drilled >= b.holes_total:
                b.state = "drilled"
                self.log("info", f"Блок {b.code} обурен ({b.holes_total} скв., сетка {b.burden:.1f}×{b.spacing:.1f} м)",
                         f"blk-{b.slot:02d}")
                d.block = None
                d.state = "idle"

    def _maint_due(self, a):
        s = self.control["maintenance_strategy"]
        if isinstance(a, Truck):
            # Planned work is levelled: at most two trucks in planned service at once.
            busy = sum(1 for t in self.trucks if t.state == "to_workshop") + \
                sum(1 for j in list(self.workshop["bays"]) + list(self.workshop["queue"]) if j["kind"] != "repair")
            if busy >= 2:
                return False
        if s == "preventive":
            return a.since_pm >= P.PM_INTERVAL_H
        if s == "predictive":
            # decided on the condition-monitoring estimate, not on the hidden true wear
            return getattr(a, "hi", a.health) < P.PDM_THRESHOLD
        return False

    def _nearest_loc(self, pos):
        best, bd = None, 1e18
        for e in self.net.edges.values():
            for i, p in enumerate(e.pts):
                dd = math.dist(p, pos)
                if dd < bd:
                    bd = dd
                    best = (e, e.cum[i])
        e, dist = best
        if e.id.startswith("spur-"):
            return (e.id, dist)
        return e.a if dist < e.length / 2 else e.b

    def _in_blast_zone(self, pos):
        return self.blast is not None and math.dist(pos, self.blast["pos"]) < P.BLAST_EXCLUSION_M

    def _blasting(self, dt_s):
        # Charging: one MMU crew charges drilled blocks in order.
        if self.charging is None:
            ready = [b for b in self.blocks if b.state == "drilled"]
            if ready:
                self.charging = ready[0]
                self.charging.state = "charging"
        if self.charging is not None and not (self.blast and self.blast["phase"] == "clearing"):
            b = self.charging
            b.holes_charged = min(b.holes_total, b.holes_charged + P.CHARGE_HOLES_PER_H * dt_s / H)
            if b.holes_charged >= b.holes_total:
                b.holes_charged = b.holes_total
                b.state = "charged"
                self.log("info", f"Блок {b.code} заряжен: {b.explosive_kg / 1000:.1f} т ВВ, "
                                 f"q = {b.pf:.2f} кг/м³", f"blk-{b.slot:02d}")
                self.charging = None
        # Blast windows.
        h = self.hour()
        prev_h = (self.now - dt.timedelta(seconds=dt_s))
        prev_h = prev_h.hour + prev_h.minute / 60 + prev_h.second / 3600
        for wnd in P.BLAST_WINDOWS:
            start = wnd - P.BLAST_CLEAR_S / H
            if prev_h < start <= h and self.blast is None:
                self._start_blast()
        if self.blast is None:
            return
        bl = self.blast
        bl["timer"] += dt_s
        if bl["phase"] == "clearing" and bl["timer"] >= P.BLAST_CLEAR_S:
            bl["phase"] = "fumes"
            bl["timer"] = 0.0
            for b in bl["blocks"]:
                b.state = "blasted"
                b.blast_t = self.t
                b.fragment(random.Random(b.code))
                self.kpi["explosive_kg"] += b.explosive_kg
                self.shift_kpi["explosive_kg"] += b.explosive_kg
            self.blasts += 1
            self.last_blast_t = self.t
            x50 = sum(b.x50 for b in bl["blocks"]) / len(bl["blocks"])
            self.log("alarm", f"ВЗРЫВ: блок(и) {', '.join(b.code for b in bl['blocks'])}; x50 = {x50 * 100:.0f} см, "
                              f"ожидание проветривания", "drill-blast")
            mass = sum(b.explosive_kg for b in bl["blocks"])
            self.plume = dict(x=bl["pos"][0], y=bl["pos"][1], z=bl["pos"][2] + 40, age=0.0, mass=mass)
            self.gas = dict(co=380.0 * min(2.0, mass / 60000), no2=15.0, pos=bl["pos"], status="closed")
        elif bl["phase"] == "fumes":
            if self.gas["co"] < P.REENTRY_CO_PPM and bl["timer"] > 900:
                self.log("info", f"Допуск в зону взрыва: CO = {self.gas['co']:.0f} ppm < {P.REENTRY_CO_PPM:.0f}",
                         "gm-01")
                self.gas["status"] = "open"
                self.blast = None

    def _start_blast(self, manual=False):
        charged = [b for b in self.blocks if b.state == "charged"]
        if not charged:
            if manual:
                self.log("warn", "Взрыв отменён: нет заряженных блоков", "drill-blast")
            return
        if self.blast is not None:
            return
        pos = charged[0].pos
        self.blast = dict(phase="clearing", timer=0.0 if not manual else P.BLAST_CLEAR_S * 0.6, blocks=charged,
                          pos=pos)
        self.log("warn", f"{'Внеплановый взрыв' if manual else 'Взрывное окно'}: эвакуация из зоны "
                         f"{P.BLAST_EXCLUSION_M:.0f} м вокруг блока {charged[0].code}", "drill-blast")

    # -- loaders -----------------------------------------------------------------
    def _loader_available(self, ld):
        return ld.state not in ("breakdown", "maintenance", "down", "blast_standby", "slope_hold", "starved")

    def _loader(self, ld, dt_s):
        ld.total_s += dt_s
        ld.lph = 0.0
        diesel_full = 245.0 if ld.model.startswith("Hitachi") else 125.0
        # Externally imposed stops.
        if self.control["loader_down"] == ld.id:
            if ld.state != "down":
                ld.state = "down"
                self.log("alarm", f"{ld.id.upper()} остановлен (сценарий: отказ экскаватора)", ld.id)
                self._release_queue(ld)
            ld.avail += (0 - ld.avail) * dt_s / (24 * H)
            return
        if ld.state == "down":
            ld.state = "waiting"
            self.log("info", f"{ld.id.upper()} возвращён в работу", ld.id)
        if ld.state in ("breakdown", "maintenance"):
            ld.repair_left -= dt_s
            ld.avail += (0 - ld.avail) * dt_s / (24 * H)
            if ld.repair_left <= 0:
                ld.health = 95.0 if ld.state == "breakdown" else min(95.0, ld.health + 40)
                ld.since_pm = 0.0
                ld.state = "waiting"
                self.log("info", f"{ld.id.upper()} вернулся в работу", ld.id)
            return
        ld.avail += (1 - ld.avail) * dt_s / (24 * H)
        if ld.spur.id in self.closed_spurs:
            if ld.state != "slope_hold":
                ld.state = "slope_hold"
                self._release_queue(ld)
            return
        if ld.state == "slope_hold":
            ld.state = "waiting"
        if self._in_blast_zone(ld.pos) and self.blast["phase"] in ("clearing", "fumes") and ld.truck is None:
            if ld.state != "blast_standby":
                ld.state = "blast_standby"
                self._release_queue(ld)
            ld.lph = 40.0
            return
        if ld.state == "blast_standby":
            ld.state = "waiting"
        if ld.state == "relocating":
            ld.timer -= dt_s
            ld.lph = 90.0
            target = ld.block.dist - 25.0
            ld.dist += clamp(target - ld.dist, -1.2 * dt_s, 1.2 * dt_s)
            ld.pos = ld.spur.point_at(ld.dist)
            if ld.timer <= 0:
                ld.dist = target
                ld.pos = ld.spur.point_at(ld.dist)
                ld.state = "waiting"
                self.log("info", f"{ld.id.upper()} перешёл на блок {ld.block.code}", ld.id)
            return
        if ld.block is None or ld.block.state != "mining":
            nxt = [b for b in ld.slots if b.state == "blasted"]
            if nxt:
                ld.block = min(nxt, key=lambda b: b.dist)
                ld.block.state = "mining"
                ld.state = "relocating"
                ld.timer = 40 * 60
                return
            if ld.state != "starved":
                self.log("alarm", f"{ld.id.upper()}: нет взорванной горной массы — простой экскаватора "
                                  f"(отставание БВР)", ld.id)
            ld.state = "starved"
            self._release_queue(ld)
            return
        if ld.state == "starved":
            ld.state = "waiting"
        if self._maint_due(ld) and ld.truck is None:
            ld.state = "maintenance"
            ld.repair_left = (P.PDM_DURATION_H if self.control["maintenance_strategy"] == "predictive"
                              else P.PM_DURATION_H) * H
            self.log("info", f"{ld.id.upper()}: плановое ТО", ld.id)
            self._release_queue(ld)
            return
        # Serve trucks.
        if ld.truck is None:
            while ld.queue and (ld.queue[0].state != "queue_loader" or ld.queue[0].loader != ld.id):
                ld.queue.popleft()
            if ld.queue:
                tr = ld.queue.popleft()
                # the truck moves up from the queue to the loading spot beside the bucket
                sx, sy, sz = ld.spur.point_at(max(0.0, ld.dist - 12.0))
                tr.pos = (sx, sy, sz)
                ld.truck = tr
                tr.state = "spotting"
                tr.timer = 0.0
                tr.last_queue = (self.t - tr.queue_start) / 60
                self.kpi["queue_min_sum"] += tr.last_queue
                self.kpi["queue_n"] += 1
                ld.timer = 0.0
                ld.state = "spotting"
            else:
                ld.state = "waiting"
                ld.lph = 60.0 if ld.model.startswith("Hitachi") else 30.0
                return
        tr = ld.truck
        ld.busy_s += dt_s
        if ld.state == "spotting":
            ld.timer += dt_s
            ld.lph = 70.0
            if ld.timer >= P.SPOT_S:
                ld.state = "loading"
                tr.state = "loading"
                ld.timer = 0.0
            return
        # loading
        b = ld.block
        x80 = b.x80 or 0.7
        dig = (0.75 + 0.30 * x80 / 0.7) * (0.92 + 0.08 * b.ucs / 110) * (1 + 0.25 * (1 - ld.health / 100))
        cycle = ld.spec["cycle"] * dig
        ld.lph = diesel_full * (0.75 + 0.15 * dig)
        ld.timer += dt_s
        ld.dig_rate = 0.0
        if ld.wear(dt_s, dig, self.rng, "loader"):
            ld.state = "breakdown"
            ld.failures += 1
            ld.repair_left = (ld.rng.uniform(*P.REPAIR_H) + P.RESPONSE_H) * H
            self.log("alarm", f"Отказ {ld.id.upper()} ({ld.model}): "
                              f"{CM.SUBSYS_RU[CM.dominant(ld)] if hasattr(ld, 'cm') else 'гидросистема'}, ремонт на месте; {ld.cm_text()}", ld.id)
            self._finish_loading(ld, tr)
            self._release_queue(ld)
            return
        bucket_t = ld.spec["bucket"] * ld.spec["fill"] * b.rho / P.SWELL * (1.06 - 0.10 * x80 / 0.7)
        while ld.timer >= cycle:
            ld.timer -= cycle
            pass_t = min(bucket_t * ld.rng.uniform(0.92, 1.05), ld.spec.get("rated_t", 1e9),
                         max(0.0, tr.max_load - tr.payload), b.remaining)
            if pass_t <= 0.5:
                break
            g = b.cu * math.exp(ld.rng.gauss(-0.016, 0.18))
            tr.grade = (tr.grade * tr.payload + g * pass_t) / (tr.payload + pass_t)
            tr.lot = self._mix(tr.lot, tr.payload, self._lot_from(b, pass_t, g), pass_t)
            tr.payload += pass_t
            tr.mat = ld.material
            tr.pit = ld.pit
            b.remaining -= pass_t
            ld.passes += 1
            ld.tonnes += pass_t
            self.kpi[f"dug_{ld.id}"] += pass_t
            if tr.payload + bucket_t * 0.6 > tr.max_load or b.remaining <= 0.5:
                break
        if tr.payload + bucket_t * 0.6 > tr.max_load or b.remaining <= 0.5:
            self._finish_loading(ld, tr)
            if b.remaining <= 0.5:
                self._deplete(ld, b)

    # -- exposed reserves (monthly planning) ------------------------------------------
    def _pit_account(self, pit, t, is_ore):
        """Ore taken from a pit uses up its exposed (uncovered) ore; waste
        stripped at the pit's strip ratio uncovers new ore."""
        p = self.pits[pit]
        if is_ore:
            p["ore_t"] += t
            p["exposed_t"] -= t
            self.kpi[f"ore_t_{pit}"] += t
            self.shift_kpi[f"ore_t_{pit}"] += t
        else:
            p["waste_t"] += t
            p["exposed_t"] += t / P.PITS[pit]["strip_t_t"]
            self.kpi[f"waste_t_{pit}"] += t
            self.shift_kpi[f"waste_t_{pit}"] += t
        if not self.mute:
            months = self.exposed_months(pit)
            if months < 1.0 and not p["warned"]:
                p["warned"] = True
                self.log("warn", f"{PIT_RU[pit]} карьер: вскрытой руды меньше чем на месяц ({months:.1f} мес)",
                         f"pit-{pit}")
            elif months > 1.3:
                p["warned"] = False

    def pit_plan_month_t(self, pit):
        """Monthly ore plan of a pit under the current allocation, t."""
        se = clamp(float(self.control["east_ore_share"]), 0.0, 1.0)
        return P.ORE_PLAN_KT_MONTH * 1000 * (se if pit == "east" else 1 - se)

    def exposed_months(self, pit, exposed_t=None):
        e = self.pits[pit]["exposed_t"] if exposed_t is None else exposed_t
        # Months of the pit's own share of the plan; a pit set to zero ore is
        # measured against its design share.
        base = max(self.pit_plan_month_t(pit), 0.05 * P.ORE_PLAN_KT_MONTH * 1000)
        return e / base

    def outlook(self, k=None, sim_s=None):
        """Month and six-month view from the rates of the run behind `k` (a KPI
        dict): ore and copper per month, and month by month for
        PLAN_HORIZON_MONTHS the exposed ore of each pit. A pit whose exposed ore
        runs out cannot deliver its share of the plan that month: the ore it
        misses, and the copper in it, are lost (the other pit's faces and
        fleet are not re-planned automatically — that is the planner's job)."""
        k = self.kpi if k is None else k
        sim_s = k.get("sim_s", 0.0) if sim_s is None else sim_s
        if sim_s < 3600:
            return {}
        per_month = 30.4 * 86400 / sim_s
        month_ore = (k["mill_t"] + k["clay_proc_t"]) * per_month
        month_cu = k["cu_t"] * per_month
        out = {"month_ore_kt": month_ore / 1000, "month_cu_t": month_cu}
        ore_all = sum(k[f"ore_t_{p}"] for p in P.PITS) or 1.0
        out["ore_east_pct"] = k["ore_t_east"] / ore_all * 100
        rates = {}
        for p, g in P.PITS.items():
            ore_m = k[f"ore_t_{p}"] * per_month
            waste_m = k[f"waste_t_{p}"] * per_month
            rates[p] = (ore_m, waste_m / g["strip_t_t"])
            out[f"exposed_now_{p}_mo"] = self.exposed_months(p)
            out[f"strip_{p}"] = waste_m / ore_m if ore_m > 0 else 0.0
        # Month-by-month balance of exposed ore.
        exp = {p: self.pits[p]["exposed_t"] for p in P.PITS}
        traj = {p: [round(max(0.0, self.exposed_months(p, exp[p])), 2)] for p in P.PITS}
        cu6 = short = 0.0
        for _ in range(P.PLAN_HORIZON_MONTHS):
            taken = 0.0
            for p in P.PITS:
                ore_m, uncover = rates[p]
                exp[p] += uncover
                got = min(ore_m, max(0.0, exp[p]))
                exp[p] -= got
                taken += got
                short += ore_m - got
                traj[p].append(round(max(0.0, self.exposed_months(p, exp[p])), 2))
            cu6 += month_cu * (taken / (ore_all * per_month) if ore_all > 1 else 1.0)
        for p in P.PITS:
            out[f"exposed6_{p}_mo"] = traj[p][-1]
            out[f"traj_{p}"] = traj[p]
        out["cu_6m_kt"] = cu6 / 1000
        out["ore_short_6m_kt"] = short / 1000
        return out

    def _lot_from(self, b, t, g):
        return dict(cu=g, clay=b.clay, au=b.au * g / max(b.cu, 0.01), ucs=b.ucs, bwi=b.bwi, x80=b.x80 or 0.7)

    @staticmethod
    def _mix(a, wa, b, wb):
        if not a or wa <= 0:
            return dict(b)
        s = wa + wb
        return {k: (a.get(k, 0) * wa + b[k] * wb) / s for k in b}

    def _finish_loading(self, ld, tr):
        ld.truck = None
        ld.state = "waiting"
        if tr.payload > 1:
            self._send_to_dest(tr, start=(ld.spur.id, ld.dist))
        else:
            tr.state = "idle"

    def _deplete(self, ld, b):
        b.state = "depleted"
        self.log("info", f"Блок {b.code} отработан ({b.tonnes / 1000:.0f} кт)", f"blk-{b.slot:02d}")
        dist = ld.next_dist
        if dist > ld.spur.length - 40:
            dist = 60.0
        ld.next_dist = dist + 115.0
        nb = Block(b.slot, ld.id, ld.spur, dist, ld.material, ld.rng, self.control["powder_factor"],
                   ld.spec["bench"])
        idx = ld.slots.index(b)
        ld.slots[idx] = nb
        self.blocks[self.blocks.index(b)] = nb
        ld.block = None

    def _release_queue(self, ld):
        while ld.queue:
            tr = ld.queue.popleft()
            if tr.state == "queue_loader" and tr.loader == ld.id:
                tr.state = "idle"

    # -- dispatch ------------------------------------------------------------------
    def _plan_rates(self):
        """Target dig rates per loader (t/h) for the blend dispatcher."""
        ls = self.loaders
        r = {k: 0.0 for k in ls}
        avail = {k: self._loader_available(v) or v.state == "relocating" for k, v in ls.items()}
        mill = self.sag["tph"] if self.sag["tph"] > 500 else 3150.0
        cos_corr = (self.cos["t"] - 30000.0) / 4.0
        t_ore = clamp(mill - cos_corr * 0.4, 2400.0, 4300.0)
        se = clamp(float(self.control["east_ore_share"]), 0.0, 1.0)
        if not avail["sh-04"]:
            se = 0.0
        if not avail["sh-01"] and not avail["sh-02"]:
            se = 1.0 if avail["sh-04"] else se
        g1 = ls["sh-01"].block.cu if ls["sh-01"].block else MATERIAL["ore"]["cu"]
        g2 = ls["sh-02"].block.cu if ls["sh-02"].block else MATERIAL["ore_hg"]["cu"]
        g4 = ls["sh-04"].block.cu if ls["sh-04"].block else MATERIAL["ore"]["cu"]
        target = float(self.control["grade_target"])
        fg = self._feed_grade_1h()
        # Central blend that brings the two-pit feed to the target grade.
        tc = (target - se * g4) / max(0.05, 1 - se)
        x = (tc - g1) / max(0.02, g2 - g1)
        if fg > 0:
            x += 0.8 * (target - fg) / max(0.02, g2 - g1) / max(0.3, 1 - se)
        x = clamp(x, 0.04, 0.92)
        if not avail["sh-02"]:
            x = 0.0
        if not avail["sh-01"]:
            x = 1.0
        tc_t = (1 - se) * t_ore
        r["sh-01"] = (1 - x) * tc_t if avail["sh-01"] else 0.0
        r["sh-02"] = x * tc_t if avail["sh-02"] else 0.0
        r["sh-04"] = se * t_ore if avail["sh-04"] else 0.0
        r["sh-03"] = float(self.control["waste_central_tph"]) if avail["sh-03"] else 0.0
        r["ex-01"] = float(self.control["waste_east_tph"]) if avail["ex-01"] else 0.0
        r["ld-01"] = P.CLAY_RATE_TPH if avail["ld-01"] else 0.0
        self.blend_x = x
        return r

    def _feed_grade_1h(self):
        tot = sum(t for _, t, _ in self.feed_hist)
        return sum(t * g for _, t, g in self.feed_hist) / tot if tot > 0 else 0.0

    def _dispatch(self, tr, start):
        policy = self.control["dispatch_policy"]
        cands = [ld for ld in self.loaders.values()
                 if (ld.spec["serves"] == tr.cls or (tr.cls == "777" and not self._loader_available(self.loaders["ld-01"])
                                                    and ld.material != "waste"))
                 and (self._loader_available(ld) or ld.state == "relocating")
                 and ld.pit == getattr(tr, "group", ld.pit)
                 and ld.spur.id not in self.closed]
        if not cands:
            return None
        if policy == "fixed":
            home = self.loaders.get(tr.home)
            return home if home in cands else None

        def wait_h(ld):
            en_route = sum(1 for t in self.trucks if t.loader == ld.id and t.state in ("to_loader", "queue_loader",
                                                                                      "spotting", "loading"))
            load_s = (tr.cap / (ld.spec["bucket"] * ld.spec["fill"] * 1.8)) * ld.spec["cycle"] + P.SPOT_S
            return en_route * load_s / H

        if policy == "min_queue":
            return min(cands, key=wait_h)
        rates = self._plan_rates()
        while self.dispatch_log and self.t - self.dispatch_log[0][0] > H:
            self.dispatch_log.popleft()
        recent = collections.defaultdict(float)
        for _, _, lid, tonnes in self.dispatch_log:
            recent[lid] += tonnes

        def score(ld):
            rate = rates.get(ld.id, 0.0)
            if rate <= 0:
                return -1e9
            prio = {"ore": 1.35, "ore_hg": 1.35, "clay": 1.15, "waste": 1.0}[ld.material]
            return prio * (rate - recent[ld.id]) / rate - 1.6 * wait_h(ld)

        best = max(cands, key=score)
        rate = rates.get(best.id, 0.0)
        # A pit group whose faces are all ahead of plan holds its trucks in
        # reserve rather than overloading the stockpiles.
        if rate <= 0 or (best.material in ("ore", "ore_hg") and recent[best.id] >= 1.4 * rate + tr.cap):
            return None
        return best

    def _send_to_loader(self, tr, ld, start):
        route = self.net.route(start, (ld.spur.id, max(0.0, ld.dist - 12)), closed=self.closed,
                               restricted=self.restricted)
        if route is None:
            tr.state = "standby"
            return
        tr.route = route
        tr.d = 0.0
        tr.loader = ld.id
        tr.state = "to_loader"
        tr.cycle_start = self.t
        ld.assigned += tr.cap
        self.dispatch_log.append((self.t, tr.id, ld.id, tr.cap))

    def _send_to_dest(self, tr, start):
        crusher_ok = self.crusher["state"] in ("running", "starved", "blocked") and not self.control["crusher_down"]
        waste_dump = "dump_e" if getattr(tr, "pit", "central") == "east" else "dump"
        if tr.mat == "waste":
            dest = waste_dump
        elif tr.mat == "clay":
            dest = "clay_plant" if tr.grade >= P.CUTOFF_LG else "dump"
        elif tr.grade >= P.CUTOFF_MILL:
            q = sum(1 for t in self.trucks if t.dest == "crusher" and t.state in ("queue_dump",))
            dest = "crusher" if crusher_ok and q < 3 else "lg"
        elif tr.grade >= P.CUTOFF_LG:
            dest = "lg"
        else:
            dest = waste_dump
        route = self.net.route(start, dest, closed=self.closed, restricted=self.restricted)
        if route is None and dest == "crusher":
            dest = "lg"
            route = self.net.route(start, dest, closed=self.closed, restricted=self.restricted)
        if route is None:
            tr.state = "standby"
            return
        tr.dest = dest
        tr.route = route
        tr.d = 0.0
        tr.state = "hauling"

    def _send_somewhere(self, tr, target_node, state):
        start = self._truck_loc(tr)
        route = self.net.route(start, target_node, closed=self.closed)
        if route is None:
            route = self.net.route(start, target_node)
        tr.route = route
        tr.d = 0.0
        tr.state = state

    def _truck_loc(self, tr):
        if tr.route is not None and tr.route.length > 0:
            end = tr.route.pts[-1] if tr.d >= tr.route.length - 1 else None
            if end is not None:
                for name, p in self.net.nodes.items():
                    if math.dist(p, end) < 1.0:
                        return name
        return self._nearest_loc(tr.pos)

    # -- trucks ------------------------------------------------------------------
    def _speed_target(self, tr, grade, edge):
        road = self.roads[edge.road] if edge else None
        rr = (edge.rr if edge else 0.03) + (road["rr_add"] if road else 0.0)
        mass = (tr.empty + tr.payload) * 1000
        resist = grade + rr
        lim = edge.limit if edge else 20.0
        if edge and edge.road != "road-faces":
            lim = min(lim, float(self.control["speed_limit_kmh"]))
        if self.wx["rain"] > 3:
            lim = min(lim, 35.0)
        if edge and (edge.road in self.restricted):
            lim = min(lim, 15.0)
        if tr.cas:
            lim = min(lim, 12.0)
        if resist > 0:
            v_pow = P.TRUCK_EFFICIENCY * tr.p_kw * 1000 / (mass * 9.81 * resist) * 3.6
        else:
            v_pow = tr.vmax
            if grade < -0.04 and tr.payload > 1:
                v_pow = P.RETARDER_KMH
        v = min(v_pow, tr.vmax, lim)
        power_kw = max(0.0, mass * 9.81 * resist * (v / 3.6) / 1000 / P.TRUCK_EFFICIENCY)
        return v, power_kw

    def _move(self, tr, dt_s):
        if tr.route is None:
            return True
        x, y, z, hd, i, grade = tr.route.at(tr.d)
        edge = tr.route.seg[i] if i < len(tr.route.seg) else None
        v_t, pkw = self._speed_target(tr, grade, edge)
        acc = 0.45 * dt_s * 3.6
        tr.v = clamp(v_t, tr.v - 3 * acc, tr.v + acc)
        tr.v = max(tr.v, 3.0)
        tr.d += tr.v / 3.6 * dt_s
        x, y, z, hd, i, grade = tr.route.at(tr.d)
        tr.pos = (x, y, z)
        tr.heading = hd
        tr.edge = edge.road if edge else None
        if edge is not None:
            r = self.roads[edge.road]
            r["traffic"] += dt_s / 1800 * (tr.v / 30)
        tr.lph = P.IDLE_L_PER_H + pkw * P.BSFC_L_PER_KWH
        tr.power_frac = pkw / tr.p_kw
        return tr.d >= tr.route.length

    def _truck(self, tr, dt_s):
        s = tr.state
        tr.lph = P.IDLE_L_PER_H if s not in ("parked", "in_workshop", "breakdown") else 0.0
        tr.power_frac = 0.1
        if tr.cas and self.t > tr.cas_until:
            tr.cas = False
        if s in ("in_workshop",):
            tr.avail += (0 - tr.avail) * dt_s / (24 * H)
            tr.v = 0.0
            return
        if s == "breakdown":
            tr.avail += (0 - tr.avail) * dt_s / (24 * H)
            tr.v = 0.0
            tr.timer -= dt_s
            if tr.timer <= 0:
                tr.state = "towing"
                tr.route = self.net.route(self._nearest_loc(tr.pos), "workshop") or self.net.route("J1", "workshop")
                tr.d = 0.0
            return
        if s == "towing":
            tr.avail += (0 - tr.avail) * dt_s / (24 * H)
            tr.v = 10.0
            tr.d += 10 / 3.6 * dt_s
            x, y, z, hd, *_ = tr.route.at(tr.d)
            tr.pos, tr.heading = (x, y, z), hd
            if tr.d >= tr.route.length:
                self._enter_workshop(tr, "repair")
            return
        if s == "parked":
            tr.v = 0.0
            if not tr.parked:
                tr.state = "idle"
            return
        if s == "no_fuel":
            # Engine stopped with an empty tank: the truck waits where it stands
            # for the field fuel bowser (A), which brings what the station holds.
            tr.v = 0.0
            tr.lph = 0.0
            tr.timer -= dt_s
            if tr.timer <= 0:
                got = min(P.BOWSER_L, self.fuel_tank * 1000)
                if got <= 0:
                    tr.timer = 30 * 60.0          # station dry: the bowser comes after the next delivery
                    return
                self.fuel_tank -= got / 1000
                tr.fuel += got
                tr.state = tr.prev_state or "idle"
                self.log("info", f"{tr.id.upper()}: заправщик залил {got:.0f} л, машина продолжает работу", tr.id)
            return
        if tr.fuel <= 0.0 and s not in ("refueling",):
            tr.prev_state = s
            tr.state = "no_fuel"
            tr.timer = P.BOWSER_RESPONSE_S
            tr.v = 0.0
            self.kpi["out_of_fuel"] += 1
            self.log("alarm", f"{tr.id.upper()}: закончилось топливо, двигатель остановлен — ждёт заправщик", tr.id)
            return
        tr.avail += (1 - tr.avail) * dt_s / (24 * H)
        moving = s in ("to_loader", "hauling", "to_fuel", "to_workshop", "to_park", "to_reserve")
        if moving:
            arrived = self._move(tr, dt_s)
        else:
            tr.v = 0.0
            arrived = False
        tr.fuel = max(0.0, tr.fuel - tr.lph * dt_s / H)   # an empty tank stops the truck on the next step
        self.energy["diesel_l"] += tr.lph * dt_s / H
        self.shift_kpi["diesel_l"] += tr.lph * dt_s / H
        if s not in ("idle", "standby", "queue_loader", "queue_dump"):
            stress = 0.6 + 0.9 * getattr(tr, "power_frac", 0.1) + 8 * self.roads.get(tr.edge or "road-main",
                                                                                      {"rr_add": 0})["rr_add"]
            if tr.wear(dt_s, stress, self.rng, "truck") and s not in ("loading", "spotting", "dumping"):
                tr.state = "breakdown"
                tr.failures += 1
                tr.timer = P.RESPONSE_H * H
                tr.v = 0.0
                self.kpi["failures"] += 1
                self.log("alarm", f"Отказ {tr.id.upper()} ({tr.model}) на дороге "
                                  f"{(tr.edge or '').replace('road-', '')}: "
                                  f"{CM.SUBSYS_RU[CM.dominant(tr)] if hasattr(tr, 'cm') else 'двигатель'}; {tr.cm_text()}", tr.id)
                return
        if s == "idle" or s == "standby":
            if tr.parked:
                self._send_somewhere(tr, "workshop", "to_park")
                return
            if tr.fuel < P.REFUEL_BELOW * tr.tank:
                self._send_somewhere(tr, "fuel", "to_fuel")
                return
            if self._maint_due(tr):
                self._send_somewhere(tr, "workshop", "to_workshop")
                return
            ld = self._dispatch(tr, None)
            if ld is None:
                # No face needs this truck now: wait in the reserve bay of its pit.
                bay = "park_e" if tr.group == "east" else "park_c"
                if s == "idle" and self._truck_loc(tr) != bay:
                    self._send_somewhere(tr, bay, "to_reserve")
                    if tr.route is None:
                        tr.state = "standby"
                else:
                    tr.state = "standby"
                return
            self._send_to_loader(tr, ld, start=self._truck_loc(tr))
            return
        if s == "to_reserve" and arrived:
            tr.state = "standby"
            # side by side in the bay, not on top of each other
            bay = self.net.nodes["park_e" if tr.group == "east" else "park_c"]
            tr.pos = self._free_slot(tr, bay, 22.0, 30.0, 5, ("standby",))
            return
        if s == "to_loader" and arrived:
            ld = self.loaders[tr.loader]
            if not (self._loader_available(ld) or ld.state == "relocating"):
                tr.state = "idle"
                return
            tr.state = "queue_loader"
            tr.queue_start = self.t
            ld.queue.append(tr)
        elif s == "queue_loader":
            ld = self.loaders.get(tr.loader)
            if ld is None or not (self._loader_available(ld) or ld.state in ("relocating", "spotting", "loading")):
                tr.state = "idle"
            elif tr in ld.queue:
                # Queued trucks line up along the face road, one truck length apart.
                room = max(0.0, ld.dist - 12.0)
                gap = max(15.0, min(26.0, room / (len(ld.queue) + 1)))   # squeeze up on a short face road
                d = room - gap * (ld.queue.index(tr) + 1)
                over = 0.0
                if d < 0.0:                       # the face road is full: wait beside its start
                    over, d = -d, 0.0
                x, y, z = ld.spur.point_at(d)
                ax, ay, _ = ld.spur.point_at(min(ld.spur.length, d + 5.0))
                hd = math.atan2(ay - y, ax - x)
                tr.pos = (x - math.cos(hd) * over * 0.6 - math.sin(hd) * over * 0.8,
                          y - math.sin(hd) * over * 0.6 + math.cos(hd) * over * 0.8, z)
                tr.heading = math.degrees(hd)
        elif s == "hauling" and arrived:
            tr.state = "queue_dump"
            tr.queue_start = self.t
        elif s == "queue_dump":
            self._try_dump(tr)
            self._dump_spot(tr)
            if tr.state == "queue_dump" and tr.route is not None:
                # Line up on the approach road behind the trucks that came first.
                ahead = sum(1 for t in self.trucks if t is not tr and t.state == "queue_dump" and t.dest == tr.dest
                            and t.queue_start < tr.queue_start)
                x, y, z, hd, *_ = tr.route.at(max(0.0, tr.route.length - 26.0 * (ahead + 1)))
                tr.pos, tr.heading = (x, y, z), hd
        elif s == "dumping":
            tr.timer += dt_s
            if tr.timer >= P.DUMP_S:
                self._deliver(tr)
        elif s == "to_fuel" and arrived:
            tr.state = "refueling"
            tr.timer = 0.0
            fx, fy, fz = FACILITIES["fuel"]
            tr.pos = self._free_slot(tr, (fx - 20.0, fy + 25.0, fz), 20.0, 28.0, 3, ("refueling",))
        elif s == "refueling":
            tr.timer += dt_s
            if tr.timer >= P.REFUEL_S:
                # Only what the station holds; an empty station keeps the truck
                # waiting for the next rail delivery.
                got = min(tr.tank - tr.fuel, self.fuel_tank * 1000)
                self.fuel_tank = max(0.0, self.fuel_tank - got / 1000)
                tr.fuel += got
                if tr.fuel < P.REFUEL_BELOW * tr.tank:
                    tr.timer = 0.0
                    tr.state = "refueling"
                    if not getattr(self, "_dry_logged", False) and not self.mute:
                        self._dry_logged = True
                        self.log("alarm", "АЗС: резервуар пуст — самосвалы ждут поставку дизтоплива", "fs-01")
                else:
                    tr.state = "idle"
        elif s == "to_workshop" and arrived:
            self._enter_workshop(tr, "pm" if self.control["maintenance_strategy"] == "preventive" else "pdm")
        elif s == "to_park" and arrived:
            tr.state = "parked"
        elif s in ("loading", "spotting"):
            pass

    def _try_dump(self, tr):
        if tr.dest == "crusher":
            c = self.crusher
            if self.control["crusher_down"] or c["state"] == "mantle_change":
                tr.dest = "lg"
                tr.route = self.net.route("crusher", "lg", closed=self.closed) or self.net.route("crusher", "lg")
                tr.d = 0.0
                tr.state = "hauling"
                return
            # Loads already being tipped are reserved in the pocket: two trucks
            # must not be admitted into the same free space.
            tipping = [t for t in self.trucks if t.state == "dumping" and t.dest == "crusher"]
            reserved = sum(t.payload for t in tipping)
            if len(tipping) < c["slots"] and c["pocket"] + reserved + tr.payload <= P.CRUSHER_POCKET_T:
                tr.state = "dumping"
                tr.timer = 0.0
        elif tr.dest == "clay_plant":
            tipping = [t for t in self.trucks if t.state == "dumping" and t.dest == "clay_plant"]
            reserved = sum(t.payload for t in tipping)
            if not tipping and self.clay_plant["hopper"] + reserved + tr.payload <= P.CLAY_HOPPER_T:
                tr.state = "dumping"
                tr.timer = 0.0
        else:
            tr.state = "dumping"
            tr.timer = 0.0

    def _dump_spot(self, tr):
        """Trucks tipping at the same place stand side by side along the
        dump edge / crusher wall, perpendicular to the approach road."""
        if tr.state != "dumping":
            return
        x, y, z = tr.pos
        hd = math.radians(tr.heading)
        k = sum(1 for t in self.trucks if t is not tr and t.state == "dumping" and t.dest == tr.dest)
        side = (k + 1) // 2 * (1 if k % 2 else -1) * 16.0
        tr.pos = (x - math.sin(hd) * side, y + math.cos(hd) * side, z)

    def _deliver(self, tr):
        t = tr.payload
        lot = tr.lot or dict(cu=tr.grade, clay=0.05, au=0.1, ucs=110, bwi=14.5, x80=0.7)
        if tr.dest == "crusher":
            c = self.crusher
            c["lot"] = self._mix(c["lot"], c["pocket"], lot, t)
            c["pocket"] += t
            c["dumps"].append(self.t)
            self.shift_kpi["ore_crusher_t"] += t
        elif tr.dest == "clay_plant":
            cp = self.clay_plant
            cp["lot"] = self._mix(cp["lot"], cp["hopper"], lot, t)
            cp["hopper"] += t
            self.shift_kpi["clay_t"] += t
        elif tr.dest == "lg":
            s = self.lg_stock
            for k in ("cu", "clay", "au", "ucs", "bwi"):
                s[k] = (s[k] * s["t"] + lot.get(k, s[k]) * t) / (s["t"] + t)
            s["t"] += t
            self.shift_kpi["lg_t"] += t
        elif tr.dest == "dump_e":
            self.dump_e_t += t
        else:
            self.dump_t += t
        for d in (self.kpi, self.shift_kpi):
            d["moved_t"] += t
            d["ore_t" if tr.dest in ("crusher", "lg", "clay_plant") else "waste_t"] += t
        self._pit_account(getattr(tr, "pit", "central"), t, tr.dest in ("crusher", "lg", "clay_plant"))
        tr.tonnes += t
        tr.trips += 1
        tr.last_cycle = (self.t - tr.cycle_start) / 60
        self.kpi["cycle_min_sum"] += tr.last_cycle
        self.kpi["cycles"] += 1
        tr.payload = 0.0
        tr.grade = 0.0
        tr.lot = None
        tr.mat = None
        tr.loader = None
        tr.state = "idle"
        start = tr.dest
        tr.dest = None
        if tr.parked:
            self._send_somewhere(tr, "workshop", "to_park")
        elif tr.fuel < P.REFUEL_BELOW * tr.tank:
            self._send_somewhere(tr, "fuel", "to_fuel")
        elif self._maint_due(tr):
            self._send_somewhere(tr, "workshop", "to_workshop")
            self.log("info", f"{tr.id.upper()} направлен на "
                             f"{'ТО по наработке' if self.control['maintenance_strategy'] == 'preventive' else 'ТО по состоянию'}"
                             f" ({tr.cm_text()})", tr.id)
        else:
            ld = self._dispatch(tr, start)
            if ld is None:
                # held back: drive empty to the reserve bay of its pit
                self._send_somewhere(tr, "park_e" if tr.group == "east" else "park_c", "to_reserve")
                if tr.route is None:
                    tr.state = "standby"
            else:
                self._send_to_loader(tr, ld, start=start)

    # -- workshop ------------------------------------------------------------------
    def _enter_workshop(self, tr, kind):
        if tr.payload > 0:
            s = self.lg_stock
            s["t"] += tr.payload
            tr.payload, tr.grade, tr.lot, tr.mat = 0.0, 0.0, None, None
        tr.dest = None
        tr.state = "in_workshop"
        tr.v = 0.0
        tr.pos = self._bay_pos(tr)
        dur = {"repair": tr.rng.uniform(*P.REPAIR_H), "pm": P.PM_DURATION_H, "pdm": P.PDM_DURATION_H}[kind]
        self.workshop["queue"].append(dict(truck=tr, kind=kind, dur=dur * H, left=dur * H, t_in=self.t))
        if tr.loader and kind != "repair":
            tr.loader = None

    def _workshop(self, dt_s):
        ws = self.workshop
        while len(ws["bays"]) < P.WORKSHOP_BAYS and ws["queue"]:
            q = sorted(ws["queue"], key=lambda j: 0 if j["kind"] == "repair" else 1)
            job = q[0]
            ws["queue"].remove(job)
            ws["bays"].append(job)
        for job in list(ws["bays"]):
            job["left"] -= dt_s
            if job["left"] <= 0:
                tr = job["truck"]
                ws["bays"].remove(job)
                ws["done"] += 1
                ws["mttr_sum"] += (self.t - job["t_in"]) / H
                tr.health = 95.0 if job["kind"] in ("repair", "pdm") else min(92.0, tr.health + 45)
                tr.since_pm = 0.0
                tr.state = "idle"
                tr.pos = self._bay_pos(tr)
                self.log("info", f"{tr.id.upper()} вышел из ремзоны "
                                 f"({ {'repair': 'ремонт', 'pm': 'ТО', 'pdm': 'ТО по состоянию'}[job['kind']] }, "
                                 f"{(self.t - job['t_in']) / H:.1f} ч)", tr.id)

    # -- service vehicles ------------------------------------------------------------
    def _mover_step(self, m, dt_s, speed):
        if m.route is None:
            return True
        m.v = speed
        m.d += speed / 3.6 * dt_s
        x, y, z, hd, i, _ = m.route.at(m.d)
        m.pos, m.heading = (x, y, z), hd
        seg = m.route.seg[i] if i < len(m.route.seg) else None
        m.edge = seg.road if seg else None
        return m.d >= m.route.length

    def _water_truck(self, dt_s):
        w = self.wt
        if w.state == "refill":
            w.timer -= dt_s
            w.v = 0
            if w.timer <= 0:
                w.water = P.WATER_TRUCK_M3
                w.state = "parked"
            return
        if w.route is None or w.state == "parked":
            a = w.loop[w.li % len(w.loop)]
            b = w.loop[(w.li + 1) % len(w.loop)]
            w.li += 1
            w.route = self.net.route(a, b, closed=self.closed)
            w.d = 0.0
            w.state = "spraying"
            if w.route is None:
                w.state = "parked"
                return
        done = self._mover_step(w, dt_s, 28.0)
        if self.wx["rain"] < 0.5 and w.edge and w.water > 0:
            r = self.roads[w.edge]
            r["moisture"] = min(1.0, r["moisture"] + 0.9 * dt_s / 90)
            w.water = max(0.0, w.water - 0.010 * 28 / 3.6 * dt_s)
        if done:
            w.route = None
            w.state = "parked"
            if w.water <= 3:
                w.route = self.net.route(w.loop[(w.li) % len(w.loop)], "fuel", closed=self.closed)
                w.d = 0
                w.state = "to_refill"
        if w.state == "to_refill" and w.route and w.d >= w.route.length:
            w.state = "refill"
            w.timer = 600

    def _light_vehicles(self, dt_s):
        lv1 = self.lvs["lv-01"]
        target = None
        if self.blast and self.blast["phase"] == "clearing":
            target = "J1"
        elif self.charging is not None:
            target = (self.charging.spur.id, self.charging.dist + 30)
        elif self.drills and any(d.block for d in self.drills):
            d = next(d for d in self.drills if d.block)
            target = (d.block.spur.id, d.block.dist + 30)
        self._lv_go(lv1, target, dt_s)
        p1 = self.people["p-01"]
        if lv1.state == "on_site":
            # Park off the haul lanes: towards the pit wall in the pit, aside the junction on surface.
            x, y, z = lv1.pos
            if z < -5:
                lv1.park = self._toward_wall(x, y, z, 9.0)
            else:
                lv1.park = (x + 70, y + 90, z)
        else:
            lv1.park = None
        if lv1.state == "on_site" and self.charging is not None:
            b = self.charging
            ang = self.t / 120.0
            p1["pos"] = (b.pos[0] + 25 * math.cos(ang), b.pos[1] + 25 * math.sin(ang), b.pos[2])
        else:
            p1["pos"] = lv1.park or lv1.pos
        lv2 = self.lvs["lv-02"]
        if lv2.state in ("on_site",) and lv2.timer <= 0:
            lv2.fi += 1
            lv2.state = "parked"
        if lv2.state == "on_site":
            lv2.timer -= dt_s
        ld = self.loaders[lv2.faces[lv2.fi % len(lv2.faces)]]
        if ld.spur.id in self.closed or (self.blast and self._in_blast_zone(ld.pos)):
            lv2.fi += 1
            ld = self.loaders[lv2.faces[lv2.fi % len(lv2.faces)]]
        self._lv_go(lv2, (ld.spur.id, max(0.0, ld.dist - 45)), dt_s, dwell=20 * 60)
        p3 = self.people["p-03"]
        if lv2.state == "on_site":
            # Park off the haul lane, on the bench crest side, and sample the face on foot.
            x, y, z = lv2.pos
            lv2.park = self._toward_wall(x, y, z, 9.0)
            ang = self.t / 90.0
            p3["pos"] = (lv2.park[0] + 10 * math.cos(ang), lv2.park[1] + 10 * math.sin(ang), z)
        else:
            lv2.park = None
            p3["pos"] = lv2.pos
        p2 = self.people["p-02"]
        hh = int(self.t // 1200) % 4
        p2["pos"] = [FACILITIES["sag"], FACILITIES["flot_r"], FACILITIES["substation"], FACILITIES["th_t"]][hh]
        p4 = self.people["p-04"]
        s = self.radar[int(self.t // 1800) % 3]
        # The surveyor checks the monitored wall from the pit rim above the sector.
        p4["pos"] = ((P.PIT_A + 45) * math.cos(s["theta"]), (P.PIT_B + 45) * math.sin(s["theta"]), 0.0)

    def _free_slot(self, tr, origin, dx, dy, per_row, states):
        """First free parking place in a yard laid out in rows from `origin`,
        so that waiting trucks stand side by side, not inside each other."""
        taken = [t.pos for t in self.trucks if t is not tr and t.state in states]
        for k in range(60):
            p = (origin[0] + dx * (k % per_row), origin[1] + dy * (k // per_row), origin[2])
            if all(math.dist(p[:2], q[:2]) > 3.0 for q in taken):
                return p
        return origin

    def _bay_pos(self, tr):
        """The workshop yard: 4 bays in a row, the queue in rows behind."""
        wx, wy, wz = FACILITIES["workshop"]
        return self._free_slot(tr, (wx - 45.0, wy - 60.0, wz), 30.0, -35.0, 4, ("in_workshop",))

    @staticmethod
    def _toward_wall(x, y, z, metres):
        """A point `metres` off the haul lane towards the wall of the pit that
        contains (x, y): parked vehicles stay on their bench."""
        from .geometry import pit_at
        pit = pit_at(x, y) or "central"
        g = P.PITS[pit]
        dx, dy = x - g["cx"], y - g["cy"]
        nx, ny = dx / g["a"] ** 2, dy / g["b"] ** 2          # ellipse normal, outwards
        n = math.hypot(nx, ny) or 1.0
        return (x + metres * nx / n, y + metres * ny / n, z)

    def _lv_go(self, lv, target, dt_s, dwell=None):
        if target is None:
            return
        if lv.target != target and lv.state != "on_site":
            route = self.net.route(self._nearest_loc(lv.pos), target, closed=self.closed)
            lv.target = target
            lv.route = route
            lv.d = 0.0
            lv.state = "driving" if route else "parked"
        if lv.state == "driving":
            if self._mover_step(lv, dt_s, 38.0 if not (lv.edge or "").endswith("faces") else 18.0):
                lv.state = "on_site"
                lv.timer = dwell or 0
                lv.v = 0.0
        elif lv.state == "on_site" and dwell is None and lv.target != target:
            lv.state = "parked"

    def _proximity(self):
        """Collision avoidance (CAS): truck vs light vehicle / person on foot."""
        # Moving vehicles keep to their lanes; CAS events come from parked light
        # vehicles and from people on foot near the haul lanes.
        objs = [(k, getattr(v, "park", None) or v.pos) for k, v in self.lvs.items() if v.state == "on_site"]
        for k, p in self.people.items():
            lv = self.lvs.get(p.get("lv") or "")
            if lv is None or lv.state == "on_site":
                objs.append((k, p["pos"]))
        for tr in self.trucks:
            if tr.state in ("in_workshop", "parked", "breakdown"):
                continue
            for oid, pos in objs:
                dd = math.dist(tr.pos, pos)
                if dd < 60:
                    tr.cas = True
                    tr.cas_until = self.t + 60
                if dd < (22 if oid.startswith("p-") else 15) and tr.v > 5:
                    key = (tr.id, oid)
                    if self.t - self.cas_pairs.get(key, -1e9) > 600:
                        self.cas_pairs[key] = self.t
                        self.shift_kpi["cas_alerts"] += 1
                        self.kpi["cas_alerts"] += 1
                        self.log("warn", f"CAS: {tr.id.upper()} ↔ {oid.upper()} — {dd:.0f} м, "
                                         f"скорость снижена до 12 км/ч", tr.id)

    # -- processing plant -------------------------------------------------------------
    def _plant(self, dt_s):
        dth = dt_s / H
        c = self.crusher
        # Crusher state.
        if self.control["crusher_down"]:
            if c["state"] != "down":
                self.log("alarm", "ККД-1 остановлен (сценарий): руда направляется на склад забалансовой руды", "gc-01")
            c["state"] = "down"
        elif c["state"] == "down":
            c["state"] = "running"
            self.log("info", "ККД-1 запущен", "gc-01")
        if c["state"] == "mantle_change":
            c["down_left"] -= dt_s
            if c["down_left"] <= 0:
                c["wear"] = 0.0
                c["state"] = "running"
                self.log("info", "ККД-1: замена брони завершена", "gc-01")
        # Rehandle low-grade stock when the pocket is low and the COS needs ore.
        c["reclaim"] = 0.0
        if c["state"] in ("running", "starved") and c["pocket"] < 200 and self.cos["t"] < 20000 and \
                self.lg_stock["t"] > 1000:
            rt = 700.0 * dth
            c["reclaim"] = 700.0
            lot = {k: self.lg_stock[k] for k in ("cu", "clay", "au", "ucs", "bwi")}
            lot["x80"] = 0.5
            c["lot"] = self._mix(c["lot"], c["pocket"], lot, rt)
            c["pocket"] += rt
            self.lg_stock["t"] -= rt
        cap = P.CRUSHER_TPH * clamp(0.75 + 0.25 * 0.7 / max(c["lot"]["x80"], 0.2), 0.75, 1.12)
        cap *= clamp(1.08 - 0.10 * c["wear"] / 100, 0.9, 1.08)
        crushed = 0.0
        if c["state"] in ("running", "starved", "blocked"):
            # Free room on the stockpile counts the ore already on the 2.1 km belt.
            on_belt = sum(t for _, t, _ in self.conveyor)
            room = P.COS_TOTAL_T - self.cos["t"] - on_belt
            if room <= 0:
                c["state"] = "blocked"
            else:
                crushed = min(c["pocket"], cap * dth, room)
                c["state"] = "running" if crushed > 0.3 * cap * dth else ("blocked" if room < cap * dth else "starved")
        c["pocket"] -= crushed
        c["tph"] = c["tph"] + (crushed / dth - c["tph"]) * min(1.0, dt_s / 300)
        c["total"] += crushed
        c["wear"] += crushed / 3.2e6 * 100 * (c["lot"]["ucs"] / 115)
        if c["wear"] >= 100 and c["state"] != "mantle_change":
            c["state"] = "mantle_change"
            c["down_left"] = 12 * H
            self.log("alarm", "ККД-1: износ брони 100 % — остановка на замену (12 ч)", "gc-01")
        while c["dumps"] and self.t - c["dumps"][0] > H:
            c["dumps"].popleft()
        if crushed > 0:
            lot = dict(c["lot"])
            lot["f80"] = 135.0 * (lot["x80"] / 0.7) ** 0.6
            self.conveyor.append((self.t + P.CONVEYOR_LEN_M / P.CONVEYOR_SPEED, crushed, lot))
        # Conveyor delivers to the coarse ore stockpile.
        cos = self.cos
        arrived = 0.0
        while self.conveyor and self.conveyor[0][0] <= self.t:
            _, t, lot = self.conveyor.popleft()
            for k in ("cu", "clay", "au", "bwi", "f80"):
                cos[k] = (cos[k] * cos["t"] + lot[k] * t) / (cos["t"] + t) if cos["t"] + t > 0 else lot[k]
            cos["t"] += t
            arrived += t
        self.conv_tph = sum(t for _, t, _ in self.conveyor) / max(1.0, P.CONVEYOR_LEN_M / P.CONVEYOR_SPEED) * H
        # SAG mill: power-limited throughput (operators push to the power limit).
        zone, price = self.tariff()
        shave = self.control["peak_shaving"] and zone == "peak"
        p_max = P.SAG_DRAW_MAX * (0.80 if shave else 1.0)
        bm_draw = P.BM_DRAW * (0.88 if shave else 1.0)
        sag = self.sag
        e = 7.9 * (cos["bwi"] / 14.5) ** 0.9 * (cos["f80"] / 135.0) ** 0.45 * (1 + 0.35 * cos["clay"])
        sag["e"] = e
        bm_power = sum(bm_draw for b in self.bm if b["state"] == "running")
        t80 = 1900.0 * (max(sag["tph"], 500) / 3150.0) ** 0.4
        w_need = 10 * cos["bwi"] * (1 / math.sqrt(P.P80_MAX) - 1 / math.sqrt(t80))
        q_bm = bm_power * 1000 / max(w_need, 0.5)
        q_sag = p_max * 1000 / e
        q = min(q_sag, q_bm, 4300.0)
        if cos["t"] < 1500:
            q = min(q, cos["t"] / max(dth, 1e-6) * 0.5, sag["tph"] * 0.95)
        if cos["t"] <= 0:
            q = 0.0
        sag["tph"] += (q - sag["tph"]) * min(1.0, dt_s / 600)
        fed = min(cos["t"], sag["tph"] * dth)
        cos["t"] -= fed
        sag["power"] = min(p_max, sag["tph"] * e / 1000) if sag["tph"] > 1 else 1.5
        sag["state"] = "running" if sag["tph"] > 300 else "starved"
        sag["t80"] = t80
        sag["liner"] = max(0.0, sag["liner"] - fed / 9.0e6 * 100 * (cos["bwi"] / 14.5))
        sag["speed"] = 72 + 6 * (sag["power"] / P.SAG_DRAW_MAX - 0.8)
        for b in self.bm:
            b["power"] = bm_draw if (b["state"] == "running" and sag["tph"] > 300) else 0.3
        # Bond: product size from ball-mill specific energy.
        if sag["tph"] > 100:
            w = sum(b["power"] for b in self.bm) * 1000 / sag["tph"]
            self.p80 = (w / (10 * cos["bwi"]) + 1 / math.sqrt(t80)) ** -2
        # Flotation: first-order kinetics, residence time from slurry flow.
        f = self.flot
        g = cos["cu"]
        clay = cos["clay"]
        qs = max(sag["tph"], 1.0) * (1 / 2.7 + 0.65 / 0.35)
        f["tau"] = P.FLOT_VOL_M3 / qs * 60
        f["k"] = P.FLOT_K0 * math.exp(-((self.p80 - 95) / 150) ** 2) * (1 - 1.4 * clay)
        r_inf = P.R_INF * (1 - 0.03 / max(g, 0.05)) * (1 - 0.5 * max(0.0, clay - 0.05))
        rec = r_inf * (1 - math.exp(-f["k"] * f["tau"])) if sag["tph"] > 100 else 0.0
        f["rec"] = max(0.0, rec)
        f["conc_grade"] = P.CONC_GRADE * (1 - 0.6 * max(0.0, clay - 0.05)) * (0.96 + 0.04 * g / 0.41)
        # Metal follows the ore actually fed in this step (no output from an empty
        # mill); the smoothed sag["tph"] only drives power and residence time.
        feed_tph = fed / max(dth, 1e-9)
        f["cu_tph"] = feed_tph * g / 100 * f["rec"]
        f["conc_tph"] = f["cu_tph"] / (f["conc_grade"] / 100) if f["conc_grade"] > 0 else 0
        tails = max(feed_tph - f["conc_tph"], 0.0)
        f["tails_cu"] = (feed_tph * g / 100 - f["cu_tph"]) / max(tails, 1) * 100 if feed_tph > 1 else 0.0
        f["xanthate"] = 22 + 60 * clay
        f["air"] = 0.9 + 0.3 * (sag["tph"] / 3150)
        au_oz = feed_tph * cos["au"] * P.AU_RECOVERY * (f["rec"] / 0.765) / 31.1035
        # Clay plant.
        cp = self.clay_plant
        cpt = min(cp["hopper"], P.CLAY_PLANT_TPH * dth)
        cp["hopper"] -= cpt
        cp["tph"] += (cpt / dth - cp["tph"]) * min(1.0, dt_s / 300)
        cp["rec"] = clamp(0.66 - 0.30 * (cp["lot"]["clay"] - 0.30), 0.45, 0.72)
        cp["cu_tph"] = cpt / max(dth, 1e-9) * cp["lot"]["cu"] / 100 * cp["rec"]
        # Thickeners, tailings, water.
        th = self.thick
        th["c_ud"] = 64 - 6 * max(0, clay - 0.05)
        th["t_ud"] = 58 - 18 * max(0, clay - 0.05)
        th["ntu"] = 30 + 400 * max(0, clay - 0.04)
        th["floc"] = 16 + 70 * max(0, clay - 0.04)
        water_t = tails / (th["t_ud"] / 100) - tails
        self.tsf["volume"] += (tails / 1.45 + water_t * 0.45) * dth
        self.tsf["freeboard"] = 3.2 - (self.tsf["volume"] - 41.5e6) / 1.8e6
        self.tsf["reclaim"] = water_t * 0.55
        total_feed = sag["tph"] + cp["tph"]
        self.water["fresh"] = P.WATER_M3_PER_T * total_feed
        self.water["reclaim"] = self.tsf["reclaim"]
        # Feed history for the blend controller (1 h rolling).
        self.feed_hist.append((self.t, fed, g))
        while self.feed_hist and self.t - self.feed_hist[0][0] > H:
            self.feed_hist.popleft()
        # KPIs.
        cu = f["cu_tph"] * dth + cp["cu_tph"] * dth
        for d in (self.kpi, self.shift_kpi):
            d["mill_t"] += fed
            d["cu_t"] += cu
            d["au_oz"] += au_oz * dth
            d["clay_proc_t"] += cpt
            d["mill_grade_t"] += fed * g
            d["rec_t"] += fed * f["rec"]
            if abs(g - float(self.control["grade_target"])) <= P.GRADE_BAND:
                d["inband_s"] += dt_s
            d["feed_s"] += dt_s

    # -- dust and gases ------------------------------------------------------------------
    def _dust_gas(self, dt_s):
        w = self.wx
        if self.plume:
            pl = self.plume
            pl["age"] += dt_s
            ang = math.radians((w["wind_dir"] + 180) % 360)  # wind comes FROM wind_dir
            sp = w["wind"] * dt_s
            pl["x"] += math.sin(ang) * sp
            pl["y"] += math.cos(ang) * sp
            pl["r"] = 60 + 1.6 * pl["age"] ** 0.85
            pl["mass"] *= math.exp(-dt_s / (25 * 60))
            if pl["age"] > 2.5 * H or pl["mass"] < 500:
                self.plume = None
        washout = 0.3 if w["rain"] > 1 else 1.0
        for mid in self.dust:
            mp = FACILITIES[mid]
            c = 22.0
            for e in self.net.edges.values():
                r = self.roads[e.road]
                dmin = min(math.dist(mp[:2], p[:2]) for p in e.pts[:: max(1, len(e.pts) // 6)])
                if dmin < 700:
                    c += 160 * r["traffic"] * (1 - 0.85 * r["moisture"]) * (1 + w["wind"] / 8) * math.exp(-dmin / 260)
            if mid == "dm-02":
                c += 10 * len(self.crusher["dumps"]) / 6
            if self.plume:
                pl = self.plume
                d = math.dist(mp[:2], (pl["x"], pl["y"]))
                c += pl["mass"] / 6.0 * math.exp(-(d ** 2) / (2 * pl["r"] ** 2)) / (1 + pl["r"] / 200)
            c *= washout
            self.dust[mid] += (c - self.dust[mid]) * min(1.0, dt_s / 300)
        g = self.gas
        if g["status"] != "open" or g["co"] > 3:
            tau = 600 * math.sqrt(3 / (w["wind"] + 1))
            g["co"] = max(1.5, g["co"] * math.exp(-dt_s / tau))
            g["no2"] = max(0.05, g["no2"] * math.exp(-dt_s / tau))

    # -- energy ----------------------------------------------------------------------------
    def _energy(self, dt_s):
        dth = dt_s / H
        sag = self.sag
        load = clamp(sag["tph"] / 3150, 0, 1.4)
        cp_load = self.clay_plant["tph"] / P.CLAY_PLANT_TPH
        br = {
            "ККД-1": (0.15 + P.CRUSHER_KW / 1000 * clamp(self.crusher["tph"] / P.CRUSHER_TPH, 0, 1.2))
            if self.crusher["state"] not in ("down", "mantle_change") else 0.05,
            "Конвейер": 0.25 + P.CONVEYOR_KW / 1000 * clamp(self.conv_tph / P.CONVEYOR_TPH, 0, 1.2),
            "МПСИ": sag["power"],
            "ШМ-1": self.bm[0]["power"],
            "ШМ-2": self.bm[1]["power"],
            "Флотация": P.FLOT_MW * (0.6 + 0.4 * load),
            "Насосы и сгустители": P.PUMPS_MW * (0.5 + 0.5 * load),
            "Глинистая фабрика": 0.8 + (P.CLAY_PLANT_MW - 0.8) * cp_load,
            "Водовод": P.WATER_PUMP_MW * (0.4 + 0.6 * load),
            "Вспомогательные": P.AUX_MW,
        }
        mw = sum(br.values())
        e = self.energy
        e["breakdown"] = br
        e["mw"] = mw
        zone, price = self.tariff()
        e["zone"] = zone
        e["price"] = price
        e["cost_h"] = mw * 1000 * price
        diesel_lph = sum(t.lph for t in self.trucks) + sum(l.lph for l in self.loaders.values()) + \
            sum(d.lph for d in self.drills) + 60.0
        e["diesel_lph"] = diesel_lph
        e["mvar"] = mw * math.tan(math.acos(0.93))
        e["co2_h"] = mw * P.GRID_T_CO2_PER_MWH + diesel_lph * P.DIESEL_KG_CO2_PER_L / 1000
        self.fuel_tank = max(0.0, self.fuel_tank - (diesel_lph - sum(t.lph for t in self.trucks)) * dth / 1000)
        if self.now.hour == 6 and getattr(self, "_rail_today", None) != self.now.date():
            self._rail_today = self.now.date()
            self.fuel_tank = 400.0
            self._dry_logged = False
            self.log("info", "АЗС: прибыл ж/д состав с дизтопливом, резервуар 400 м³", "fs-01")
        for d in (self.kpi, self.shift_kpi):
            d["mwh"] += mw * dth
            d["el_cost"] += mw * 1000 * price * dth
            d["diesel_all_l"] += diesel_lph * dth
            d["co2_t"] += e["co2_h"] * dth
        self.peak_window = getattr(self, "peak_window", collections.deque())
        self.peak_window.append((self.t, mw))
        while self.peak_window and self.t - self.peak_window[0][0] > 900:
            self.peak_window.popleft()
        avg15 = sum(m for _, m in self.peak_window) / len(self.peak_window)
        if self.now.hour == 0 and self.now.minute == 0:
            e["peak_mw"] = 0.0
        e["avg15"] = avg15
        e["peak_mw"] = max(e["peak_mw"], avg15)
        self.kpi["peak_mw_max"] = max(self.kpi["peak_mw_max"], avg15)

    # -- KPIs for the forecaster --------------------------------------------------------------
    def kpis(self):
        k = self.kpi
        cap = k["peak_mw_max"] * P.CAPACITY_KZT_PER_MW_DAY * k["sim_s"] / 86400
        cost = k["el_cost"] + k["diesel_all_l"] * P.DIESEL_KZT_PER_L + k["explosive_kg"] * P.EXPLOSIVE_KZT_PER_KG + cap
        fleet = [t for t in self.trucks]
        return {
            "cu_t": k["cu_t"],
            "ore_t": k["ore_t"],
            "waste_t": k["waste_t"],
            "cos_end_kt": self.cos["t"] / 1000,
            "margin_mkzt": (k["cu_t"] * P.CU_NET_KZT_T + k["au_oz"] * P.AU_NET_KZT_OZ - cost) / 1e6,   # cost includes cap
            "mill_t": k["mill_t"],
            "moved_t": k["moved_t"],
            "feed_grade": k["mill_grade_t"] / k["mill_t"] if k["mill_t"] else 0.0,
            "recovery": k["rec_t"] / k["mill_t"] * 100 if k["mill_t"] else 0.0,
            "kwh_t": k["mwh"] * 1000 / k["mill_t"] if k["mill_t"] else 0.0,
            "diesel_l": k["diesel_all_l"],
            "cost_mkzt": cost / 1e6,
            "cost_kzt_t_cu": cost / k["cu_t"] if k["cu_t"] else 0.0,
            "co2_t": k["co2_t"],
            "fleet_avail": sum(t.avail for t in fleet) / len(fleet) * 100,
            "queue_min": k["queue_min_sum"] / k["queue_n"] if k["queue_n"] else 0.0,
            "inband_pct": k["inband_s"] / k["feed_s"] * 100 if k["feed_s"] else 0.0,
            "failures": k["failures"],
            "cas_alerts": k["cas_alerts"],
            "pq_ok_pct": k.get("pq_ok", 0) / k["pq_n"] * 100 if k.get("pq_n") else 100.0,
            **self.outlook(k),
        }

    def reseed(self, seed):
        self.rng = random.Random(seed)
        for a in list(self.trucks) + list(self.loaders.values()) + list(self.drills):
            a.rng = random.Random(f"{a.id}-{seed}")

    def reset_kpis(self):
        self.kpi = collections.defaultdict(float)
