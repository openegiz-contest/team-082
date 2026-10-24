#!/usr/bin/env python3
"""Generate the Bozshakol Grafana dashboards (JSON) from one description.

    python3 bozshakol/grafana/build_dashboards.py

Every panel reads InfluxDB (bucket default, measurement mqtt_consumer), which
Telegraf fills from the Ditto twin events: field value_<feature>_properties_value,
tag thingId. The 3D control room is embedded on the overview.
"""

import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards")
DS = {"type": "influxdb", "uid": "opentwins-influxdb"}
NS = "kz.bozshakol"

DASHES = [
    ("overview", "Бозшаколь · Обзор ГОК"),
    ("haulage", "Бозшаколь · Транспорт и диспетчеризация"),
    ("geology", "Бозшаколь · Геология и шихтовка"),
    ("drill-blast", "Бозшаколь · Буровзрывные работы"),
    ("plant", "Бозшаколь · Переработка (ЗИФ)"),
    ("energy", "Бозшаколь · Энергетика"),
    ("maintenance", "Бозшаколь · ТОиР и надёжность"),
    ("safety", "Бозшаколь · Промбезопасность"),
    ("whatif", "Бозшаколь · Сценарии «что если»"),
    ("data-ml", "Бозшаколь · Открытые данные и ML"),
    ("standards", "Бозшаколь · Нормы и контроль качества (ГОСТ)"),
]


def fld(f):
    return f"value_{f}_properties_value"


def q_series(thing, fields, fn="mean"):
    """One series per field of one twin, named by the label."""
    out = []
    for i, (f, label) in enumerate(fields):
        out.append({"refId": chr(65 + i), "datasource": DS, "query": (
            f'from(bucket: "default")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
            f'  |> filter(fn: (r) => r.thingId == "{NS}:{thing}" and r._field == "{fld(f)}")\n'
            f'  |> aggregateWindow(every: v.windowPeriod, fn: {fn}, createEmpty: false)\n'
            f'  |> keep(columns: ["_time", "_value"])\n  |> rename(columns: {{_value: "{label}"}})')})
    return out


def q_pits(fields):
    """The same fields of both pits, one series per pit and field."""
    out = []
    for pit, name in (("pit-central", "Центр."), ("pit-east", "Вост.")):
        for t in q_series(pit, [(f, f"{lab} {name}") for f, lab in fields]):
            t["refId"] = chr(65 + len(out))
            out.append(t)
    return out


def q_by_twin(regex, field, fn="mean"):
    return [{"refId": "A", "datasource": DS, "query": (
        f'from(bucket: "default")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
        f'  |> filter(fn: (r) => r.thingId =~ /^{NS.replace(".", "[.]")}:{regex}/ and r._field == "{fld(field)}")\n'
        f'  |> map(fn: (r) => ({{_time: r._time, _value: r._value, twin: r.thingId}}))\n'
        f'  |> group(columns: ["twin"])\n'
        f'  |> aggregateWindow(every: v.windowPeriod, fn: {fn}, createEmpty: false)')}]


def q_states(regex, field="state"):
    return [{"refId": "A", "datasource": DS, "query": (
        f'from(bucket: "default")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
        f'  |> filter(fn: (r) => r.thingId =~ /^{NS.replace(".", "[.]")}:{regex}/ and r._field == "{fld(field)}")\n'
        f'  |> map(fn: (r) => ({{_time: r._time, _value: r._value, twin: strings.toUpper(v: strings.split(v: r.thingId, t: ":")[1])}}))\n'
        f'  |> group(columns: ["twin"])\n  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)'
    ).replace('from(bucket', 'import "strings"\nfrom(bucket', 1)}]


def q_last(thing, field):
    return [{"refId": "A", "datasource": DS, "query": (
        f'from(bucket: "default")\n  |> range(start: -6h)\n'
        f'  |> filter(fn: (r) => r.thingId == "{NS}:{thing}" and r._field == "{fld(field)}")\n'
        f'  |> last()\n  |> keep(columns: ["_time", "_value"])')}]


def q_table(regex, fields, strings_=()):
    """Latest value of several features for every twin matching regex, one row per twin."""
    targets = []
    for i, fl in enumerate([fields, strings_]):
        if not fl:
            continue
        rx = "|".join(fl)
        targets.append({"refId": chr(65 + i), "datasource": DS, "query": (
            'import "strings"\n'
            f'from(bucket: "default")\n  |> range(start: -30m)\n'
            f'  |> filter(fn: (r) => r.thingId =~ /^{NS.replace(".", "[.]")}:{regex}/ and r._field =~ /^value_({rx})_properties_value$/)\n'
            '  |> last()\n'
            '  |> map(fn: (r) => ({twin: strings.toUpper(v: strings.split(v: r.thingId, t: ":")[1]), _value: r._value, '
            '_field: strings.trimSuffix(v: strings.trimPrefix(v: r._field, prefix: "value_"), suffix: "_properties_value")}))\n'
            '  |> group(columns: ["twin"])\n  |> pivot(rowKey: ["twin"], columnKey: ["_field"], valueColumn: "_value")\n  |> group()')})
    return targets


