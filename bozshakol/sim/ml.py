"""Pure-Python inference of the models trained by ml/train.py.

The stand needs no ML libraries: gradient-boosted trees, ridge models and the
GeoMet block-model grid are stored as JSON in bozshakol/ml/models/ and are
evaluated here with the standard library only.
"""

import json
import math
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.environ.get("ML_MODELS_DIR", os.path.join(ROOT, "ml", "models"))
_cache = {}


def load(name):
    if name not in _cache:
        with open(os.path.join(MODELS, f"{name}.json"), encoding="utf-8") as fh:
            _cache[name] = json.load(fh)
    return _cache[name]


def available(name):
    return os.path.exists(os.path.join(MODELS, f"{name}.json"))


def _tree(t, x):
    i = 0
    left, right, feat, thr, val = t["l"], t["r"], t["f"], t["t"], t["v"]
    while left[i] != -1:
        i = left[i] if x[feat[i]] <= thr[i] else right[i]
    return val[i]


def _f32(v):
    """scikit-learn trees compare float32 features: round the same way."""
    return struct.unpack("f", struct.pack("f", v))[0]


def gbm(model, row):
    """row: dict feature -> value. Regression value or binary probability."""
    x = [float(row[f]) for f in model["features"]]
    if model.get("f32"):
        x = [_f32(v) for v in x]
    raw = model["base"] + model["lr"] * sum(_tree(t, x) for t in model["trees"])
    if model["kind"] == "binary":
        return 1.0 / (1.0 + math.exp(-raw))
    return raw


def gbm_proba(model, row):
    """Multiclass GBM: class probabilities (softmax over per-class raw scores)."""
    x = [float(row[f]) for f in model["features"]]
    raw = [b + model["lr"] * sum(_tree(t, x) for t in trees) for b, trees in zip(model["base"], model["trees"])]
    mx = max(raw)
    e = [math.exp(v - mx) for v in raw]
    s = sum(e)
    return [v / s for v in e]


def linear(model, values):
    return model["intercept"] + sum(c * v for c, v in zip(model["coef"], values))


class Grid:
    """Trilinear lookup in the pre-computed GeoMet block-model grid."""

    def __init__(self, obj):
        self.x, self.y, self.z = obj["x"], obj["y"], obj["z"]
        self.vars = obj["vars"]
        self.values = obj["values"]
        self.means = obj["means"]
        self.ny, self.nz = len(self.y), len(self.z)

    @staticmethod
    def _locate(axis, v):
        step = axis[1] - axis[0]
        f = (v - axis[0]) / step
        f = min(max(f, 0.0), len(axis) - 1.000001)
        i = int(f)
        return i, f - i

    def at(self, x, y, z):
        ix, fx = self._locate(self.x, x)
        iy, fy = self._locate(self.y, y)
        iz, fz = self._locate(self.z, z)
        out = {}
        for var in self.vars:
            vals = self.values[var]
            acc = 0.0
            for dx, wx in ((0, 1 - fx), (1, fx)):
                for dy, wy in ((0, 1 - fy), (1, fy)):
                    for dz, wz in ((0, 1 - fz), (1, fz)):
                        w = wx * wy * wz
                        if w:
                            acc += w * vals[((ix + dx) * self.ny + iy + dy) * self.nz + iz + dz]
            out[var] = acc
        return out


_geo = {}


def geomet():
    """(grid, hardness model, normalisers) or None when the models are absent."""
    if "g" not in _geo:
        if not (available("geomet_grid") and available("geomet_hardness")):
            _geo["g"] = None
        else:
            grid = Grid(load("geomet_grid"))
            hard = load("geomet_hardness")
            _geo["g"] = (grid, hard)
    return _geo["g"]


ASSAYS = ["Cu ppm", "Fe ppm", "S ppm", "Al ppm", "K ppm", "Ca ppm", "Mg ppm"]
# Ca and Mg are not interpolated in space; their median from the comminution
# samples is used, so the hardness model sees the same feature set.
CA_MG_MEDIAN = {"Ca ppm": 6764.0, "Mg ppm": 11263.0}


def hardness_index(assay):
    """Predicted breakage index t (th3, higher = softer) from block assays."""
    g = geomet()
    if g is None:
        return None
    _, hard = g
    vals = [math.log(max(1.0, assay.get(a, CA_MG_MEDIAN.get(a, 1.0)))) for a in ASSAYS]
    return linear(hard, vals)
