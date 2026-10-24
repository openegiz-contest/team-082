"""Real open data replayed through the twin, with live ML inference.

Two twins stream real records through the platform (MQTT -> Ditto ->
InfluxDB), advancing with the model clock, and show what the ML model says
about each record next to the truth:

  qc-01  flotation quality analyser — one hour of a real flotation plant per
         model hour (Kaggle "Quality Prediction in a Mining Process", CC0).
         The soft sensor estimates % SiO2 in the concentrate *now*; the lab
         assay arrives 3 h later, as at a real plant.
  sm-01  seismic monitoring station — one real shift record per model shift
         (UCI "seismic-bumps", CC BY 4.0); the classifier gives the
         probability of a hazardous next shift.

  mwd-01 MWD rock-type classifier — one real blasting round per model hour
         (NGI, 15 Norwegian tunnels, Zenodo 10358374, CC BY 4.0): the
         drilling statistics go through a multiclass GBM, and the predicted
         rock is shown next to the geologist's mapping of the same round.

  en-01  energy profile of a mining and processing plant — one real half hour
         per model half hour (Zenodo 20647907, CC BY-SA 4.0): total active and
         reactive power and the GBM forecast of the load 2 h ahead.

Only the hold-out part of each dataset (the last 20 %, never seen in
training) is replayed, so the errors shown on the stand are honest.
"""

import collections
import csv
import datetime
import os

from . import ml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("DATA_DIR", os.path.join(ROOT, "data"))
_tables = {}


def _flotation_table():
    if "flot" not in _tables:
        path = os.path.join(DATA, "flotation-plant", "flotation_hourly.csv")
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    rows.append({k: (v if k == "hour" else float(v)) for k, v in r.items()})
        _tables["flot"] = rows
    return _tables["flot"]


def _seismic_table():
    if "seis" not in _tables:
        path = os.path.join(DATA, "seismic-bumps", "seismic-bumps.arff")
        rows, cols, data = [], [], False
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.lower().startswith("@attribute"):
                        cols.append(line.split()[1])
                    elif line.lower().startswith("@data"):
                        data = True
                    elif data and line and not line.startswith("%"):
                        rows.append(dict(zip(cols, line.split(","))))
        _tables["seis"] = rows
    return _tables["seis"]


def _mwd_table():
    if "mwd" not in _tables:
        path = os.path.join(DATA, "mwd-rocktype", "mwd_rocktype_blastholes_model_ready_full.csv")
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    rows.append(r)
            rows.sort(key=lambda r: (r["Tunnel"], float(r["PegStart"])))
        _tables["mwd"] = rows
    return _tables["mwd"]


def _energy_table():
    if "en" not in _tables:
        path = os.path.join(DATA, "energy-gok", "energy_30min.csv")
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    rows.append({k: (v if k in ("date", "time") else float(v)) for k, v in r.items()})
        _tables["en"] = rows
    return _tables["en"]


ROCK_RU = {
    "Granittic_gneiss": "гранитный гнейс", "Drammensgranite": "гранит (Драммен)", "Rhomb_porphyry": "ромб-порфир",
    "Amphibolittic_gneiss": "амфиболитовый гнейс", "Blackshale": "чёрный сланец", "Elnes_lime_shale": "известковистый сланец",
    "Huk_limestone": "известняк", "Hagaberg_shale": "глинистый сланец", "Hornfels": "роговик", "Augen_gneiss": "очковый гнейс",
}

PROC = ["iron_feed", "silica_feed", "starch_flow", "amina_flow", "pulp_flow", "pulp_ph", "pulp_density"] + \
    [f"air_{i}" for i in range(1, 8)] + [f"level_{i}" for i in range(1, 8)]
LEVEL_RU = {"a": "нет опасности", "b": "низкая", "c": "высокая", "d": "опасно"}
CAT = {"a": 0, "b": 1, "c": 2, "d": 3}


def _safe(loader):
    """Load a dataset table; an unreadable file disables its twin instead of stopping the model."""
    try:
        return loader()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("dataset unavailable (%s): %r", loader.__name__, exc)
        return []


