"""
Equipment passports of the Bozshakol twin.

Source: the team's equipment reference (20.10.2026), compiled from the
manufacturers' documentation; docs/equipment_passports.pdf is generated from
this module (tools/build_passports.py). Every value below is a passport value
with its unit and a link to the manufacturer's document. Operating speeds,
fuel burn, repair times and the simulator's calibrated throughputs are NOT
passport values; they live in sim/params.py and are marked (A) there.

A passport is static: it is written to the twin's attributes (and, since it
is the same for every instance of a model, to the OpenTwins type), never to
features, which carry telemetry only.

Statuses:
  passport   — a serial model, values from its spec sheet
  analog     — a real serial model proposed as an analog; not confirmed as
               installed at Bozshakol
  family     — a custom-engineered product; the family limits are given, not
               the characteristics of a selected unit
  drive      — the drive and mill size are confirmed for Bozshakol (ABB),
               the shell manufacturer is not
  candidate  — a candidate device for a function of the twin
  project    — no serial passport: described by project documentation
"""

STATUS_RU = {
    "passport": "паспорт производителя",
    "analog": "предлагаемый аналог (не подтверждён как установленный)",
    "family": "семейство, исполнение на заказ (не выбранный агрегат)",
    "drive": "привод и размер подтверждены ABB, изготовитель барабана не установлен",
    "candidate": "кандидат для функции двойника",
    "project": "без серийного паспорта, по проектной документации",
}


def _p(manufacturer, model, variant, status, specs, notes, title, ref, url):
    return {
        "manufacturer": manufacturer, "model": model, "variant": variant,
        "status": status, "status_ru": STATUS_RU[status],
        "specs": {k: {"label": lab, "value": v, "unit": u} for k, lab, v, u in specs},
        "notes": notes,
        "source": {"title": title, "ref": ref, "url": url},
    }


