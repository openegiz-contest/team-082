#!/usr/bin/env python3
"""
Ultimate pit and nested pit shells by the Lerchs-Grossmann method.

    python3 bozshakol/tools/pit_optimize.py      # needs numpy and scipy

The Lerchs-Grossmann problem — which blocks to mine so that the total value
is the largest while every mined block has its overlying cone mined too — is
the maximum-closure problem of a directed graph. It is solved here exactly as
a minimum cut (Picard, 1976), the formulation used by the pseudoflow solvers of
modern pit optimisers: source -> block with the block value if positive,
block -> sink with minus the value if negative, block -> each block of its
slope cone with infinite capacity. The source side of the minimum cut is the
optimal pit.

Block model (honest status): a regular grid of 30 x 30 x 30 m blocks over each
pit. Cu and Au come from the GeoMet drill-hole field (Zenodo 7051975, another
porphyry deposit, see ml/README.md), re-levelled to the Bozshakol reserve
grade 0.38 % Cu (S14). The East pit samples the same field shifted and scaled
to its footprint. It is a synthetic block model: the shells show how the
method works on the twin's data, not the real Bozshakol pit design.

Nested shells: the same problem with the copper price multiplied by revenue
factors 0.35 ... 1.0. Small factors give the high-margin core (first stages),
1.0 gives the ultimate pit.

Output: data/pit-shells/pit_shells.json — per pit: block size, economics,
for every shell its tonnes, grade, strip ratio, value, bench outlines
(crest polygons per level) for the 3D control room, and what is left to mine
outside the current pit.
"""

import json
import math
import os
import sys
import time

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import breadth_first_order, maximum_flow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim import ml as ML  # noqa: E402
from sim import params as P  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data", "pit-shells")
OUT = os.path.join(OUT_DIR, "pit_shells.json")

B = 30.0                         # block edge, m (two 15 m benches)
RHO = 2.68                       # t/m3, as the model's ore (A)
BLOCK_T = B ** 3 * RHO
GRADE_MEAN = 0.38                # % Cu, Bozshakol reserves (S14)
AU_MEAN = 0.20                   # g/t (S1: 0.22 g/t in the 2023 feed)
GRADE_EXP = 1.0                  # drill-hole composite variability kept: low-grade pockets become internal waste (A)
REC_CU = 0.79                    # S1 2023
REC_AU = 0.54                    # S1 2023
MINE_KZT_T = 900.0               # mining cost per tonne moved (A, ~1.8 USD/t)
PROC_KZT_T = 4400.0              # processing + G&A per tonne of ore (A): break-even grade = CUTOFF_LG 0.13 %
SLOPE_DEG = 42.0                 # overall slope angle (A)
REVENUE_FACTORS = [0.35, 0.45, 0.55, 0.7, 0.85, 1.0]

DOMAINS = {
    # Licence area of the optimisation (A): a box around each pit, depth from S13
    # (Central pit 270 m deep by 2040) and an assumed 150 m for the East pit.
    "central": dict(x0=-1710.0, x1=1710.0, y0=-1140.0, y1=1140.0, depth=270.0),
    "east": dict(x0=-1020.0, x1=1020.0, y0=-690.0, y1=690.0, depth=150.0),
}
# Mineralised envelope (A): the GeoMet field is mineralised everywhere, a
# porphyry orebody is not. Grades fade outside an elliptic cone around the pit
# axis (semi-axes as fractions of the pit rim, widening with depth by `flare`),
# so the pit has to strip barren wall rock. One shape for both pits, tuned only
# so the two ultimate pits together have a strip ratio near the life-of-mine
# 0.7 t/t (S2) and the ore in them near the measured + indicated resources
# 936 Mt (S14); the split between the pits is what the optimisation gives.
ENVELOPE = {"central": dict(rx=0.7, ry=0.45, flare=0.8, edge=0.10),
            "east": dict(rx=0.7, ry=0.45, flare=0.8, edge=0.10)}


