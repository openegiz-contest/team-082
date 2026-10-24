"""
Spatial model of the Central and East pits, its haul-road network and the surface
facilities. Shared by the simulator (routing, grades, distances) and by the
3D control room (the layout is stored in the site twin's attributes).
"""

import bisect
import heapq
import math

from . import params as P

# Surface facilities: x, y, z in metres (local grid, pit centre at 0,0).
FACILITIES = {
    "crusher": (1750.0, -250.0, 8.0),
    "lg": (1720.0, -980.0, 6.0),
    "dump": (650.0, 1420.0, 30.0),
    "fuel": (1560.0, 560.0, 0.0),
    "workshop": (1780.0, 720.0, 0.0),
    "clay_plant": (2300.0, 330.0, 6.0),
    "cos": (3750.0, -600.0, 0.0),
    "sag": (4060.0, -600.0, 0.0),
    "bm-01": (4060.0, -520.0, 0.0),
    "bm-02": (4060.0, -680.0, 0.0),
    "flot_r": (4320.0, -560.0, 0.0),
    "flot_c": (4320.0, -680.0, 0.0),
    "th_c": (4540.0, -420.0, 0.0),
    "th_t": (4540.0, -780.0, 0.0),
    "tsf": (4400.0, -1750.0, 0.0),
    "substation": (3500.0, 120.0, 0.0),
    "water": (4900.0, 250.0, 0.0),
    "camp": (2600.0, 1300.0, 0.0),
    "radar": (-300.0, 900.0, 0.0),
    "weather": (2000.0, 900.0, 0.0),
    "dm-01": (300.0, -200.0, -210.0),     # on the floor of the Central pit (14 benches x 15 m)
    "dm-02": (1900.0, -120.0, 0.0),
    "dm-03": (2550.0, 1150.0, 0.0),
    "qc": (4200.0, -440.0, 0.0),
    "lab": (3930.0, -330.0, 0.0),
    "pq": (3560.0, 60.0, 0.0),
    "seis": (-680.0, 1020.0, 0.0),
    "mwd": (-980.0, -640.0, 0.0),
    "en": (3420.0, 230.0, 0.0),
    # East waste dump (EWD, S13 table 1.4); position is a model assumption (A).
    "dump_e": (3550.0, -1300.0, 20.0),
}

# Ramp prefixes and exit angles per pit. The Central ramp starts on the east
# rim; the East ramp on its north-west rim, facing the crusher.
PIT_KEYS = {"central": dict(node="b", edge="ramp", road="road-ramp", theta0=0.0),
            "east": dict(node="e", edge="eramp", road="road-ramp-east", theta0=2.3)}


def pit_of_node(name):
    return "east" if name.startswith("e") and name[1:].isdigit() else "central"


def bench_ellipse(k, inset=10.0, pit="central"):
    """Semi-axes of the road line on bench k (k=0 is the rim)."""
    g = P.PITS[pit]
    return g["a"] - P.BENCH_STEP * k - inset, g["b"] - P.BENCH_STEP * k - inset


def pit_point(pit, a, b, theta):
    g = P.PITS[pit]
    return g["cx"] + a * math.cos(theta), g["cy"] + b * math.sin(theta)


def pit_at(x, y):
    """Which pit contains a plan position (None outside both)."""
    for key, g in P.PITS.items():
        if ((x - g["cx"]) / g["a"]) ** 2 + ((y - g["cy"]) / g["b"]) ** 2 <= 1.0:
            return key
    return None


def ellipse_point(a, b, theta):
    return a * math.cos(theta), b * math.sin(theta)


def _ellipse_ds_dtheta(a, b, theta):
    return math.hypot(a * math.sin(theta), b * math.cos(theta))


class Edge:
    def __init__(self, eid, a, b, pts, road, limit_kmh, rr):
        self.id = eid
        self.a = a
        self.b = b
        self.pts = [tuple(p) for p in pts]
        self.road = road
        self.limit = limit_kmh
        self.rr = rr
        self.cum = [0.0]
        for p, q in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(p, q))
        self.length = self.cum[-1]

    def point_at(self, d):
        return Polyline(self.pts).at(d)[:3]


class Polyline:
    """Points with cumulative distance; segment attributes ride along."""

    def __init__(self, pts, seg_info=None):
        self.pts = pts
        self.seg = seg_info or [None] * max(0, len(pts) - 1)
        self.cum = [0.0]
        for p, q in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(p, q))
        self.length = self.cum[-1]

    def at(self, d):
        """x, y, z, heading (deg, 0 = east, ccw), segment index, grade."""
        if len(self.pts) == 1:
            x, y, z = self.pts[0]
            return x, y, z, 0.0, 0, 0.0
        d = min(max(d, 0.0), self.length)
        i = max(0, min(bisect.bisect_right(self.cum, d) - 1, len(self.pts) - 2))
        p, q = self.pts[i], self.pts[i + 1]
        seg = self.cum[i + 1] - self.cum[i] or 1e-9
        t = (d - self.cum[i]) / seg
        x = p[0] + (q[0] - p[0]) * t
        y = p[1] + (q[1] - p[1]) * t
        z = p[2] + (q[2] - p[2]) * t
        horiz = math.hypot(q[0] - p[0], q[1] - p[1]) or 1e-9
        heading = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
        grade = (q[2] - p[2]) / horiz
        return x, y, z, heading, i, grade


