"""
Parameters of the Bozshakol digital twin.

Every number is either taken from a public source (S-codes, listed in
SUBMISSION.md -> "Данные и допущения") or is an engineering assumption (A),
chosen from textbook ranges and calibrated so that the whole model reproduces
the published operating figures of Bozshakol (ore processed, feed grade,
copper recovery, copper in concentrate).

S1  KAZ Minerals production reports (kazminerals.com): calibration target is
    FY 2023 (Q4 2023 report) — 32,935 kt processed (90.2 kt/d), 0.42 % Cu,
    79.2 % Cu recovery, 109.5 kt Cu, 0.22 g/t Au, 53.8 % Au recovery. The
    quarters Q1 2023 - Q2 2024 (76.8-80.0 % recovery, 0.40-0.43 % Cu) are the
    validation range (SUBMISSION.md, section 7).
S2  KAZ Minerals, site visit presentation (01.06.2015): fleet (Sandvik D55SP,
    Hitachi EX3600, CAT 785C / 777D, CAT 993K), strip ratio 0.7, concentrate
    22 % Cu, gyratory crusher 25 Mtpa, SAG + 2 ball mills, clay plant 5 Mtpa.
S3  mining-technology.com, "Bozshakol Copper Project": 1.22 bn t at 0.36 % Cu,
    28 MW gearless SAG + two gearless ball mills, 220 kV supply from
    Ekibastuz GRES-1, water from the Satpayev canal.
S4  Caterpillar 785C, AEHQ5320-02: 136 t payload, 1,082 kW gross, 1,005 kW
    net, GMW 249,480 kg, 1,893 L tank, 78 m3 body. Empty 102 t is the rounded
    model mass (A), not GMW - payload.
S5  Caterpillar 777D, AEHQ5140-02 (12-00): 90.9 t payload, 746 kW gross,
    699 kW flywheel, GMW 161,000 kg, 1,137 L tank. Empty 70.0 t is a model
    assumption chosen so that empty + payload <= GMW (A).
S13 KAZ Minerals Bozshakol, «План горных работ месторождения Бозшаколь.
    Корректировка» — отчёт о возможных воздействиях (ТОО «ECO AIR», 2023):
    Central and East pits in 6 stages (p. 11), pit on 01.01.2023 (table 1.3),
    Central pit design on 01.01.2040 (table 4), volumes mined to 01.01.2023
    (table 2), dumps incl. North (CWD) and East (EWD) (table 1.4), drill and
    blast (pp. 16-18: D55SP, holes 0.2 m x 12 m, 6 m spacing, Fortis Extra
    70, >= 450 m exclusion), 365 days, 2 shifts x 11 h, plant water balance
    2016-2023 (table 4.1). Annual mining mass and overburden 2023-2040:
    statement of planned activity KZ37RYS00424177 (08.08.2023).
S14 KAZ Minerals Annual Report 2015, Ore Reserves (DMT, JORC, 31.12.2015):
    Bozshakol 573 Mt at 0.38 % Cu (Proved 118, Probable 455); resources
    M+I 936 Mt at 0.37 %, Inferred 284 Mt at 0.32 %.
S0  Equipment passports (manufacturer, model, variant, value, unit, link):
    sim/equipment.py and docs/equipment_passports.pdf (generated from it). Passports are
    static twin attributes; this file holds the simulator's configuration,
    which must stay consistent with them (tests: sim/equipment_check.py).
S6  Hitachi EX3600-6 spec (ritchiespecs): 21 m3 loading-shovel bucket,
    1,450 kW.
S7  Sandvik D55SP (geotechpedia): holes 172-254 mm, 17 m single pass,
    567-708 kW.
S8  Cunningham C.V.B. (1983, 2005) Kuz-Ram fragmentation model.
S9  Bond F.C. (1961) Crushing and grinding calculations (third theory).
S10 Caterpillar Performance Handbook: rolling resistance 2-4 % for
    maintained haul roads, retarder-limited speeds downhill.
"""

# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------
SIM_START = "2026-10-20T11:20:00+05:00"   # local time, Pavlodar region (UTC+5)
SHIFT_STARTS = (8, 20)                    # two shifts a day; 11 h working time each + breaks (S13)
BLAST_WINDOWS = (12.0, 17.0)              # daily blast windows, hours (A)
TARIFF = {                                # KZT/kWh, time-of-use zones (A)
    "night": (23, 7, 14.0),
    "day": (7, 17, 22.0),
    "peak": (17, 23, 36.0),
}
DIESEL_KZT_PER_L = 310.0                  # (A) retail diesel price level
EXPLOSIVE_KZT_PER_KG = 520.0              # (A) bulk emulsion, ~1 USD/kg
CAPACITY_KZT_PER_MW_DAY = 85000.0       # (A) capacity charge ~2.5 M KZT per MW-month
CU_NET_KZT_T = 4.3e6                    # (A) LME ~9,500 USD/t less TC/RC, 1 USD = 500 KZT
AU_NET_KZT_OZ = 1.4e6                   # (A) payable gold in concentrate
GRID_T_CO2_PER_MWH = 0.75                 # (A) coal-dominated KZ grid
DIESEL_KG_CO2_PER_L = 2.68                # IPCC default for diesel

# --------------------------------------------------------------------------
# Pit geometry (local metres, x east, y north, z relative to pit rim)
# --------------------------------------------------------------------------
PIT_A = 1100.0          # Central pit rim half-length (A; S13: worked pit 4,070 x 880 m on 01.01.2023,
PIT_B = 650.0           #   Central pit 6,767 x 1,496 m by 2040 — the model keeps a compact ellipse)

# Two pits (S13: «границы Центрального и Восточного карьеров разделены на 6 стадий»).
# The East pit geometry is a model assumption (A): the open documents give the
# deposit totals only. strip_t_t below is the fallback; with the pit shells file
# present it is the strip ratio of each pit's Lerchs-Grossmann ultimate pit.
PITS = {
    "central": dict(name="Центральный", cx=0.0, cy=0.0, a=1100.0, b=650.0, n=14,
                    strip_t_t=0.78, reserve_share=0.72, ore_share=0.70),
    "east": dict(name="Восточный", cx=2650.0, cy=-1600.0, a=620.0, b=360.0, n=6,
                 strip_t_t=0.50, reserve_share=0.28, ore_share=0.30),
}
# Design strip ratios from the Lerchs-Grossmann ultimate pits (tools/pit_optimize.py,
# synthetic block model; data/pit-shells/pit_shells.json). The constants above are
# the fallback when the file is absent.
PIT_SHELLS = None
try:
    import json as _json
    import os as _os
    with open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            "data", "pit-shells", "pit_shells.json")) as _f:
        PIT_SHELLS = _json.load(_f)
    for _k, _g in PITS.items():
        _g["strip_t_t"] = PIT_SHELLS["pits"][_k]["shells"][-1]["strip_t_t"]
        _g["strip_source"] = "Lerchs-Grossmann"
except (OSError, KeyError, ValueError):
    PIT_SHELLS = None
ORE_PLAN_KT_MONTH = 2740.0      # plant demand: 32,935 kt processed in 2023 / 12 (S1)
EXPOSED_MONTHS_START = {"central": 3.0, "east": 2.2}   # exposed (uncovered) ore at the model start, months of plan (A)
PLAN_HORIZON_MONTHS = 6
BENCH_H = 15.0          # bench height (A, typical for 21 m3 shovels)
N_BENCHES = 14          # 210 m deep (A)
BENCH_STEP = 17.0       # horizontal step per bench: face + berm (A, ~41 deg overall)
RAMP_GRADE = 0.10       # 10 % ramp (S10 typical)
RAMP_WIDTH = 30.0