def block_model(pit):
    g = P.PITS[pit]
    d = DOMAINS[pit]
    grid = ML.geomet()[0]
    xs = np.arange(d["x0"] + B / 2, d["x1"], B)
    ys = np.arange(d["y0"] + B / 2, d["y1"], B)
    nz = int(round(d["depth"] / B))
    zs = -B / 2 - B * np.arange(nz)
    # GeoMet grid lies over the Central pit footprint; the East pit borrows it scaled.
    sx, sy = (1.0, 1.0) if pit == "central" else (1100.0 / g["a"], 650.0 / g["b"])
    cu = np.zeros((nz, len(ys), len(xs)))
    au = np.zeros_like(cu)
    for k, z in enumerate(zs):
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                s = grid.at(x * sx, y * sy, z * (210.0 / d["depth"] if pit == "east" else 1.0))
                cu[k, j, i] = s["Cu ppm"]
                au[k, j, i] = s["Au ppm"]
    e = ENVELOPE[pit]
    X, Y = np.meshgrid(xs, ys)
    env = np.zeros_like(cu)
    for k, z in enumerate(zs):
        grow = 1 + e["flare"] * (-z / d["depth"])
        dist = np.sqrt((X / (e["rx"] * g["a"] * grow)) ** 2 + (Y / (e["ry"] * g["b"] * grow)) ** 2)
        env[k] = 1 / (1 + np.exp((dist - 1) / e["edge"]))
    cu = cu ** GRADE_EXP
    au = np.maximum(au, 1e-3) ** GRADE_EXP
    inside = env > 0.5
    cu *= GRADE_MEAN / cu[inside].mean()
    au *= AU_MEAN / au[inside].mean()
    return xs + g["cx"], ys + g["cy"], zs, cu * env, au * env


def block_value(cu, au, rf):
    rev = (cu / 100 * REC_CU * P.CU_NET_KZT_T + au / 31.1035 * REC_AU * P.AU_NET_KZT_OZ) * rf
    ore = rev - PROC_KZT_T > 0
    v = np.where(ore, rev - PROC_KZT_T, 0.0) - MINE_KZT_T
    return v * BLOCK_T, ore


def precedence(nz, ny, nx):
    """Arcs block -> block above that must be mined first. Alternating 1:5 and
    1:9 patterns per level approximate a cone; the reach per level follows
    the slope angle."""
    reach = B / math.tan(math.radians(SLOPE_DEG)) / B      # horizontal blocks per level
    idx = np.arange(nz * ny * nx).reshape(nz, ny, nx)
    src, dst = [], []
    for k in range(1, nz):
        pattern = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]
        if (k % 2 == 0) or reach > 1.15:
            pattern += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        for dj, di in pattern:
            a = idx[k, max(0, -dj):ny - max(0, dj), max(0, -di):nx - max(0, di)]
            b = idx[k - 1][max(0, dj):ny + min(0, dj), max(0, di):nx + min(0, di)]
            src.append(a.ravel())
            dst.append(b.ravel())
    return np.concatenate(src), np.concatenate(dst)


def max_closure(values, arcs):
    """Optimal pit as a boolean array over blocks (minimum cut)."""
    n = values.size
    s, t = n, n + 1
    unit = 1e5                                    # capacities in 0.1 M KZT (scipy needs int32)
    v = np.round(values.ravel() / unit).astype(np.int64)
    pos = np.nonzero(v > 0)[0]
    neg = np.nonzero(v < 0)[0]
    inf = int(min(2 ** 31 - 1, v[v > 0].sum() + 1))
    rows = np.concatenate([np.full(pos.size, s), neg, arcs[0]])
    cols = np.concatenate([pos, np.full(neg.size, t), arcs[1]])
    caps = np.concatenate([v[pos], -v[neg], np.full(arcs[0].size, inf)]).astype(np.int32)
    C = csr_matrix((caps, (rows, cols)), shape=(n + 2, n + 2))
    C.sum_duplicates()
    flow = maximum_flow(C, s, t, method="dinic").flow
    R = (C - flow).tocsr()
    R.data = np.where(R.data > 0, 1, 0)
    R.eliminate_zeros()
    reach = breadth_first_order(R, s, directed=True, return_predecessors=False)
    mask = np.zeros(n + 2, bool)
    mask[reach] = True
    return mask[:n]


def outline(mask2d, xs, ys):
    """Boundary loops of a 2D boolean grid as polygons (cell corners), with
    collinear points dropped."""
    ny, nx = mask2d.shape
    edges = {}
    for j in range(ny):
        for i in range(nx):
            if not mask2d[j, i]:
                continue
            for (a, b), (dj, di) in (((( i, j), (i + 1, j)), (-1, 0)), (((i + 1, j), (i + 1, j + 1)), (0, 1)),
                                     (((i + 1, j + 1), (i, j + 1)), (1, 0)), (((i, j + 1), (i, j)), (0, -1))):
                jj, ii = j + dj, i + di
                if 0 <= jj < ny and 0 <= ii < nx and mask2d[jj, ii]:
                    continue
                edges.setdefault(a, []).append(b)
    loops = []
    while edges:
        start = next(iter(edges))
        loop, cur = [start], start
        while True:
            nxt = edges[cur].pop()
            if not edges[cur]:
                del edges[cur]
            if nxt == start:
                break
            loop.append(nxt)
            cur = nxt
        pts = []
        m = len(loop)
        for q in range(m):
            p0, p1, p2 = loop[q - 1], loop[q], loop[(q + 1) % m]
            if (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0]) != 0:
                pts.append(p1)
        x0, y0 = xs[0] - B / 2, ys[0] - B / 2
        if len(pts) >= 4:
            loops.append([[round(x0 + i * B, 1), round(y0 + j * B, 1)] for i, j in pts])
    loops.sort(key=len, reverse=True)
    return loops