class Network:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.adj = {}
        self.spur_slots = {}
        self._build()

    # -- construction -----------------------------------------------------
    def node(self, name, xyz):
        self.nodes[name] = tuple(xyz)
        self.adj.setdefault(name, [])

    def edge(self, eid, a, b, pts, road, limit, rr):
        e = Edge(eid, a, b, [self.nodes[a]] + list(pts) + [self.nodes[b]], road, limit, rr)
        self.edges[eid] = e
        self.adj[a].append((e, True))
        self.adj[b].append((e, False))
        return e

    def _ramp(self, pit):
        """Spiral ramp: descends counter-clockwise at RAMP_GRADE, one node per
        bench level."""
        g, kk = P.PITS[pit], PIT_KEYS[pit]
        ds = 25.0
        theta, s = kk["theta0"], 0.0
        ramp_pts = []
        bench_theta = {}
        while True:
            z = -P.RAMP_GRADE * s
            k = -z / P.BENCH_H
            a, b = bench_ellipse(k, pit=pit)
            x, y = pit_point(pit, a, b, theta)
            ramp_pts.append((x, y, z))
            if abs(k - round(k)) < 1e-6:
                bench_theta[int(round(k))] = theta
            if k >= g["n"] - 1e-6:
                break
            theta += ds / _ellipse_ds_dtheta(a, b, theta)
            s += ds
        self.ramp_thetas[pit] = bench_theta
        per = int(round(P.BENCH_H / P.RAMP_GRADE / ds))
        for k in range(g["n"] + 1):
            self.node(f"{kk['node']}{k}", ramp_pts[k * per])
        for k in range(1, g["n"] + 1):
            inner = ramp_pts[(k - 1) * per + 1:k * per]
            self.edge(f"{kk['edge']}-{k}", f"{kk['node']}{k - 1}", f"{kk['node']}{k}", inner, kk["road"],
                      P.LIMIT_RAMP_KMH, 0.025)

    def _build(self):
        self.ramp_thetas = {}
        for pit in P.PITS:
            self._ramp(pit)
        self.ramp_theta = self.ramp_thetas["central"]

        # Surface network.
        n = self.node
        n("J1", (1350.0, 0.0, 2.0))
        n("J2", (1250.0, -760.0, 0.0))
        n("J3", (1380.0, 420.0, 0.0))
        n("J4", (2000.0, -1050.0, 0.0))
        for f in ("crusher", "lg", "dump", "fuel", "workshop", "clay_plant", "dump_e"):
            n(f, FACILITIES[f])
        e = self.edge
        e("exit-j1", "b0", "J1", [(1220.0, 0.0, 1.0)], "road-main", P.LIMIT_HAUL_KMH, 0.020)
        e("j1-crusher", "J1", "crusher", [(1560.0, -110.0, 4.0)], "road-crusher", P.LIMIT_HAUL_KMH, 0.020)
        e("j1-j2", "J1", "J2", [(1330.0, -380.0, 1.0)], "road-bypass", P.LIMIT_HAUL_KMH, 0.022)
        e("j2-crusher", "J2", "crusher", [(1600.0, -700.0, 2.0), (1820.0, -480.0, 5.0)], "road-bypass", P.LIMIT_HAUL_KMH, 0.022)
        e("j2-lg", "J2", "lg", [(1480.0, -900.0, 3.0)], "road-lg", P.LIMIT_HAUL_KMH, 0.025)
        e("j1-j3", "J1", "J3", [(1380.0, 210.0, 1.0)], "road-main", P.LIMIT_HAUL_KMH, 0.020)
        e("j3-dump", "J3", "dump", [(1300.0, 820.0, 6.0), (1050.0, 1180.0, 16.0)], "road-dump",
          P.LIMIT_HAUL_KMH, 0.025)
        e("j3-fuel", "J3", "fuel", [], "road-service", 40.0, 0.022)
        e("fuel-ws", "fuel", "workshop", [], "road-service", 30.0, 0.022)
        e("j3-clay", "J3", "clay_plant", [(1800.0, 330.0, 2.0)], "road-clay", P.LIMIT_HAUL_KMH, 0.022)
        # East pit: exit to J4, then to the crusher, the low-grade stockpile
        # (and on to the Central pit via J2) and the East waste dump. (A)
        e("exit-e", "e0", "J4", [(2090.0, -1180.0, 1.0)], "road-east", P.LIMIT_HAUL_KMH, 0.020)
        e("j4-crusher", "J4", "crusher", [(1990.0, -700.0, 3.0), (1880.0, -420.0, 6.0)], "road-east",
          P.LIMIT_HAUL_KMH, 0.020)
        e("j4-j2", "J4", "J2", [(1600.0, -1000.0, 1.0)], "road-lg", P.LIMIT_HAUL_KMH, 0.022)
        # Reserve bays near each pit exit: trucks the dispatcher holds back wait
        # there instead of standing on the haul roads.
        n("park_c", (1250.0, 230.0, 0.0))
        n("park_e", (1880.0, -1150.0, 0.0))
        e("j1-park", "J1", "park_c", [(1320.0, 140.0, 0.0)], "road-service", 30.0, 0.025)
        e("j4-park", "J4", "park_e", [], "road-service", 30.0, 0.025)
        e("j4-dump-e", "J4", "dump_e", [(2500.0, -1110.0, 2.0), (3100.0, -1150.0, 8.0)], "road-dump-east",
          P.LIMIT_HAUL_KMH, 0.025)

        # Face spurs: flat, along the bench, away from the ramp. Blocks and
        # loaders sit at distances along them.
        for ld in P.LOADERS:
            pit = ld.get("pit", "central")
            k = ld["bench"]
            th0 = self.ramp_thetas[pit][k]
            a, b = bench_ellipse(k, inset=14.0, pit=pit)
            # Faces shorter than ~40 % of the bench perimeter.
            per = 2 * math.pi * math.sqrt((a * a + b * b) / 2)
            target = min(780.0, 0.4 * per)
            pts, th, length = [], th0, 0.0
            while length < target:
                th -= 20.0 / _ellipse_ds_dtheta(a, b, th)
                length += 20.0
                x, y = pit_point(pit, a, b, th)
                pts.append((x, y, -P.BENCH_H * k))
            end = f"end-{ld['id']}"
            n(end, pts[-1])
            e(f"spur-{ld['id']}", f"{PIT_KEYS[pit]['node']}{k}", end, pts[:-1], "road-faces", P.LIMIT_FACE_KMH, 0.035)

    # -- routing -------------------------------------------------------------
    def shortest(self, src, dst, closed=(), restricted=()):
        """Node path as a list of (edge, forward)."""
        if src == dst:
            return []
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist.get(u, math.inf):
                continue
            for e, fwd in self.adj[u]:
                if e.road in closed or e.id in closed:
                    continue
                v = e.b if fwd else e.a
                cost = e.length / e.limit * (2.5 if (e.road in restricted or e.id in restricted) else 1.0)
                nd = d + cost
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = (u, e, fwd)
                    heapq.heappush(pq, (nd, v))
        if dst not in prev:
            return None
        path, v = [], dst
        while v != src:
            u, e, fwd = prev[v]
            path.append((e, fwd))
            v = u
        return list(reversed(path))

    def route(self, src, dst, closed=(), restricted=()):
        """Polyline between two locations. A location is a node name or
        (spur edge id, distance along it). Returns None if unreachable."""
        pts, segs = [], []

        def add(points, edge):
            for p in points:
                if pts and math.dist(pts[-1], p) < 1e-6:
                    continue
                if pts:
                    segs.append(edge)
                pts.append(p)

        def cut(edge, d, from_start):
            out = []
            for p, c in zip(edge.pts, edge.cum):
                if c < d:
                    out.append(p)
            out.append(edge.point_at(d))
            return out if from_start else list(reversed(out))

        s_node = src
        if isinstance(src, tuple):
            e = self.edges[src[0]]
            add(cut(e, src[1], from_start=False), e)
            s_node = e.a
        d_node, tail = dst, None
        if isinstance(dst, tuple):
            e = self.edges[dst[0]]
            d_node = e.a
            tail = (e, cut(e, dst[1], from_start=True))
        if isinstance(src, tuple) and isinstance(dst, tuple) and src[0] == dst[0]:
            e = self.edges[src[0]]
            a, b = src[1], dst[1]
            pts = [e.point_at(a), e.point_at(b)]
            return Polyline(pts, [e])
        path = self.shortest(s_node, d_node, closed, restricted)
        if path is None:
            return None
        if not pts:
            add([self.nodes[s_node]], None)
        for e, fwd in path:
            add(e.pts if fwd else list(reversed(e.pts)), e)
        if tail:
            add(tail[1], tail[0])
        if len(pts) == 1:
            pts.append(pts[0])
            segs.append(None)
        return Polyline(pts, segs)

    # -- export for the UI -----------------------------------------------------
    def layout(self):
        r = lambda v: round(v, 1)  # noqa: E731
        return {
            "pit": {"a": P.PIT_A, "b": P.PIT_B, "bench_h": P.BENCH_H, "n": P.N_BENCHES,
                    "step": P.BENCH_STEP, "ramp_width": P.RAMP_WIDTH},
            "pits": {k: {"name": g["name"], "cx": g["cx"], "cy": g["cy"], "a": g["a"], "b": g["b"], "n": g["n"]}
                     for k, g in P.PITS.items()},
            "edges": [{"id": e.id, "road": e.road, "pts": [[r(x), r(y), r(z)] for x, y, z in e.pts]}
                      for e in self.edges.values()],
            "facilities": {k: [r(c) for c in v] for k, v in FACILITIES.items()},
        }