class Dash:
    def __init__(self, key, title):
        self.key, self.title = key, title
        self.panels = []
        self.y = 0
        self.x = 0
        self.row_h = 0

    def add(self, panel, w, h):
        if self.x + w > 24:
            self.x = 0
            self.y += self.row_h
            self.row_h = 0
        panel["id"] = len(self.panels) + 1
        panel["gridPos"] = {"x": self.x, "y": self.y, "w": w, "h": h}
        panel.setdefault("datasource", DS)
        self.panels.append(panel)
        self.x += w
        self.row_h = max(self.row_h, h)

    def newline(self):
        self.x = 24

    def stat(self, title, thing, field, unit=None, dec=1, w=4, h=4, thresholds=None, color=None):
        p = {"type": "stat", "title": title, "targets": q_last(thing, field),
             "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                         "colorMode": "value", "graphMode": "none", "textMode": "value"},
             "fieldConfig": {"defaults": {"decimals": dec, "unit": unit or "none",
                                          "color": {"mode": "thresholds" if thresholds else "fixed",
                                                    "fixedColor": color or "#d4824a"}}, "overrides": []}}
        if thresholds:
            p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": thresholds}
        self.add(p, w, h)

    def text_stat(self, title, thing, field, w=4, h=4, mappings=None):
        p = {"type": "stat", "title": title, "targets": q_last(thing, field),
             "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False},
                         "colorMode": "background" if mappings else "none", "graphMode": "none", "textMode": "value"},
             "fieldConfig": {"defaults": {"mappings": mappings or [], "color": {"mode": "fixed", "fixedColor": "#2a323b"}},
                             "overrides": []}}
        self.add(p, w, h)

    def ts(self, title, targets, unit=None, w=12, h=8, stack=False, min_=None, thresholds=None, desc=None):
        p = {"type": "timeseries", "title": title, "targets": targets,
             "fieldConfig": {"defaults": {"unit": unit or "none", "custom": {
                 "lineWidth": 2, "fillOpacity": 25 if stack else 8, "showPoints": "never",
                 "stacking": {"mode": "normal" if stack else "none"},
                 "thresholdsStyle": {"mode": "line+area" if thresholds else "off"}}}, "overrides": []},
             "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}
        if min_ is not None:
            p["fieldConfig"]["defaults"]["min"] = min_
        if thresholds:
            p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": thresholds}
            p["fieldConfig"]["defaults"]["color"] = {"mode": "palette-classic"}
        if desc:
            p["description"] = desc
        self.add(p, w, h)

    def table(self, title, targets, w=24, h=8, rename=None, order=None, units=None):
        overrides = []
        for col, u in (units or {}).items():
            overrides.append({"matcher": {"id": "byName", "options": col}, "properties": [{"id": "unit", "value": u}]})
        tr = [{"id": "merge", "options": {}}] if len(targets) > 1 else []
        tr.append({"id": "organize", "options": {"renameByName": rename or {},
                                                  "indexByName": {c: i for i, c in enumerate(order or [])}}})
        tr.append({"id": "sortBy", "options": {"sort": [{"field": "twin"}]}})
        self.add({"type": "table", "title": title, "targets": targets, "transformations": tr,
                  "options": {"showHeader": True, "cellHeight": "sm"},
                  "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": overrides}}, w, h)

    def timeline(self, title, targets, mappings, w=24, h=9):
        self.add({"type": "state-timeline", "title": title, "targets": targets,
                  "options": {"showValue": "never", "rowHeight": 0.8, "mergeValues": True,
                              "legend": {"displayMode": "list", "placement": "bottom"}},
                  "fieldConfig": {"defaults": {"mappings": mappings, "color": {"mode": "fixed", "fixedColor": "#56606b"}},
                                  "overrides": []}}, w, h)

    def html(self, title, content, w=24, h=8, transparent=False):
        self.add({"type": "text", "title": title, "transparent": transparent,
                  "options": {"mode": "html", "content": content}, "datasource": None}, w, h)

    def json(self):
        links = [{"title": t, "type": "link", "url": f"/d/bozshakol-{k}", "targetBlank": False, "icon": "dashboard"}
                 for k, t in DASHES if k != self.key]
        links.insert(0, {"title": "3D-пульт диспетчера", "type": "link", "url": "http://localhost:8095/",
                         "targetBlank": True, "icon": "external link"})
        return {"uid": f"bozshakol-{self.key}", "title": self.title, "tags": ["bozshakol", "openegiz"],
                "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "10s",
                "time": {"from": "now-30m", "to": "now"}, "links": links, "panels": self.panels,
                "templating": {"list": [{"name": "twin", "type": "textbox", "label": "Двойник", "query": "", "hide": 2}]},
                "description": "Цифровой двойник ГОК «Бозшаколь» на OpenEgiz. Данные: модель -> MQTT -> Ditto -> "
                               "Telegraf -> InfluxDB."}


def vm(pairs):
    """Value mappings for state strings: [(value, text, color)]."""
    return [{"type": "value", "options": {v: {"text": t, "color": c, "index": i}}} for i, (v, t, c) in enumerate(pairs)]


TRUCK_STATES = [("hauling", "груженый", "#d4824a"), ("to_loader", "порожний", "#5aa6e8"),
                ("queue_loader", "очередь", "#e6b13a"), ("queue_dump", "очередь разгр.", "#e6b13a"),
                ("spotting", "установка", "#c9d36a"), ("loading", "погрузка", "#9ad36a"),
                ("dumping", "разгрузка", "#c58cf0"), ("to_fuel", "на АЗС", "#7fd6d0"), ("refueling", "заправка", "#7fd6d0"),
                ("to_workshop", "в ремзону", "#a0a0a0"), ("in_workshop", "ТО/ремонт", "#7a7a7a"),
                ("breakdown", "ОТКАЗ", "#e5534b"), ("towing", "буксировка", "#e5534b"), ("standby", "резерв", "#6b7480"),
                ("no_fuel", "нет топлива", "#e5534b"), ("parked", "резерв (сценарий)", "#4b525b"), ("to_park", "в резерв", "#6b7480"), ("to_reserve", "в резерв (нет фронта)", "#6b7480"), ("idle", "ожидание", "#6b7480")]
LOADER_STATES = [("loading", "погрузка", "#9ad36a"), ("spotting", "установка", "#c9d36a"), ("waiting", "ожидание", "#e6b13a"),
                 ("relocating", "перегон", "#5aa6e8"), ("starved", "нет массы", "#e5534b"),
                 ("blast_standby", "укрытие", "#c58cf0"), ("slope_hold", "запрет (борт)", "#e5534b"),
                 ("breakdown", "ОТКАЗ", "#e5534b"), ("maintenance", "ТО", "#7a7a7a"), ("down", "стоп (сценарий)", "#4b525b")]
BLOCK_STATES = [("planned", "запланирован", "#56606b"), ("drilling", "бурение", "#4f7fb0"), ("drilled", "обурен", "#3f9bd0"),
                ("charging", "заряжание", "#d08a3f"), ("charged", "заряжен", "#e86b2c"), ("blasted", "взорван", "#a35fd0"),
                ("mining", "отработка", "#58b368"), ("depleted", "отработан", "#30363c")]