class RealData:
    """Small state only (indices, rolling errors): Mine is deep-copied by the forecaster."""

    def __init__(self):
        self.ok_flot = ml.available("flotation_silica") and bool(_safe(_flotation_table))
        self.ok_seis = ml.available("seismic_hazard") and bool(_safe(_seismic_table))
        self.flot_i = None
        self.flot_err = collections.deque(maxlen=24)
        self.flot_last = {}
        self.seis_i = None
        self.seis_last = {}
        self.seis_hits = collections.deque(maxlen=30)
        self.ok_mwd = ml.available("mwd_rocktype") and bool(_safe(_mwd_table))
        self.mwd_order = None
        self.mwd_i = None
        self.mwd_last = {}
        self.mwd_hits = collections.deque(maxlen=48)
        self.ok_en = ml.available("energy_load") and bool(_safe(_energy_table))
        self.en_order = None
        self.en_i = None
        self.en_last = {}
        self.en_err = collections.deque(maxlen=48)
        self.en_err_now = collections.deque(maxlen=48)

    # -- flotation -----------------------------------------------------------------
    def _flot_row(self, i):
        rows = _flotation_table()
        m = ml.load("flotation_silica")
        d = m["lab_delay_h"]
        r, prev = rows[i], rows[i - 1]
        x = {c: r[c] for c in PROC}
        for c in PROC:
            x[c + "_d"] = r[c] - prev[c]
        x["silica_lab"] = rows[i - d]["silica_conc"]
        x["iron_lab"] = rows[i - d]["iron_conc"]
        x["silica_lab_m3"] = sum(rows[i - d - k]["silica_conc"] for k in range(3)) / 3
        return r, x, ml.gbm(m, x)

    def _flot_step(self, hours, log):
        rows = _flotation_table()
        m = ml.load("flotation_silica")
        start = m["metrics"]["train"] + 6          # first hour of the hold-out part
        span = len(rows) - start
        i = start + hours % span
        if i == self.flot_i:
            return
        self.flot_i = i
        r, x, pred = self._flot_row(i)
        err = pred - r["silica_conc"]
        self.flot_err.append(abs(err))
        self.flot_last = dict(row=r, x=x, pred=pred, err=err)
        if pred > 3.5 and log:
            log("warn", f"Анализатор QC-01 (реальные данные): ML-оценка SiO₂ в концентрате {pred:.2f} % — выше нормы 3,5 %, "
                        f"лабораторный анализ придёт через {m['lab_delay_h']} ч", "qc-01")

    # -- seismic --------------------------------------------------------------------
    def _seis_step(self, shifts, log):
        rows = _seismic_table()
        m = ml.load("seismic_hazard")
        start = int(len(rows) * 0.8)
        i = start + shifts % (len(rows) - start)
        if i == self.seis_i:
            return
        self.seis_i = i
        r = rows[i]
        x = {k: (CAT[v] if k in ("seismic", "seismoacoustic", "ghazard") else (1 if v == "N" else 0) if k == "shift"
                 else float(v)) for k, v in r.items() if k != "class"}
        p = ml.gbm(m, x)
        alarm = p >= m["metrics"]["threshold"]
        actual = r["class"] == "1"
        self.seis_hits.append((alarm, actual))
        self.seis_last = dict(row=r, p=p, alarm=alarm, actual=actual)
        if alarm and log:
            log("warn", f"Сейсмостанция SM-01 (реальные данные): ML-вероятность опасной следующей смены {p * 100:.0f} % "
                        f"(экспертная оценка: {LEVEL_RU[r['ghazard']]})", "sm-01")

    # -- MWD rock type ---------------------------------------------------------------
    def _mwd_step(self, rounds):
        rows = _mwd_table()
        m = ml.load("mwd_rocktype")
        if self.mwd_order is None:
            # hold-out rounds only: the last 25 % of each tunnel by chainage
            self.mwd_order = [i for i, r in enumerate(rows) if float(r["PegStart"]) >= m["test_from"][r["Tunnel"]]]
        k = rounds % len(self.mwd_order)
        i = self.mwd_order[k]
        if i == self.mwd_i:
            return
        self.mwd_i = i
        r = rows[i]
        p = ml.gbm_proba(m, {f: float(r[f]) for f in m["features"]})
        best = max(range(len(p)), key=p.__getitem__)
        rock = m["classes"][best]
        prev = rows[i - 1]["Rock"] if i > 0 and rows[i - 1]["Tunnel"] == r["Tunnel"] else None
        self.mwd_hits.append(rock == r["Rock"])
        self.mwd_last = dict(row=r, rock=rock, p=p[best], prev=prev, k=k)

    # -- energy profile --------------------------------------------------------------
    def _en_features(self, i, m):
        rows = _energy_table()
        H = m["horizon"]
        x = {f"lag{lag}": rows[i - lag]["P_MW"] for lag in m["lags"]}
        x["day_ago"] = rows[i + H - 48]["P_MW"]
        x["tod"] = ((rows[i]["minute"] + 30 * H) % 1440) / 60
        y, mo, d = (int(v) for v in rows[i]["date"].split("-"))
        x["dow"] = datetime.date(y, mo, d).weekday()
        return x

    def _en_step(self, halves):
        rows = _energy_table()
        m = ml.load("energy_load")
        H = m["horizon"]
        if self.en_order is None:
            # hold-out: the last 25 % of each month with a full history and a known target
            order = []
            for mo in sorted({r["month"] for r in rows}):
                idx = [i for i, r in enumerate(rows) if r["month"] == mo]
                ok = [i for i in idx if i - 48 >= idx[0] and i + H <= idx[-1]]
                order += ok[int(len(ok) * 0.75):]
            self.en_order = order
        i = self.en_order[halves % len(self.en_order)]
        if i == self.en_i:
            return
        self.en_i = i
        r = rows[i]
        pred = ml.gbm(m, self._en_features(i, m))
        actual = rows[i + H]["P_MW"]
        self.en_err.append(abs(pred - actual))
        self.en_err_now.append(abs(r["P_MW"] - actual))
        self.en_last = dict(row=r, pred=pred, actual=actual, target_time=rows[i + H]["time"])

    def update(self, t_s, log=None):
        # A missing or unreadable dataset switches its twin off; it must never stop the mine model.
        try:
            self._update(t_s, log)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("real-data replay disabled: %r", exc)
            self.ok_flot = self.ok_seis = self.ok_mwd = self.ok_en = False

    def _update(self, t_s, log=None):
        if self.ok_en:
            self._en_step(int(t_s // 1800))
        if self.ok_mwd:
            self._mwd_step(int(t_s // 3600))
        if self.ok_flot:
            self._flot_step(int(t_s // 3600), log)
        if self.ok_seis:
            self._seis_step(int(t_s // (12 * 3600)), log)