# --------------------------------------------------------------------------
# Haul trucks
# --------------------------------------------------------------------------
TRUCK_MODELS = {
    "CAT 785C": dict(payload=136.0, empty=102.0, gmw=249.48, p_kw=1005.0, vmax=55.0, tank=1893.0, class_="785"),  # S4
    "CAT 777D": dict(payload=90.9, empty=70.0, gmw=161.0, p_kw=699.0, vmax=60.0, tank=1137.0, class_="777"),      # S5
}
N_785 = 20                     # (A) the fleet of both pits; S2 lists the models, not the counts
N_777 = 6
TRUCKS_EAST_777 = 2            # CAT 777D on the East pit waste with EX-01 (A); the rest serve the 993K on clay
TRUCKS_EAST_785 = 5            # CAT 785C working the East pit by default (A); the rest in the Central pit
TRUCK_EFFICIENCY = 0.82        # drivetrain efficiency (A)
BSFC_L_PER_KWH = 0.26          # 0.22 kg/kWh / 0.84 kg/L (A, Tier-1 diesel)
IDLE_L_PER_H = 18.0            # (A)
BOWSER_RESPONSE_S = 45 * 60.0  # field fuel bowser reaches a truck that ran dry (A)
BOWSER_L = 400.0               # it brings enough to reach the station (A)
REFUEL_BELOW = 0.20            # refuel when the tank is below 20 % (A)
REFUEL_S = 15 * 60             # haul trucks at a high-flow post, model not selected (A, S0 p.16)
WATER_TRUCK_M3 = 75.7          # CAT 777 (07) water tank 75,700 L (S0 p.6)
DUST_MIN_TEMP_C = -20.0        # TSI DustTrak 8543 with heater (S0 p.20)
SPOT_S = 40.0                  # spotting under the loader (A)
DUMP_S = 60.0                  # tipping (A)
RETARDER_KMH = 32.0            # loaded downhill speed on the ramp (S10)
LIMIT_FACE_KMH = 15.0
LIMIT_RAMP_KMH = 35.0
LIMIT_HAUL_KMH = 50.0

# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------
LOADERS = [
    # id, model, bucket m3, cycle s, fill, trucks, bench, area label, pit
    dict(id="sh-01", model="Hitachi EX3600-6", bucket=21.0, cycle=32.0, fill=0.90, serves="785",
         bench=10, area="Центральный, северный борт, гор. -150", material="ore", pit="central"),
    dict(id="sh-02", model="Hitachi EX3600-6", bucket=21.0, cycle=32.0, fill=0.90, serves="785",
         bench=13, area="Центральный, северо-запад, гор. -195 (богатая руда)", material="ore_hg", pit="central"),
    dict(id="sh-03", model="Hitachi EX3600-6", bucket=21.0, cycle=32.0, fill=0.92, serves="785",
         bench=4, area="Центральный, северо-восток, гор. -60 (вскрыша)", material="waste", pit="central"),
    dict(id="ld-01", model="CAT 993K", bucket=12.5, rated_t=27.2, cycle=40.0, fill=0.85, serves="777",
         bench=7, area="Центральный, глинистая зона, гор. -105", material="clay", pit="central"),
    dict(id="sh-04", model="Hitachi EX3600-6", bucket=21.0, cycle=32.0, fill=0.90, serves="785",
         bench=4, area="Восточный, гор. -60 (руда)", material="ore", pit="east"),
    # Hitachi EX870 is in the Bozshakol fleet (S2); bucket within the ZAXIS 870H range, cycle (A).
    dict(id="ex-01", model="Hitachi EX870", bucket=4.3, cycle=28.0, fill=0.90, serves="777",
         bench=1, area="Восточный, гор. -15 (вскрыша)", material="waste", pit="east"),
]
SWELL = 1.45                    # bank -> loose (A)

# --------------------------------------------------------------------------
# Drill and blast
# --------------------------------------------------------------------------
N_DRILLS = 4                   # (A) S13 lists Sandvik D55SP, DI550 and SmartROC D65 rigs
HOLE_D_M = 0.200               # S13 p.16: holes 0.2 m (D55SP range 172-254 mm, S0 p.5); 6 m spacing
SUBDRILL = 1.5
STEMMING = 5.5
EXPLOSIVE_DENSITY = 1.10       # bulk emulsion blend, g/cc (A)
EXPLOSIVE_RWS = 100.0          # relative weight strength vs ANFO (A)
DESIGN_PF = 0.62               # kg/m3, design powder factor (A, porphyry 0.5-0.9)
ROP_REF = 48.0                 # m/h at UCS 110 MPa (A, rotary 251 mm)
HOLE_MOVE_S = 4 * 60
CHARGE_HOLES_PER_H = 22.0      # MMU truck + crew (A)
BLAST_EXCLUSION_M = 450.0
BLAST_CLEAR_S = 25 * 60        # evacuation before the shot (A)
REENTRY_CO_PPM = 20.0          # re-entry threshold (A, ~ MAC 20 mg/m3)

