#!/usr/bin/env python3
"""Convert the energy-consumption workbook of a mining and processing plant
(Zenodo 20647907, CC BY-SA 4.0) to the CSV the twin and the ML model use.

    python3 bozshakol/ml/prepare_energy.py      # needs openpyxl, pandas

Input:  data/energy-gok/EnergyConsumptionData.xlsx — half-hour active (kW·h)
        and reactive (kvar·h) energy per feeder and per main substation
        (GPP-1 ... GPP-5), January and June 2019.
Output: data/energy-gok/energy_30min.csv — one row per half hour: total
        active power P_MW and reactive power Q_Mvar of the whole plant (sum
        of the five substation TOTAL points) and P of each substation.
        Energy per half hour E becomes average power as E * 2 / 1000.
"""

import os
import re
import sys

import openpyxl
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "energy-gok", "EnergyConsumptionData.xlsx")
OUT = os.path.join(ROOT, "data", "energy-gok", "energy_30min.csv")


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    recs = []
    for ws in wb.worksheets:
        month = 6 if "JUNE" in ws.title.upper() else 1
        point = qty = days = None
        for r in ws.iter_rows(values_only=True):
            c0 = r[0]
            if isinstance(c0, str) and c0.startswith("Point"):
                point = re.sub(r"\s+", " ", c0.split(":", 1)[1].strip())
                continue
            if isinstance(c0, str) and "Power" in c0:
                qty = "P" if c0.startswith("Active") else "Q"
                continue
            if c0 is None and r[1] == "1":
                days = [int(x) for x in r[1:] if x not in (None, "")]
                continue
            if isinstance(c0, str) and re.match(r"\d\d:\d\d", c0) and days and point and "TOTAL" in point:
                hh, mm = map(int, c0.split(":"))
                gpp = re.match(r"GPP-(\d)", point).group(1)
                for d, v in zip(days, r[1:]):
                    if v not in (None, ""):
                        recs.append((month, d, hh * 60 + mm - 30, gpp, qty, float(v)))
    df = pd.DataFrame(recs, columns=["month", "day", "minute", "gpp", "qty", "kwh"])
    df["mw"] = df["kwh"] * 2 / 1000
    wide = df.pivot_table(index=["month", "day", "minute"], columns=["qty", "gpp"], values="mw", aggfunc="sum")
    out = pd.DataFrame(index=wide.index)
    out["P_MW"] = wide["P"].sum(axis=1)
    out["Q_Mvar"] = wide["Q"].sum(axis=1)
    for g in sorted(wide["P"].columns):
        out[f"P_GPP{g}_MW"] = wide["P"][g]
    out = out.reset_index().sort_values(["month", "day", "minute"])
    out["date"] = pd.to_datetime(dict(year=2019, month=out["month"], day=out["day"])).dt.strftime("%Y-%m-%d")
    out["time"] = out["minute"].map(lambda m: f"{m // 60:02d}:{m % 60:02d}")
    out = out[["date", "time", "month", "day", "minute", "P_MW", "Q_Mvar"] + [c for c in out.columns if c.startswith("P_GPP")]]
    out.round(3).to_csv(OUT, index=False)
    print(f"{len(out)} half hours -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