PASSPORTS = {
    "cat-785c": _p(
        "Caterpillar", "CAT 785C", "Dual-slope body", "passport",
        [("payload_t", "Номинальная грузоподъёмность", 136, "т"),
         ("gross_kw", "Полная мощность двигателя", 1082, "кВт"),
         ("net_kw", "Полезная мощность, ISO 9249", 1005, "кВт"),
         ("body_m3", "Объём кузова с шапкой (SAE 2:1, Dual-slope)", 78, "м³"),
         ("tank_l", "Топливный бак", 1893, "л"),
         ("gmw_kg", "Предельная полная масса машины", 249480, "кг"),
         ("length_mm", "Габаритная длина", 11022, "мм")],
        ["Масса пустой машины 102 т — округлённое значение модели, не разность полной массы и нагрузки."],
        "Caterpillar 785C, AEHQ5320-02", "PDF pp. 1, 18–19",
        "https://www.kellytractor.com/eng/images/pdf/earthmoving/offhighway_trucks/785c.pdf"),
    "cat-777d": _p(
        "Caterpillar", "CAT 777D", "AEHQ5140-02 (12-00)", "passport",
        [("payload_t", "Грузоподъёмность", 90.9, "т"),
         ("gross_kw", "Полная мощность двигателя", 746, "кВт"),
         ("flywheel_kw", "Мощность на маховике", 699, "кВт"),
         ("gmw_kg", "Предельная полная масса машины", 161000, "кг"),
         ("body_m3", "Объём кузова с шапкой (SAE 2:1)", 60.1, "м³"),
         ("tank_l", "Топливный бак", 1137, "л")],
        ["Масса пустой машины в модели 70,0 т — допущение, согласованное с полной массой: 70,0 + 90,9 ≤ 161 т.",
         "Догрузка ограничена полной массой 161 т."],
        "Caterpillar 777D, AEHQ5140-02 (12-00)", "PDF pp. 1, 18",
        "https://www.kellytractor.com/eng/images/pdf/earthmoving/offhighway_trucks/777d.pdf"),
    "hitachi-ex3600-6": _p(
        "Hitachi", "Hitachi EX3600-6", "дизель, прямая лопата", "passport",
        [("gross_kw", "Полная мощность двигателя", 1450, "кВт"),
         ("rpm", "Обороты при номинальной мощности", 1800, "об/мин"),
         ("mass_kg", "Эксплуатационная масса (прямая лопата)", 362000, "кг"),
         ("bucket_m3", "Диапазон объёмов ковшей", "21–23", "м³"),
         ("relief_mpa", "Давление предохранительных клапанов (рабочее оборудование)", 29.4, "МПа")],
        ["Не электрический EX3600E-6 и не обратная лопата. В модели ковш 21 м³."],
        "Hitachi EX3600-6 / EX3600E-6, KS-RU105P", "PDF pp. 1–2",
        "https://www.hitachicm.ru/wp-content/uploads/2017/04/EX3600-6_spec_KS-RU105P_RU.pdf"),
    "hitachi-zx870h": _p(
        "Hitachi", "Hitachi EX870 (ZAXIS 870H)", "обратная лопата", "analog",
        [("gross_kw", "Мощность двигателя (нетто)", 397, "кВт"),
         ("mass_kg", "Эксплуатационная масса", 82100, "кг"),
         ("bucket_m3", "Ковш (минимальный – максимальный)", "1.91–4.36", "м³"),
         ("dig_depth_m", "Наибольшая глубина копания", "7.14–8.87", "м")],
        ["Экскаватор EX870 указан в парке Бозшаколя в презентации визита на рудник 2015 г. (S2); исполнение не "
         "раскрыто. Значения — по модели ZAXIS 870H из сводной базы RitchieSpecs, не по документу производителя. "
         "В модели ковш 4,3 м³, работает на вскрыше Восточного карьера с CAT 777D (допущение)."],
        "RitchieSpecs: Tata Hitachi ZAXIS870H Hydraulic Excavator", "web page",
        "https://www.ritchiespecs.com/model/tata-hitachi-zaxis870h-hydraulic-excavator"),
    "cat-993k": _p(
        "Caterpillar", "CAT 993K", "Tier 2, Standard Lift", "passport",
        [("gross_kw", "Полная мощность, SAE J1995", 777, "кВт"),
         ("net_kw", "Полезная мощность, ISO 9249", 726, "кВт"),
         ("rated_t", "Номинальная нагрузка (Standard Lift)", 27.2, "т"),
         ("bucket_m3", "Диапазон объёмов ковшей", "12.2–23.7", "м³")],
        ["Ковш 12,5 м³ — допущение модели в паспортном диапазоне; каталожный номер ковша не выбран.",
         "Масса за цикл в модели ограничена номинальной нагрузкой 27,2 т."],
        "Caterpillar 993K, AEHQ6860-00", "PDF pp. 1, 20–21",
        "https://s7d2.scene7.com/is/content/Caterpillar/CM20131123-52793-53235"),
    "sandvik-d55sp": _p(
        "Sandvik", "Sandvik D55SP", "Non-Tier 4, rotary", "passport",
        [("hole_mm", "Диаметр бурения", "172–254", "мм"),
         ("single_pass_m", "Глубина за один проход", 17, "м"),
         ("max_depth_m", "Предельная общая глубина", 32, "м"),
         ("feed_kn", "Максимальное усилие подачи", 200, "кН"),
         ("bit_load_kn", "Максимальная нагрузка на долото", 232, "кН"),
         ("power_kw", "Номинальная мощность", 567, "кВт"),
         ("tank_l", "Топливный бак", 2274, "л"),
         ("air_m3min", "Расход воздуха, вращательное бурение", 45.3, "м³/мин"),
         ("air_bar", "Давление воздуха, вращательное бурение", 6.9, "бар")],
        ["Скорость бурения 48 м/ч — калибровка модели, не паспорт (скорость подачи ≠ скорость бурения породы)."],
        "Sandvik D55SP, TS2-407-01/ENG/METRIC", "PDF pp. 1–2",
        "https://www.mining.sandvik/globalassets/products/surface-drill-rigs/pdf/d55sp-specification-sheet-english.pdf"),
    "cat-777-water": _p(
        "Caterpillar", "CAT 777 (07) Bare Chassis + цистерна", "Water Tank", "analog",
        [("tank_l", "Номинальная вместимость цистерны", 75700, "л")],
        ["По презентации KAZ Minerals 2015 г. на Бозшаколе водовозы на базе CAT 777D; 777 (07) с цистерной 75 700 л — аналог с паспортной ёмкостью, ёмкость надстройки 777D не подтверждена."],
        "Cat 777 (07) Bare Chassis", "Product Specifications; Water Tank",
        "https://www.cat.com/en_US/products/new/equipment/off-highway-trucks/off-highway-trucks-bare-chassis/1000005261.html"),
    "toyota-lc79": _p(
        "Toyota", "Toyota Land Cruiser 79 (HZJ79)", "двигатель 1HZ", "candidate",
        [("power_kw", "Максимальная мощность двигателя", 96, "кВт"),
         ("rpm", "Обороты при максимальной мощности", 3800, "об/мин")],
        ["Перевозка персонала бригады и геолога. Перевозка ВВ этим автомобилем не моделируется."],
        "Toyota Gibraltar Stockholdings: Engine Technical Data", "1HZ; применимость к HZJ79",
        "https://www.toyota-gib.com/en/engines.html"),
    "metso-mkiii-60-89": _p(
        "Metso", "Metso Superior MKIII 60-89", "гирационная дробилка", "analog",
        [("power_kw", "Установленная мощность", 750, "кВт"),
         ("feed_opening_mm", "Приёмное отверстие", 1525, "мм"),
         ("mass_kg", "Масса оборудования", 365000, "кг")],
        ["По презентации KAZ Minerals 2015 г. гирационная дробилка Бозшаколя — поставки FLSmidth (модель не раскрыта); Metso MKIII 60-89 — аналог того же класса.",
         "Производительность 4600 т/ч и бункер 700 т — проектные значения модели, не паспорт дробилки.",
         "Бункер — отдельное сооружение."],
        "Metso Superior MKIII series", "Specifications, строка MKIII 60-89",
        "https://www.metso.com/pt/portfolio/britadores-giratorios-primarios/?r=3"),
    "takraf-belt": _p(
        "TAKRAF", "TAKRAF Troughed Belt Conveyor", "индивидуальное исполнение", "family",
        [("family_tph_max", "Верхняя граница производительности семейства", 50000, "т/ч")],
        ["Серийной модели нет: нужен расчёт трассы, натяжений, ширины ленты и приводов.",
         "Транспортное запаздывание в модели 2100 м / 4,5 м/с ≈ 467 с."],
        "TAKRAF Troughed Belt Conveyors", "Key Facts",
        "https://www.takraf.com/portfolio/detail/troughed-belt-conveyors/"),
    "abb-gmd-sag": _p(
        "ABB (привод)", "SAG 40 ft + ABB GMD 28 МВт", "безредукторный привод", "drive",
        [("drive_mw", "Номинальная мощность привода", 28, "МВт"),
         ("diameter_ft", "Диаметр мельницы", 40, "фут")],
        ["ABB — изготовитель привода, не всего барабана."],
        "ABB: Gearless mill drives, Aktogay and Bozshakol", "Case study",
        "https://new.abb.com/mining/grinding/gearless-mill-drives/how-to-make-remote-mines-and-low-ore-grades-economical-and-transition-mills-to-digital-operation"),
    "abb-gmd-ball": _p(
        "ABB (привод)", "Ball mill 28 ft + ABB GMD 22 МВт", "безредукторный привод", "drive",
        [("drive_mw", "Номинальная мощность привода", 22, "МВт"),
         ("diameter_ft", "Диаметр мельницы", 28, "фут")],
        ["22 МВт на каждую из двух мельниц; рабочая нагрузка модели 13 МВт (допущение)."],
        "ABB: Gearless mill drives, Aktogay and Bozshakol", "Case study",
        "https://new.abb.com/mining/grinding/gearless-mill-drives/how-to-make-remote-mines-and-low-ore-grades-economical-and-transition-mills-to-digital-operation"),
    "metso-tankcell-e300": _p(
        "Metso", "Metso TankCell e300 ×8", "линия из 8 камер", "analog",
        [("cell_m3", "Эффективный объём одной камеры", 300, "м³"),
         ("cell_kw", "Установленная мощность одной камеры", 250, "кВт"),
         ("air_m3min", "Подача воздуха на вал (факт.)", 42, "м³/мин"),
         ("air_kpa", "Избыточное давление воздуха", 65, "кПа изб."),
         ("cells", "Число камер (выбор модели)", 8, "шт"),
         ("line_m3", "Объём линии", 2400, "м³")],
        ["8 камер — выбор автора, не установленный состав фабрики.",
         "Сумма приводов не включает воздуходувки и насосы."],
        "Metso TankCell, 4789-09-22", "PDF p. 4: e300",
        "https://www.metso.com/globalassets/portfolio/brochure-tankcell-4789-09-22-en-mng-mid.pdf?r=3"),
    "metso-tankcell-e100": _p(
        "Metso", "Metso TankCell e100 ×4", "линия из 4 камер", "analog",
        [("cell_m3", "Эффективный объём одной камеры", 100, "м³"),
         ("cell_kw", "Установленная мощность одной камеры", 110, "кВт"),
         ("air_m3min", "Подача воздуха на вал (факт.)", 24, "м³/мин"),
         ("cells", "Число камер (выбор модели)", 4, "шт"),
         ("line_m3", "Объём линии", 400, "м³")],
        ["4 камеры требуют расчёта потока и времени пребывания; не паспортная конфигурация фабрики."],
        "Metso TankCell, 4789-09-22", "PDF p. 4: e100",
        "https://www.metso.com/globalassets/portfolio/brochure-tankcell-4789-09-22-en-mng-mid.pdf?r=3"),
    "ksb-rdlo": _p(
        "KSB", "KSB RDLO (насосная станция)", "семейство, 50 Гц", "family",
        [("family_q_m3h", "Предельная подача семейства", 10000, "м³/ч"),
         ("family_h_m", "Предельный напор семейства", 290, "м"),
         ("family_bar", "Предельное давление семейства", 30, "бар")],
        ["Пределы семейства не достигаются одновременно; нужны типоразмер, Q-H кривая и рабочая точка.",
         "RDLO — для воды с малым содержанием твёрдого, не для хвостовой пульпы."],
        "KSB Product Portfolio: RDLO", "Строка RDLO, 50 Hz",
        "https://live-resources-e2e-sales.ksb.com/resource/blob/326924/31c9e873a5855b3a3541d32ad88d3bfc/dow-pump-portfolio-en-data.pdf"),
    "se-pm5560": _p(
        "Schneider Electric", "PowerLogic PM5560 (учёт)", "трансформаторы ПС не выбраны", "candidate",
        [("accuracy", "Класс точности активной энергии", "0.2S", ""),
         ("eth", "Порты Ethernet", 2, "шт"),
         ("di", "Дискретные входы", 4, "шт"),
         ("do", "Дискретные выходы", 2, "шт")],
        ["Подключается через ТТ/ТН, не напрямую к 220 кВ; 220 кВ — значение проекта, паспорт трансформаторов не подтверждён.",
         "PM5560 не заменяет анализатор качества класса A: показатели ГОСТ 32144 ведёт отдельный двойник pq-01."],
        "Schneider Electric PowerLogic PM5560", "Характеристики METSEPM5560",
        "https://www.se.com/us/en/product/METSEPM5560/power-meter-powerlogic-pm5560-2-ethernet-up-to-63th-harmonic-11mb-4di-2do-52-alarms/"),
    "piusi-panther72": _p(
        "PIUSI", "PIUSI Panther 72 (пост малой техники)", "резервуары по проекту", "candidate",
        [("pump_lpm", "Номинальная подача насоса", 72, "л/мин")],
        ["Только для поста малой техники: 1514 л / 72 л/мин ≈ 21 мин без манёвров.",
         "Заправка карьерных самосвалов за 15 мин в модели — высокопроизводительный пост, модель которого не выбрана."],
        "PIUSI Panther AC", "Panther 72: 72 l/min",
        "https://www.piusi.com/products/panther-ac"),
    "konecranes-cxt": _p(
        "Konecranes", "Konecranes CXT, 20 т", "мостовой кран, здание по проекту", "family",
        [("family_t_max", "Грузоподъёмность двухбалочного семейства, макс.", 80, "т"),
         ("design_t", "Проектный выбор для узлов (не паспорт)", 20, "т")],
        ["20 т — для узлов, не для подъёма целого самосвала. Пролёт, высота и режим работы не выбраны."],
        "Konecranes CXT", "Однобалочный до 40 т, двухбалочный до 80 т",
        "https://www.konecranes.com/sites/default/files/2023-05/brochure_cxt_cranes.pdf"),
    "groundprobe-ssr-xt": _p(
        "GroundProbe / Orica", "GroundProbe SSR-XT", "радар мониторинга бортов", "passport",
        [("principle", "Принцип измерения", "интерферометрический радар", ""),
         ("accuracy", "Заявленная точность", "субмиллиметровое измерение деформаций", "")],
        ["Дальность и численная погрешность источником не подтверждены и не указываются.",
         "Пороги тревог — параметры геотехнической модели, не паспорт радара."],
        "GroundProbe SSR-XT / Orica", "Targeted slope monitoring",
        "https://www.orica.com/en/digital-solutions/geosolutions/groundprobe/slope-stability-radars/groundprobe-ssr-xt"),
    "draeger-xam8000": _p(
        "Dräger", "Dräger X-am 8000", "XXS CO LC + XXS NO2", "passport",
        [("co_range_ppm", "Диапазон CO (XXS CO LC)", "0–2000", "ppm"),
         ("co_res_ppm", "Разрешение CO", 1, "ppm"),
         ("no2_range_ppm", "Диапазон NO2 (XXS NO2)", "0–50", "ppm"),
         ("no2_res_ppm", "Разрешение NO2", 0.1, "ppm")],
        ["Переносной прибор: в модели — мобильная точка замера, которую переносят к месту взрыва, а не стационарная сеть.",
         "Показания округляются до разрешения прибора и ограничены диапазоном."],
        "Dräger X-am 8000, Product information", "Таблица датчиков XXS CO LC и XXS NO2",
        "https://www.draeger.com/Content/Documents/Products/X-am-8000-pi-100856-en.pdf"),
    "tsi-dusttrak-8543": _p(
        "TSI", "TSI DustTrak 8543", "Environmental Monitor, с нагревателем", "passport",
        [("fractions", "Измеряемые фракции", "PM1, PM2.5, респирабельная, PM10, общая пыль", ""),
         ("temp_c", "Рабочая температура с нагревателем", "-20…50", "°C"),
         ("range", "Диапазон концентраций", None, "")],
        ["Диапазон концентраций не заполнен: карточки производителя расходятся.",
         "Ниже −20 °C прибор вне рабочего диапазона: двойник выставляет флаг."],
        "TSI DustTrak Environmental Monitor 8543", "Product details",
        "https://tsi.com/outdoor-environments/products/dedicated-outdoor-monitoring-instruments/dusttrak-environmental-monitor-8543/"),
    "vaisala-wxt536": _p(
        "Vaisala", "Vaisala WXT536", "шесть погодных параметров", "passport",
        [("wind_ms", "Диапазон наблюдения скорости ветра", "0–60", "м/с"),
         ("temp_c", "Диапазон температуры", "-52…60", "°C"),
         ("rh", "Диапазон относительной влажности", "0–100", "%"),
         ("p_hpa", "Диапазон давления", "500–1100", "гПа"),
         ("supply_v", "Питание постоянного тока", "6–24", "В DC"),
         ("ip", "Защита без / с монтажным комплектом", "IP65 / IP66", "")],
        ["Диапазон выдачи ветра 75 м/с не равен диапазону наблюдения 60 м/с."],
        "Vaisala WXT530 series, B211500EN-K", "PDF p. 2, WXT536",
        "https://docs.vaisala.com/api/khub/documents/8mSgE_e9EAq~QTD3lSKELQ/content"),
    "teltonika-tmt250": _p(
        "Teltonika", "Teltonika TMT250", "GNSS + GSM трекер", "candidate",
        [("battery_mah", "Ёмкость аккумулятора", 800, "мА·ч"),
         ("battery_v", "Напряжение аккумулятора", 3.8, "В"),
         ("ip", "Защита корпуса", "IP67", "")],
        ["Демонстрационный трекинг на поверхности (нужен GSM/2G); не система предотвращения наездов, без сантиметровой точности.",
         "Метки вымышленные, данных людей нет."],
        "Teltonika TMT250 Quick Manual v1.4", "Power; ingress protection",
        "https://wiki.teltonika-gps.com/images/c/ca/QM-TMT250.pdf"),
    "metso-hrt": _p(
        "Metso", "Metso High Rate Thickener", "семейство", "family",
        [],
        ["Подтверждено семейство; размеры и привод не выбраны."],
        "Справочник оборудования ГОК, раздел «Объекты без серийного паспорта»", "", None),
    "pq-class-a": _p(
        "—", "Анализатор качества электроэнергии класса A", "модель не выбрана", "project",
        [],
        ["Функция двойника по ГОСТ 32144-2013; конкретный прибор класса A не выбран. Учётный PM5560 его не заменяет."],
        "Справочник оборудования ГОК, п. 15", "", None),
}