def current_pit(pit, xs, ys, zs):
    """Blocks inside the modelled pit today (benches of the twin's geometry)."""
    g = P.PITS[pit]
    X, Y = np.meshgrid(xs - g["cx"], ys - g["cy"])
    out = np.zeros((len(zs), len(ys), len(xs)), bool)
    for k, z in enumerate(zs):
        bench = -z / P.BENCH_H
        if bench > g["n"]:
            continue
        a, b = g["a"] - P.BENCH_STEP * bench, g["b"] - P.BENCH_STEP * bench
        out[k] = (X / a) ** 2 + (Y / b) ** 2 <= 1.0
    return out


def optimise(pit):
    t0 = time.time()
    xs, ys, zs, cu, au = block_model(pit)
    nz, ny, nx = cu.shape
    arcs = precedence(nz, ny, nx)
    now = current_pit(pit, xs, ys, zs)
    shells = []
    prev = None
    for rf in REVENUE_FACTORS:
        val, _ = block_value(cu, au, rf)
        mask = max_closure(val, arcs).reshape(cu.shape)
        if prev is not None:
            mask |= prev                    # nested by construction; guards against ties
        prev = mask
        val1, ore = block_value(cu, au, 1.0)
        ore_m, waste_m = mask & ore, mask & ~ore
        left = mask & ~now
        ore_l, waste_l = left & ore, left & ~ore
        shells.append({
            "revenue_factor": rf,
            "ore_mt": round(ore_m.sum() * BLOCK_T / 1e6, 1),
            "waste_mt": round(waste_m.sum() * BLOCK_T / 1e6, 1),
            "strip_t_t": round(waste_m.sum() / max(1, ore_m.sum()), 2),
            "cu_pct": round(float(cu[ore_m].mean()) if ore_m.any() else 0.0, 3),
            "value_bn_kzt": round(float(val1[mask].sum()) / 1e9, 1),
            "depth_m": round(float(-zs[np.nonzero(mask.any(axis=(1, 2)))[0].max()] + B / 2) if mask.any() else 0.0),
            "left_ore_mt": round(ore_l.sum() * BLOCK_T / 1e6, 1),
            "left_waste_mt": round(waste_l.sum() * BLOCK_T / 1e6, 1),
            "left_strip_t_t": round(waste_l.sum() / max(1, ore_l.sum()), 2),
            # bench outlines: every level of the ultimate pit, the surface only for the inner shells
            "levels": [{"z": round(float(zs[k] + B / 2), 1), "loops": outline(mask[k], xs, ys)}
                       for k in range(nz) if mask[k].any() and (rf == REVENUE_FACTORS[-1] or k == 0)],
        })
    val1, ore = block_value(cu, au, 1.0)
    return {
        "name": P.PITS[pit]["name"],
        "domain": DOMAINS[pit],
        "blocks": int(cu.size),
        "ore_blocks_pct": round(float(ore.mean() * 100), 1),
        "grade_p10_p90": [round(float(np.percentile(cu, 10)), 3), round(float(np.percentile(cu, 90)), 3)],
        "shells": shells,
        "calc_s": round(time.time() - t0, 1),
    }


def main():
    res = {
        "method": "Lerchs-Grossmann maximum closure, solved as a minimum cut (Picard 1976); nested shells by revenue factor",
        "status": "synthetic block model: GeoMet drill-hole field (Zenodo 7051975) re-levelled to 0.38 % Cu (S14)",
        "block_m": B, "block_t": round(BLOCK_T), "slope_deg": SLOPE_DEG,
        "economics": {"cu_net_kzt_t": P.CU_NET_KZT_T, "au_net_kzt_oz": P.AU_NET_KZT_OZ, "rec_cu": REC_CU,
                      "rec_au": REC_AU, "mine_kzt_t": MINE_KZT_T, "proc_kzt_t": PROC_KZT_T},
        "pits": {pit: optimise(pit) for pit in P.PITS},
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    for pit, r in res["pits"].items():
        print(f"{pit}: {r['blocks']} blocks, {r['calc_s']} s, ore blocks {r['ore_blocks_pct']} %")
        for s in r["shells"]:
            print(f"  rf {s['revenue_factor']:.2f}: ore {s['ore_mt']} Mt @ {s['cu_pct']} %, waste {s['waste_mt']} Mt, "
                  f"SR {s['strip_t_t']}, depth {s['depth_m']} m, value {s['value_bn_kzt']} bn KZT; "
                  f"left: ore {s['left_ore_mt']} Mt, SR {s['left_strip_t_t']}")
    print(f"-> {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