def build():
    D = {k: Dash(k, t) for k, t in DASHES}
    G, R, Y = "#4fbf7a", "#e5534b", "#e6b13a"

    # ---------------------------------------------------------------- overview
    d = D["overview"]
    d.html("3D-пульт диспетчера (данные двойников Ditto)",
           '<iframe src="http://localhost:8095/?view=overview" style="width:100%;height:100%;border:0;border-radius:6px" '
           'title="Бозшаколь 3D"></iframe>', w=24, h=17)
    d.stat("Переработка ОФ", "site", "mill_tph", "t/h", 0, w=4)
    d.stat("Cu в питании", "site", "feed_grade", "percent", 3, w=4)
    d.stat("Извлечение Cu", "site", "recovery", "percent", 1, w=4,
           thresholds=[{"color": R, "value": None}, {"color": Y, "value": 72}, {"color": G, "value": 75}])
    d.stat("Медь в концентрате, т/ч", "site", "cu_tph", "none", 2, w=4)
    d.stat("План по меди (смена)", "site", "cu_plan_pct", "percent", 0, w=4,
           thresholds=[{"color": R, "value": None}, {"color": Y, "value": 85}, {"color": G, "value": 97}])
    d.stat("Активные тревоги", "site", "alarms_active", "none", 0, w=4,
           thresholds=[{"color": G, "value": None}, {"color": Y, "value": 1}, {"color": R, "value": 3}])
    d.ts("Переработка ОФ, т/ч", q_series("site", [("mill_tph", "ЗИФ, т/ч")]), unit="t/h", w=8)
    d.ts("Медь в концентрате, т/ч", q_series("site", [("cu_tph", "Медь, т/ч")]), w=8)
    d.ts("Cu в питании и извлечение", q_series("site", [("feed_grade", "Cu в питании, %"), ("recovery", "Извлечение, %")]),
         unit="percent", w=8)
    d.ts("Электрическая нагрузка, МВт", q_series("site", [("power_mw", "Нагрузка, МВт")]), unit="none", w=8)
    d.ts("Самосвалы на линии и КТГ", q_series("site", [("trucks_working", "На линии"), ("fleet_availability", "КТГ, %")]), w=8)
    d.ts("Горная масса за смену", q_series("site", [("ore_t_shift", "Руда, т"), ("waste_t_shift", "Вскрыша, т")], "last"),
         unit="masst", w=8, stack=True)

    # ---------------------------------------------------------------- haulage
    d = D["haulage"]
    for t, f, u, dec in (("Производительность парка", "productivity_tph", "t/h", 0), ("Средний цикл", "avg_cycle_min", "m", 1),
                         ("Ожидание погрузки", "avg_queue_min", "m", 1), ("Груженых в пути", "trucks_loaded", "none", 0),
                         ("В очередях", "trucks_queued", "none", 0), ("В ремонте", "trucks_down", "none", 0)):
        d.stat(t, "haulage", f, u, dec, w=4)
    d.text_stat("Алгоритм диспетчеризации", "haulage", "dispatch_policy", w=6, h=3,
                mappings=vm([("blend", "по потребности и качеству", "#2f6d4a"), ("min_queue", "минимум очереди", "#6b4f1a"),
                             ("fixed", "закрепление", "#6b2a26")]))
    d.stat("Ограничение скорости", "haulage", "speed_limit", "velocitykmh", 0, w=6, h=3)
    d.stat("ДТ самосвалов за смену", "haulage", "diesel_l_shift", "litre", 0, w=6, h=3)
    d.stat("Горная масса за смену", "site", "moved_t_shift", "masst", 0, w=6, h=3)
    d.timeline("Состояния самосвалов (диаграмма Ганта)", q_states("ht-"), vm(TRUCK_STATES), h=12)
    d.timeline("Состояния экскаваторов", q_states("(sh|ld)-"), vm(LOADER_STATES), h=5)
    d.ts("Самосвалы по состояниям", q_series("haulage", [("trucks_loaded", "груженые"), ("trucks_empty", "порожние"),
                                                        ("trucks_queued", "в очередях"), ("trucks_down", "в ремонте"),
                                                        ("trucks_standby", "резерв")]), w=12, stack=True)
    d.ts("Скорость самосвалов", q_by_twin("ht-", "speed"), unit="velocitykmh", w=12)
    d.table("Самосвалы: текущее состояние", q_table("ht-", ["payload", "speed", "load_grade", "fuel", "health", "p_fail_24h",
                                                           "trips", "cycle_min"], ["state_ru", "destination", "loader", "road"]),
            h=12, rename={"twin": "Самосвал", "state_ru": "состояние", "payload": "груз, т", "speed": "км/ч",
                          "load_grade": "Cu, %", "fuel": "топливо, %", "health": "индекс техсостояния, %", "p_fail_24h": "P(отказ 24ч), %",
                          "trips": "рейсы", "cycle_min": "цикл, мин", "destination": "куда", "loader": "экскаватор", "road": "дорога"},
            order=["twin", "state_ru", "payload", "speed", "load_grade", "destination", "loader", "road", "fuel", "health",
                   "p_fail_24h", "trips", "cycle_min"])
    d.table("Экскаваторы", q_table("(sh|ld)-", ["block_grade", "queue", "utilization", "tonnes", "health", "fuel_lph"],
                                   ["state_ru", "block", "material", "truck"]), h=6,
            rename={"twin": "Экскаватор"})
    d.table("Дороги", q_table("road-", ["moisture", "rolling_resistance", "traffic", "length_km"], ["status"]), h=8,
            rename={"twin": "Дорога", "moisture": "увлажнение, %", "rolling_resistance": "сопр. качению, %",
                    "traffic": "маш/ч", "length_km": "км", "status": "статус"})

    # ---------------------------------------------------------------- geology
    d = D["geology"]
    d.stat("Целевое Cu в питании", "geology", "grade_target", "percent", 3, w=6)
    d.stat("Cu в питании (1 ч)", "geology", "feed_grade_1h", "percent", 3, w=6)
    d.stat("Время в коридоре ±0,03 %", "geology", "in_band_pct", "percent", 0, w=6,
           thresholds=[{"color": R, "value": None}, {"color": Y, "value": 70}, {"color": G, "value": 90}])
    d.stat("Склад забалансовой руды", "geology", "lg_stock_kt", "none", 1, w=6)
    d.ts("Шихтовка: содержание в питании против цели", q_series("geology", [("feed_grade_1h", "Cu в питании (1 ч), %"),
                                                                             ("grade_target", "Цель, %")]), unit="percent", w=16)
    d.ts("Доля богатой руды SH-02 в плане", q_series("geology", [("blend_share_hg", "доля SH-02, %")]), unit="percent", w=8)
    d.ts("Содержание Cu в кузовах (рудоконтроль по рейсу)", q_by_twin("ht-", "load_grade", "max"), unit="percent", w=12)
    d.ts("Содержание в забоях", q_by_twin("(sh|ld)-", "block_grade"), unit="percent", w=12)
    d.table("Блочная модель: активные блоки", q_table("blk-", ["cu", "au", "clay", "ucs", "ucs_mwd", "bwi", "remaining"],
                                                      ["code", "state_ru", "material", "loader"]), h=10,
            rename={"twin": "Слот", "code": "блок", "state_ru": "состояние", "material": "материал", "loader": "экскаватор",
                    "cu": "Cu, %", "au": "Au, г/т", "clay": "глина, %", "ucs": "UCS, МПа", "ucs_mwd": "UCS по MWD",
                    "bwi": "Бонд, кВт·ч/т", "remaining": "остаток, т"},
            order=["twin", "code", "state_ru", "material", "loader", "cu", "au", "clay", "ucs", "ucs_mwd", "bwi", "remaining"])
    d.ts("Склад забалансовой руды", q_series("lg-01", [("stock_kt", "запас, кт")]), w=12)
    d.ts("Коэффициент вскрыши (смена) по карьерам", q_pits([("strip_ratio_shift", "т/т")]), w=12)
    # Monthly planning: two pits, exposed ore
    d.stat("Вскрытые запасы: Центральный, мес", "pit-central", "exposed_months", "none", 1, w=6,
           thresholds=[{"color": R, "value": None}, {"color": Y, "value": 1.0}, {"color": G, "value": 2.0}])
    d.stat("Вскрытые запасы: Восточный, мес", "pit-east", "exposed_months", "none", 1, w=6,
           thresholds=[{"color": R, "value": None}, {"color": Y, "value": 1.0}, {"color": G, "value": 2.0}])
    d.stat("Доля руды с Восточного (план)", "control", "east_ore_share", "percentunit", 2, w=6)
    d.stat("CAT 785C на Восточном", "control", "trucks_east", "none", 0, w=6)
    d.ts("Обеспеченность вскрытыми запасами, мес", q_pits([("exposed_months", "мес")]), w=12, min_=0)
    d.ts("Руда и вскрыша за смену по карьерам, кт", q_pits([("ore_kt_shift", "руда"), ("waste_kt_shift", "вскрыша")]), w=12)

    # ---------------------------------------------------------------- drill-blast
    d = D["drill-blast"]
    d.text_stat("Взрыв", "drill-blast", "blast_state", w=4,
                mappings=vm([("нет", "нет", "#2a323b"), ("эвакуация", "ЭВАКУАЦИЯ", "#8a2a24"), ("проветривание", "проветривание", "#6b4f1a")]))
    d.text_stat("Следующее окно", "drill-blast", "next_window", w=4)
    d.stat("Удельный расход ВВ", "drill-blast", "design_pf", "none", 2, w=4)
    d.text_stat("Сетка скважин", "drill-blast", "pattern", w=4)
    d.stat("Блоков заряжено", "drill-blast", "blocks_charged", "none", 0, w=4)
    d.stat("Взорванная горная масса, кт", "pit-central", "blasted_stock_kt", "none", 0, w=4)
    d.html("Mine-to-Mill", "<div style='padding:4px 8px;font-size:13px'>Ниже — установившийся эффект текущего удельного расхода ВВ "
           "на всю цепочку (модель Kuz-Ram → скорость экскавации → крупность питания F80 → удельная энергия МПСИ). Динамика "
           "в модели наступает, когда новые блоки взорваны и дошли до экскаватора.</div>", h=3, transparent=True)
    for t, f, u, dec in (("x80 после взрыва, см", "m2m_x80_cm", "none", 0), ("Скорость экскавации", "m2m_dig_rate_pct", "percent", 0),
                         ("Потенциал МПСИ", "m2m_sag_tph", "t/h", 0), ("Скважин на 100 кт", "m2m_holes_per_100kt", "none", 0),
                         ("Затраты на ВВ, ₸/т", "m2m_explosive_kzt_t", "none", 0), ("ВВ за смену, т", "explosive_t_shift", "none", 1)):
        d.stat(t, "drill-blast", f, u, dec, w=4)
    d.timeline("Жизненный цикл блоков: бурение → заряжание → взрыв → отработка", q_states("blk-"), vm(BLOCK_STATES), h=9)
    d.ts("MWD: скорость бурения", q_by_twin("dr-", "rop"), unit="none", w=8)
    d.ts("MWD: удельная энергия бурения (Teale)", q_by_twin("dr-", "specific_energy"), w=8)
    d.ts("Крепость по MWD (оценка UCS)", q_by_twin("dr-", "ucs_est"), w=8)
    d.table("Блоки: проект и результат взрыва", q_table("blk-", ["holes_total", "holes_drilled", "holes_charged", "burden",
                                                                  "spacing", "powder_factor", "explosive_t", "x50", "x80"],
                                                         ["code", "state_ru"]), h=10,
            rename={"twin": "Слот", "code": "блок", "state_ru": "состояние", "holes_total": "скв.", "holes_drilled": "обурено",
                    "holes_charged": "заряжено", "burden": "B, м", "spacing": "S, м", "powder_factor": "q, кг/м³",
                    "explosive_t": "ВВ, т", "x50": "x50, см", "x80": "x80, см"},
            order=["twin", "code", "state_ru", "holes_total", "holes_drilled", "holes_charged", "burden", "spacing",
                   "powder_factor", "explosive_t", "x50", "x80"])

    # ---------------------------------------------------------------- plant
    d = D["plant"]
    for t, th, f, u, dec in (("ККД-1", "gc-01", "throughput", "t/h", 0), ("Склад КД", "cos-01", "level_kt", "none", 1),
                             ("МПСИ", "sag-01", "throughput", "t/h", 0), ("Мощность МПСИ", "sag-01", "power_mw", "none", 1),
                             ("P80", "bm-01", "p80", "none", 0), ("Извлечение", "fl-r", "recovery", "percent", 1)):
        d.stat(t, th, f, u, dec, w=4)
    d.ts("Дробление и склад", q_series("gc-01", [("throughput", "ККД-1, т/ч")]) +
         [dict(x, refId="B") for x in q_series("cv-01", [("load_tph", "Конвейер, т/ч")])], unit="t/h", w=12)
    d.ts("Склад крупнодроблёной руды и запас по времени", q_series("cos-01", [("level_kt", "запас, кт"), ("hours_cover", "запас, ч")]), w=12)
    d.ts("МПСИ: производительность и удельная энергия", q_series("sag-01", [("throughput", "т/ч")]), unit="t/h", w=8)
    d.ts("МПСИ: мощность и предел (пиковое ограничение)", q_series("sag-01", [("power_mw", "мощность, МВт"),
                                                                              ("power_limit_mw", "предел, МВт")]), w=8)
    d.ts("Удельная энергия МПСИ и F80", q_series("sag-01", [("specific_energy", "кВт·ч/т"), ("f80", "F80, мм")]), w=8)
    d.ts("Крупность помола P80 (Бонд)", q_series("bm-01", [("p80", "P80, мкм")]), w=8)
    d.ts("Флотация: извлечение и время пребывания", q_series("fl-r", [("recovery", "извлечение, %"), ("residence_min", "τ, мин")]), w=8)
    d.ts("Глина в питании и мутность слива хвостов", q_series("fl-r", [("feed_clay", "глина, %")]) +
         [dict(x, refId="B") for x in q_series("th-t", [("overflow_ntu", "мутность, NTU")])], w=8)
    d.ts("Концентрат", q_series("fl-c", [("conc_grade", "Cu в конц., %"), ("conc_tph", "конц., т/ч")]), w=8)
    d.ts("Хвосты: потери Cu", q_series("fl-r", [("tails_grade", "Cu в хвостах, %")]), unit="percent", w=8)
    d.ts("Глинистая фабрика", q_series("cp-01", [("throughput", "т/ч"), ("recovery", "извлечение, %")]), w=8)
    d.stat("Износ брони ККД", "gc-01", "mantle_wear", "percent", 0, w=6,
           thresholds=[{"color": G, "value": None}, {"color": Y, "value": 85}, {"color": R, "value": 95}])
    d.stat("Остаток футеровки МПСИ", "sag-01", "liner_remaining", "percent", 0, w=6)
    d.stat("Свежая вода, м³/ч", "water-01", "fresh_m3h", "none", 0, w=6)
    d.stat("Запас дамбы ХХ, м", "tsf-01", "freeboard", "none", 2, w=6)

    # ---------------------------------------------------------------- energy
    d = D["energy"]
    for t, th, f, u, dec in (("Нагрузка ГОК", "energy", "power_mw", "none", 1), ("Пик (15 мин)", "energy", "peak_mw_15", "none", 1),
                             ("Стоимость э/э, ₸/ч", "energy", "cost_kzt_h", "none", 0), ("ДТ, л/ч", "energy", "diesel_lph", "none", 0),
                             ("CO₂, т/ч", "energy", "co2_t_h", "none", 1), ("Удельный расход, кВт·ч/т", "site", "kwh_per_t", "none", 1)):
        d.stat(t, th, f, u, dec, w=4)
    d.text_stat("Тарифная зона", "energy", "tariff_zone", w=6, h=3,
                mappings=vm([("ночь", "ночь", "#1f3b5a"), ("день", "день", "#2f4a2f"), ("пик", "ПИК", "#8a2a24")]))
    d.text_stat("Снижение нагрузки в пик", "energy", "peak_shaving", w=6, h=3,
                mappings=[{"type": "value", "options": {"true": {"text": "включено", "color": "#6b4f1a"},
                                                        "false": {"text": "выключено", "color": "#2a323b"}}}])
    d.stat("Тариф, ₸/кВт·ч", "energy", "price", "none", 0, w=6, h=3)
    d.stat("Э/э за смену, МВт·ч", "energy", "mwh_shift", "none", 0, w=6, h=3)
    d.ts("Нагрузка по потребителям (ПС 220 кВ)", q_series("ss-220", [("load_sag", "МПСИ"), ("load_bm", "ШМ"),
                                                                  ("load_flotation", "Флотация"), ("load_crushing", "Дробление+конвейер"),
                                                                  ("load_clay_plant", "Глинистая ф-ка"), ("load_other", "Прочее")]),
         w=16, h=10, stack=True)
    d.ts("Стоимость э/э, ₸/ч", q_series("energy", [("cost_kzt_h", "₸/ч")]), w=8, h=10)
    d.ts("Расход дизтоплива по самосвалам", q_by_twin("ht-", "fuel_lph"), unit="none", w=12)
    d.ts("Запас ДТ на АЗС", q_series("fs-01", [("diesel_m3", "м³")]), w=6)
    d.ts("Напряжение 220 кВ", q_series("ss-220", [("voltage_kv", "кВ")]), w=6)
    d.html("Реальный энергопрофиль ГОК-аналога", (
        "<div style='padding:6px 10px;font-size:13px;line-height:1.55'>Двойник <code>en-01</code> проигрывает реальные получасовые "
        "данные пяти главных подстанций горно-обогатительного комбината (январь и июнь 2019, Zenodo 20647907, CC BY-SA 4.0) — "
        "только отложенную часть. GBM прогнозирует нагрузку на 2 ч вперёд для работы с пиковым тарифом и платой за мощность. "
        "Рядом — нагрузка модели Бозшаколя: профиль и cos φ сравнимы, абсолютный уровень — нет (другой комбинат).</div>"), h=4)
    d.stat("Аналог: нагрузка сейчас, МВт", "en-01", "p_mw", "none", 1, w=4)
    d.stat("ML: через 2 ч, МВт", "en-01", "forecast_2h", "none", 1, w=4)
    d.stat("Факт через 2 ч, МВт", "en-01", "actual_2h", "none", 1, w=4)
    d.stat("Ошибка ML за 24 ч, МВт", "en-01", "ml_mae_24h", "none", 2, w=4)
    d.stat("Ошибка «как сейчас», МВт", "en-01", "now_mae_24h", "none", 2, w=4)
    d.stat("cos φ аналога", "en-01", "cos_phi", "none", 3, w=4)
    d.ts("Аналог: нагрузка, прогноз ML на 2 ч и факт", q_series("en-01", [("p_mw", "сейчас"), ("forecast_2h", "ML через 2 ч"),
                                                                         ("actual_2h", "факт через 2 ч")]), w=12, h=9)
    d.ts("Аналог: нагрузка по главным подстанциям", q_series("en-01", [(f"p_gpp{g}", f"ГПП-{g}") for g in range(1, 6)]), w=12, h=9, stack=True)

    # ---------------------------------------------------------------- maintenance
    d = D["maintenance"]
    d.text_stat("Стратегия ТОиР", "maintenance", "strategy", w=6,
                mappings=vm([("preventive", "по наработке", "#2a3b4f"), ("predictive", "по состоянию (PdM)", "#2f4a2f"),
                             ("reactive", "по отказу", "#6b2a26")]))
    d.stat("КТГ самосвалов", "maintenance", "fleet_availability", "percent", 1, w=3)
    d.stat("В ремзоне", "maintenance", "in_workshop", "none", 0, w=3)
    d.stat("Очередь в ремзону", "maintenance", "queue", "none", 0, w=3)
    d.stat("Отказов всего", "maintenance", "failures_total", "none", 0, w=3)
    d.stat("Риск отказа >30 %", "maintenance", "high_risk_units", "none", 0, w=3,
           thresholds=[{"color": G, "value": None}, {"color": Y, "value": 2}, {"color": R, "value": 5}])
    d.stat("Среднее время ремонта, ч", "maintenance", "mttr_h", "none", 1, w=3)
    d.ts("Индекс технического состояния самосвалов", q_by_twin("ht-", "health"), unit="percent", w=12, h=10)
    d.ts("Вероятность отказа за 24 ч", q_by_twin("ht-", "p_fail_24h"), unit="percent", w=12, h=10)
    d.ts("КТГ парка и машины в ремзоне", q_series("maintenance", [("fleet_availability", "КТГ, %"), ("in_workshop", "в ремзоне")]), w=12)
    d.ts("Экскаваторы и станки: расчётный индекс техсостояния", q_by_twin("(sh|ld|dr)-", "health"), unit="percent", w=12)
    d.html("Мониторинг состояния", (
        "<div style='padding:6px 10px;font-size:13px;line-height:1.55'>Машины публикуют то, что реально измеряют бортовые системы: "
        "температуры ОЖ, масел трансмиссии, тормозов и гидравлики, давления масла и шин, перегрузы, коды неисправностей, анализ масла "
        "(Fe, Si) при каждом ТО. Индекс техсостояния — расчётный, из отклонений сигналов от ожидаемых при текущей нагрузке; "
        "по нему работает стратегия «ТО по состоянию». Истинный износ модели скрыт, как на реальном руднике.</div>"), h=4)
    d.ts("Самосвалы: температура масла тормозов (растёт на спусках), °C", q_by_twin("ht-", "cm_brake_oil"), unit="celsius", w=12,
         thresholds=[{"color": "transparent", "value": None}, {"color": "rgba(229,83,75,0.15)", "value": 115}])
    d.ts("Самосвалы: температура ОЖ двигателя, °C", q_by_twin("ht-", "cm_engine_coolant"), unit="celsius", w=12,
         thresholds=[{"color": "transparent", "value": None}, {"color": "rgba(229,83,75,0.15)", "value": 104}])
    d.table("Мониторинг самосвалов: сигналы, коды, анализ масла",
            q_table("ht-", ["health", "cm_engine_coolant", "cm_engine_oil_pressure", "cm_transmission_oil", "cm_brake_oil",
                            "cm_tyre_temp", "cm_tyre_pressure", "cm_overload_share", "cm_oil_fe", "cm_codes_count"],
                    ["cm_weak_point", "cm_codes"]), h=10,
            rename={"twin": "Самосвал", "health": "Индекс, %", "cm_engine_coolant": "ОЖ, °C", "cm_engine_oil_pressure": "Масло, кПа",
                    "cm_transmission_oil": "Трансм., °C", "cm_brake_oil": "Тормоза, °C", "cm_tyre_temp": "Шины, °C",
                    "cm_tyre_pressure": "Шины, кПа", "cm_overload_share": "Перегруз, %", "cm_oil_fe": "Fe, ppm",
                    "cm_codes_count": "Кодов", "cm_weak_point": "Слабое место", "cm_codes": "Активные коды"})
    d.table("Ремзона", q_table("ws-", ["bays_busy", "queue", "repairs_done", "mttr_h"], ["units"]), h=5,
            rename={"twin": "Ремзона", "units": "машины в боксах"})

    # ---------------------------------------------------------------- safety
    d = D["safety"]
    d.text_stat("Устойчивость бортов", "safety", "slope_level", w=4,
                mappings=vm([("норма", "норма", "#2f4a2f"), ("жёлтый", "ЖЁЛТЫЙ", "#6b4f1a"), ("красный", "КРАСНЫЙ", "#8a2a24")]))
    d.text_stat("Допуск в зону взрыва", "safety", "reentry", w=4,
                mappings=vm([("разрешён", "разрешён", "#2f4a2f"), ("запрещён", "ЗАПРЕЩЁН", "#8a2a24")]))
    d.stat("CAS за смену", "safety", "cas_alerts_shift", "none", 0, w=4)
    d.stat("PM10 максимум, мкг/м³", "safety", "pm10_max", "none", 0, w=4,
           thresholds=[{"color": G, "value": None}, {"color": Y, "value": 80}, {"color": R, "value": 150}])
    d.stat("Осадки, мм/ч", "wx-01", "rain", "none", 1, w=4)
    d.stat("Ветер, м/с", "wx-01", "wind_speed", "none", 1, w=4)
    d.ts("Радар бортов SR-01: скорость смещения по секторам (жёлтый 5, красный 15 мм/сут)",
         q_series("sr-01", [("w1_velocity", "W1"), ("w2_velocity", "W2"), ("w3_velocity", "W3")]), w=12, h=9,
         thresholds=[{"color": "transparent", "value": None}, {"color": "rgba(230,177,58,0.15)", "value": 5},
                     {"color": "rgba(229,83,75,0.18)", "value": 15}])
    d.ts("Прогноз времени до обрушения (метод обратной скорости, ч; −1 = нет ускорения)",
         q_series("sr-01", [("w1_ttf_h", "W1"), ("w2_ttf_h", "W2"), ("w3_ttf_h", "W3")]), w=12, h=9)
    d.ts("Пыль PM10 (норматив 150 мкг/м³)", q_by_twin("dm-", "pm10"), w=12,
         thresholds=[{"color": "transparent", "value": None}, {"color": "rgba(229,83,75,0.15)", "value": 150}])
    d.ts("Газы после взрыва (CO, NO₂)", q_series("gm-01", [("co", "CO, ppm"), ("no2", "NO₂, ppm")]), w=12)
    d.ts("Увлажнение дорог (поливочная машина, дождь)", q_by_twin("road-", "moisture"), unit="percent", w=12)
    d.ts("Метео", q_series("wx-01", [("temperature", "t, °C"), ("wind_speed", "ветер, м/с"), ("rain", "дождь, мм/ч")]), w=12)
    d.table("Персонал (синтетические метки ролей)", q_table("p-", ["nearest_truck_m"], ["zone"]), h=6,
            rename={"twin": "Метка", "nearest_truck_m": "до самосвала, м", "zone": "зона"})

    # ---------------------------------------------------------------- what-if
    d = D["whatif"]
    d.html("Как запускать сценарии",
           "<div style='padding:6px 10px;font-size:13px;line-height:1.5'>Сценарии запускаются без изменения кода: "
           "в <a href='http://localhost:8095/' target='_blank'>3D-пульте</a> (вкладка «Сценарии»), командой "
           "<code>make scenario P=heavy_rain</code> или записью в двойник <code>kz.bozshakol:control</code> через Ditto. "
           "Отмена — «Базовый режим» или <code>make scenario-reset</code>. Модель применяет изменение за ~3 с; прогноз на 48 ч "
           "(база против сценария на одинаковых случайных числах) публикуется в двойник <code>kz.bozshakol:whatif</code>.</div>",
           h=4)
    d.text_stat("Активный сценарий", "whatif", "scenario", w=16, h=3)
    d.text_stat("Статус прогноза", "whatif", "status", w=8, h=3,
                mappings=vm([("готов", "готов", "#2f4a2f"), ("расчёт", "расчёт…", "#6b4f1a")]))
    for t, f in (("Δ маржа, %", "delta_margin_mkzt"), ("Δ медь, %", "delta_cu_t"), ("Δ переработка, %", "delta_mill_t"),
                 ("Δ ДТ, %", "delta_diesel_l"), ("Δ КТГ, %", "delta_fleet_avail"), ("Δ отказы, %", "delta_failures")):
        d.stat(t, "whatif", f, "none", 1, w=4, thresholds=[{"color": R, "value": None}, {"color": "#8b96a2", "value": -0.5},
                                                          {"color": G, "value": 0.5}])
    d.ts("Прогноз меди за 48 ч: база и сценарий", q_series("whatif", [("base_cu_t", "база, т"), ("scen_cu_t", "сценарий, т")], "last"), w=12)
    d.ts("Прогноз маржи за 48 ч, млн ₸", q_series("whatif", [("base_margin_mkzt", "база"), ("scen_margin_mkzt", "сценарий")], "last"), w=12)
    keys = ["margin_mkzt", "cu_t", "ore_t", "waste_t", "mill_t", "feed_grade", "recovery", "kwh_t", "diesel_l",
            "cost_kzt_t_cu", "fleet_avail", "failures", "inband_pct", "queue_min", "cos_end_kt", "co2_t", "cas_alerts"]
    flux = ('import "strings"\nfrom(bucket: "default")\n  |> range(start: -6h)\n'
            f'  |> filter(fn: (r) => r.thingId == "{NS}:whatif" and r._field =~ /^value_(base|scen|delta)_.*_properties_value$/)\n'
            '  |> last()\n'
            '  |> map(fn: (r) => ({kind: strings.split(v: strings.trimPrefix(v: r._field, prefix: "value_"), t: "_")[0], '
            'kpi: strings.trimSuffix(v: strings.trimPrefix(v: strings.trimPrefix(v: strings.trimPrefix(v: strings.trimPrefix(v: r._field, '
            'prefix: "value_"), prefix: "base_"), prefix: "scen_"), prefix: "delta_"), suffix: "_properties_value"), _value: r._value}))\n'
            '  |> group()\n  |> pivot(rowKey: ["kpi"], columnKey: ["kind"], valueColumn: "_value")')
    d.add({"type": "table", "title": "Прогноз на 48 ч: все показатели", "targets": [{"refId": "A", "datasource": DS, "query": flux}],
           "transformations": [{"id": "organize", "options": {"renameByName": {"kpi": "показатель", "base": "база",
                                                                               "scen": "сценарий", "delta": "Δ, %"},
                                                              "indexByName": {"kpi": 0, "base": 1, "scen": 2, "delta": 3}}}],
           "fieldConfig": {"defaults": {"decimals": 2}, "overrides": [
               {"matcher": {"id": "byName", "options": "Δ, %"}, "properties": [
                   {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                   {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": R, "value": None},
                                                                               {"color": "#8b96a2", "value": -0.5},
                                                                               {"color": G, "value": 0.5}]}}]}]},
           "options": {"showHeader": True, "cellHeight": "sm"}}, 24, 14)
    _ = keys

    # ---------------------------------------------------------------- open data and ML
    d = D["data-ml"]
    met = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "models", "metrics.json")))
    fm, sm, gm, hm, rm = (met["flotation_silica"], met["seismic_hazard"], met["geomet_grid"], met["geomet_hardness"],
                          met["geomet_recovery"])
    mw = met.get("mwd_rocktype", {})
    fr = next(iter(met.get("fragmentation_ref", {}).values()), {})
    d.html("Что здесь", (
        "<div style='padding:6px 10px;font-size:13px;line-height:1.55'>Открытые датасеты со страницы конкурса работают в двойнике. "
        "Модели обучены заранее (<code>bozshakol/ml/train.py</code>), на стенде исполняются на чистом Python, все метрики — "
        "на данных, которых модель не видела.<br>"
        f"<b>GeoMet</b> (Zenodo 7051975, CC BY 4.0): {gm['samples']} проб из {gm['holes']} скважин → GBM-интерполяция в 3D-сетку → "
        "содержание Cu/Au и крепость каждого взрывного блока (уровень откалиброван на Бозшаколь). "
        f"Крепость по химии: ridge, R² {hm['r2_cv']} (перекрёстная проверка по скважинам). Извлечение LCT по химии не "
        f"предсказывается (R² {rm['r2_cv']}) — поэтому в модель не подключено.<br>"
        f"<b>Флотация</b> (Kaggle, CC0): двойник <code>qc-01</code> проигрывает реальные часы отложенной части; софтсенсор SiO₂ — "
        f"R² {fm['r2']} против {fm['r2_naive']} у последнего анализа лаборатории (задержка {fm['lab_delay_h']} ч), MAE {fm['mae']} против {fm['mae_naive']}.<br>"
        f"<b>Сейсмика</b> (UCI, CC BY 4.0): <code>sm-01</code>, GBM-классификатор опасной смены — ROC AUC {sm['roc_auc_holdout']} на "
        f"будущих сменах (эксперт {sm['roc_auc_expert_holdout']}), {sm['roc_auc_cv']} при перекрёстной проверке.<br>"
        f"<b>MWD → порода</b> (NGI, 15 тоннелей Норвегии, Zenodo 10358374, CC BY 4.0): <code>mwd-01</code>, GBM на 10 пород — точность "
        f"{mw.get('accuracy')} на отложенных циклах (самая частая порода {mw.get('accuracy_majority')}, порода прошлого цикла "
        f"{mw.get('accuracy_previous_round')}); подсказка геологу, а не замена картированию.<br>"
        f"<b>Фрагментация</b> (дрон, карьер El Aljibe, Zenodo 10666378, CC BY 4.0): Розин–Раммлер n = {fr.get('rr_n')}, x50 = "
        f"{fr.get('x50_mm_measured')} мм — эталон для модели Kuz-Ram (n = 1,35).</div>"), h=8)
    d.stat("SiO₂: ML-оценка сейчас", "qc-01", "silica_ml", "percent", 2, w=4)
    d.stat("SiO₂: последний анализ (3 ч назад)", "qc-01", "silica_lab", "percent", 2, w=4)
    d.stat("SiO₂: факт", "qc-01", "silica_actual", "percent", 2, w=4)
    d.stat("Средняя ошибка ML, 24 ч", "qc-01", "ml_mae_24h", "none", 3, w=4)
    d.stat("ML: вероятность опасной смены", "sm-01", "hazard_ml", "percent", 1, w=4,
           thresholds=[{"color": G, "value": None}, {"color": Y, "value": 10.8}, {"color": R, "value": 30}])
    d.text_stat("Эксперт: опасность", "sm-01", "ghazard", w=4)
    d.ts("Флотация (реальные данные): SiO₂ в концентрате — ML сейчас, анализ лаборатории и факт",
         q_series("qc-01", [("silica_ml", "ML-оценка"), ("silica_lab", "анализ (3 ч назад)"), ("silica_actual", "факт")]),
         unit="percent", w=12, h=9)
    d.ts("Флотация (реальные данные): питание и реагенты",
         q_series("qc-01", [("silica_feed", "SiO₂ в питании, %"), ("iron_feed", "Fe в питании, %"), ("pulp_ph", "pH")]), w=12, h=9)
    d.ts("Сейсмостанция (реальные данные): ML-вероятность опасной смены, %", q_series("sm-01", [("hazard_ml", "ML, %")]), w=12,
         thresholds=[{"color": "transparent", "value": None}, {"color": "rgba(229,83,75,0.15)", "value": 10.8}])
    d.ts("Сейсмостанция: энергия толчков, Дж", q_series("sm-01", [("energy", "суммарная"), ("maxenergy", "максимальная")]), w=12)
    d.text_stat("MWD: порода по ML", "mwd-01", "rock_ml", w=6)
    d.text_stat("MWD: порода по картированию", "mwd-01", "rock_mapped", w=6)
    d.stat("ML: уверенность", "mwd-01", "rock_ml_prob", "percent", 0, w=4)
    d.stat("Эталон фрагментации: n", "drill-blast", "frag_ref_n", "none", 2, w=4)
    d.stat("Kuz-Ram модели: x50, мм", "drill-blast", "frag_model_x50", "none", 0, w=4)
    d.ts("MWD (реальные данные): нормированные параметры бурения цикла",
         q_series("mwd-01", [("penetration", "проходка"), ("rotation_pressure", "вращение"), ("feed_pressure", "подача"),
                             ("water_flow", "вода")]), w=24, h=8)
    d.table("Взрывные блоки: геология из GeoMet и ML-крепость",
            q_table("blk-", ["geo_cu_ppm", "geo_fe_ppm", "geo_s_ppm", "geo_k_ppm", "t10_ml", "hardness_factor", "cu", "ucs", "bwi"],
                    ["code", "material"]), h=9,
            rename={"twin": "Блок", "geo_cu_ppm": "Cu GeoMet, ppm", "geo_fe_ppm": "Fe, ppm", "geo_s_ppm": "S, ppm",
                    "geo_k_ppm": "K, ppm", "t10_ml": "t (ML)", "hardness_factor": "× крепость", "cu": "Cu блока, %",
                    "ucs": "UCS, МПа", "bwi": "Bond Wi", "code": "код", "material": "материал"})

    # ---------------------------------------------------------------- standards (ГОСТ)
    d = D["standards"]
    d.html("Нормы в двойнике", (
        "<div style='padding:6px 10px;font-size:13px;line-height:1.55'>Стандарты работают как правила модели, а не как ссылки. "
        "<b>ГОСТ 32144-2013</b> — анализатор <code>pq-01</code> на ПС 220 кВ: отклонения частоты и напряжения, гармоники от "
        "безредукторных приводов МПСИ и ШМ, несимметрия, фликер, провалы; усреднение 10 мин, оценка на окне в неделю (1008 интервалов). "
        "Сценарий «ФКУ отключена» выводит K_U за нормы. "
        "<b>ГОСТ 14180-80</b> — план опробования смены в <code>lab-01</code>: m = Q·b/(3600·v), N = 4V²/Δ², T = 60·M/(Q·N), "
        "категория однородности и K·d². <b>ГОСТ 13170-80</b> — влага по двум параллельным определениям с допуском п. 4.2. "
        "<b>ГОСТ 24598-81</b> — ситовый анализ питания флотации (модуль √2 от 0,04 мм, q = 0,02d² + 0,5d). "
        "Баланс по трём продуктам ε = c(f−t)/(f(c−t)) сравнивается с данными фабрики.</div>"), h=5)
    d.text_stat("Соответствие ГОСТ 32144 (итог — на полной неделе)", "pq-01", "compliance", w=6,
                mappings=vm([("соответствует", "соответствует", "#2f4a2f"), ("НЕ соответствует", "НЕ СООТВЕТСТВУЕТ", "#8a2a24")]))
    d.stat("Полнота недельного окна", "pq-01", "window_coverage", "percent", 1, w=4,
           thresholds=[{"color": Y, "value": None}, {"color": G, "value": 100}])
    d.text_stat("ФКУ", "pq-01", "harmonic_filter", w=4,
                mappings=vm([("включена", "включена", "#2f4a2f"), ("ОТКЛЮЧЕНА", "ОТКЛЮЧЕНА", "#8a2a24")]))
    d.stat("K_U сейчас", "pq-01", "ku", "percent", 2, w=4,
           thresholds=[{"color": G, "value": None}, {"color": Y, "value": 2.0}, {"color": R, "value": 3.0}])
    d.stat("Время с K_U ≤ 2 %", "pq-01", "ku_95_share", "percent", 1, w=4,
           thresholds=[{"color": R, "value": None}, {"color": G, "value": 95}])
    d.stat("Провалов напряжения", "pq-01", "dips", "none", 0, w=4)
    d.ts("Гармоники (норма K_U 2 % / 3 %, K_U(5) 1,5 % / 2,25 %)",
         q_series("pq-01", [("ku", "K_U"), ("ku5", "K_U(5)"), ("ku7", "K_U(7)")]), unit="percent", w=12, h=8,
         thresholds=[{"color": "transparent", "value": None}, {"color": "rgba(230,177,58,0.15)", "value": 2},
                     {"color": "rgba(229,83,75,0.18)", "value": 3}])
    d.ts("Отклонения частоты (Гц) и напряжения (%)", q_series("pq-01", [("freq_dev", "Δf, Гц"), ("volt_dev", "δU, %")]), w=12, h=8)
    d.ts("Несимметрия K_2U (норма 2 %) и фликер P_st (норма 1,38)", q_series("pq-01", [("k2u", "K_2U, %"), ("pst", "P_st")]), w=12)
    d.ts("Опробование смены (ГОСТ 14180): точечных проб и период, мин",
         q_series("lab-01", [("n_points", "принято проб"), ("n_min", "минимум по ф. (3)"), ("period_min", "период, мин")]), w=12)
    d.ts("Анализы смены: Cu в питании и хвостах, %", q_series("lab-01", [("assay_feed", "питание"), ("assay_tails", "хвосты")], "last"),
         unit="percent", w=8)
    d.ts("Баланс: извлечение по 3 продуктам и по фабрике, %",
         q_series("lab-01", [("eps_lab", "ОТК, 3 продукта"), ("eps_plant", "фабрика")], "last"), unit="percent", w=8)
    d.ts("Влага (ГОСТ 13170) и класс −0,08 мм (ГОСТ 24598), %",
         q_series("lab-01", [("w_conc", "влага конц."), ("w_ore", "влага руды"), ("sieve_minus_008", "−0,08 мм")], "last"),
         unit="percent", w=8)
    return D


def main():
    os.makedirs(OUT, exist_ok=True)
    for key, d in build().items():
        path = os.path.join(OUT, f"{key}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(d.json(), fh, ensure_ascii=False, indent=1)
        print(f"{path}: {len(d.panels)} panels")


if __name__ == "__main__":
    main()