PROJECT_NOTE = ("Вместимость и геометрия заданы проектной документацией и моделью; "
                "это не характеристики серийной машины.")

# twin -> passport id; kinds without a serial passport get the project note.
BY_MODEL = {"CAT 785C": "cat-785c", "CAT 777D": "cat-777d",
            "Hitachi EX3600-6": "hitachi-ex3600-6", "CAT 993K": "cat-993k",
            "Hitachi EX870": "hitachi-zx870h",
            "Sandvik D55SP": "sandvik-d55sp"}
BY_TWIN = {
    "wt-01": "cat-777-water", "lv-01": "toyota-lc79", "lv-02": "toyota-lc79",
    "gc-01": "metso-mkiii-60-89", "cv-01": "takraf-belt",
    "sag-01": "abb-gmd-sag", "bm-01": "abb-gmd-ball", "bm-02": "abb-gmd-ball",
    "fl-r": "metso-tankcell-e300", "fl-c": "metso-tankcell-e100",
    "th-c": "metso-hrt", "th-t": "metso-hrt",
    "water-01": "ksb-rdlo", "ss-220": "se-pm5560", "fs-01": "piusi-panther72",
    "ws-01": "konecranes-cxt", "sr-01": "groundprobe-ssr-xt", "gm-01": "draeger-xam8000",
    "dm-01": "tsi-dusttrak-8543", "dm-02": "tsi-dusttrak-8543", "dm-03": "tsi-dusttrak-8543",
    "wx-01": "vaisala-wxt536", "pq-01": "pq-class-a",
    "p-01": "teltonika-tmt250", "p-02": "teltonika-tmt250", "p-03": "teltonika-tmt250", "p-04": "teltonika-tmt250",
}
PROJECT_KINDS = {"road", "block", "stockpile", "waste-dump", "tailings", "clay-plant"}

DOC = "docs/equipment_passports.pdf"


def passport_for(name, attrs):
    """Passport attribute for a twin, or None for twins that are not equipment."""
    pid = BY_TWIN.get(name) or BY_MODEL.get(attrs.get("model"))
    if pid:
        return {"id": pid, **PASSPORTS[pid], "document": DOC}
    if attrs.get("kind") in PROJECT_KINDS:
        return {"id": "project", "status": "project", "status_ru": STATUS_RU["project"],
                "notes": [PROJECT_NOTE], "document": DOC}
    return None


def spec(pid, key):
    return PASSPORTS[pid]["specs"][key]["value"]
