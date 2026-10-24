#!/usr/bin/env python3
"""Prepare the committed subset of the Kaggle flotation dataset.

The original file (MiningProcess_Flotation_Plant_Database.csv, 184 MB, CC0)
is sampled every 20 s with hourly laboratory assays. This script averages it
to one row per hour (about 4 100 rows, ~0.5 MB) — the form the twin and the
ML model use — and writes data/flotation-plant/flotation_hourly.csv.

    python3 bozshakol/ml/prepare.py /path/to/MiningProcess_Flotation_Plant_Database.csv

Development tool (pandas). The output is committed, so the stand never needs
the original download.
"""

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "flotation-plant", "flotation_hourly.csv")

RENAME = {
    "% Iron Feed": "iron_feed", "% Silica Feed": "silica_feed", "Starch Flow": "starch_flow",
    "Amina Flow": "amina_flow", "Ore Pulp Flow": "pulp_flow", "Ore Pulp pH": "pulp_ph",
    "Ore Pulp Density": "pulp_density", "% Iron Concentrate": "iron_conc", "% Silica Concentrate": "silica_conc",
}


def main(src):
    df = pd.read_csv(src, decimal=",", parse_dates=["date"])
    df = df.rename(columns=RENAME)
    for i in range(1, 8):
        df = df.rename(columns={f"Flotation Column 0{i} Air Flow": f"air_{i}", f"Flotation Column 0{i} Level": f"level_{i}"})
    hourly = df.groupby("date").mean().reset_index()
    hourly = hourly.sort_values("date")
    hourly.insert(0, "hour", hourly["date"].dt.strftime("%Y-%m-%d %H:00"))
    hourly = hourly.drop(columns=["date"]).round(4)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    hourly.to_csv(OUT, index=False)
    print(f"{len(df)} rows -> {len(hourly)} hourly rows: {OUT}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