# --------------------------------------------------------------------------
# Ore control and blending
# --------------------------------------------------------------------------
CUTOFF_MILL = 0.22             # % Cu, to the crusher (A)
CUTOFF_LG = 0.13               # % Cu, to the low-grade stockpile (A)
GRADE_TARGET = 0.42            # % Cu mill feed target (S1: FY 2023 0.42 %)
GRADE_BAND = 0.03
WASTE_RATE_TPH = 1900.0        # Central pit waste plan, t/h (A)
WASTE_RATE_EAST_TPH = 500.0    # East pit waste plan, t/h (A): keeps the East exposed ore at its design strip ratio
CLAY_RATE_TPH = 600.0          # clay plant 5 Mtpa (S2)

# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------
CRUSHER_TPH = 4600.0           # gyratory 60-89 nominal at x80 = 0.6 m (A, 25 Mtpa at ~62 % use, S2)
CRUSHER_POCKET_T = 700.0
CRUSHER_KW = 750.0
CONVEYOR_LEN_M = 2100.0
CONVEYOR_SPEED = 4.5           # m/s
CONVEYOR_TPH = 5200.0
CONVEYOR_KW = 2400.0
COS_LIVE_T = 45000.0           # coarse ore stockpile, live (A)
COS_TOTAL_T = 130000.0
SAG_MW = 28.0                  # S3
SAG_DRAW_MAX = 25.5            # (A) 91 % of installed
BM_MW = 22.0                   # S3 two gearless ball mills (ABB)
BM_DRAW = 13.0                 # (A) operating draw each (grind P80 ~150 um)
BOND_WI = 14.5                 # kWh/t, porphyry average (A)
P80_MAX = 230.0                # um, ball-mill circuit product limit (A)
FLOT_VOL_M3 = 2400.0           # rougher-scavenger: 8 x Metso TankCell e300 (S0 p.12; 8 cells is the author's choice)
FLOT_K0 = 0.20                 # 1/min (A)
R_INF = 0.89                   # max recoverable Cu (A, calibrated to S1 FY 2023: 79.2 %)
CONC_GRADE = 22.0              # % Cu (S2)
AU_RECOVERY = 0.52             # Au recovery at 76.5 % Cu recovery (calibrated to S1 FY 2023: 53.8 %)
CLAY_PLANT_TPH = 620.0         # S2: 5 Mtpa at ~92 % availability
CLAY_HOPPER_T = 320.0          # clay plant receiving hopper (A)
CLAY_PLANT_MW = 9.0
FLOT_MW = 4.5
PUMPS_MW = 3.5
AUX_MW = 2.6
WATER_PUMP_MW = 1.6
WATER_M3_PER_T = 0.29          # fresh water from the Satpayev canal: 0.14-0.40 m3/t, rising, in the last four years of S13 table 4.1

# --------------------------------------------------------------------------
# Reliability (per operating hour)
# --------------------------------------------------------------------------
LAMBDA_BASE = 1 / 260.0        # failure rate of a healthy unit (A)
HAZARD_SLOPE = 4.5             # hazard multiplies e^(4.5*(1-h)) (A)
WEAR_PER_H = {"truck": 0.42, "loader": 0.35, "drill": 0.40}   # health % per op hour (A)
PM_INTERVAL_H = 120.0          # preventive service interval (A)
PM_DURATION_H = 4.0
PDM_THRESHOLD = 45.0           # predictive: service when health < 45 % (A)
PDM_DURATION_H = 3.0
REPAIR_H = (6.0, 12.0)         # unplanned repair incl. parts (A)
RESPONSE_H = 0.75              # breakdown response time (A)
WORKSHOP_BAYS = 4
