"""
Twin catalogue of the Bozshakol mine: Ditto thing ids, hierarchy (_parents),
static attributes and the feature snapshot published every tick.
"""

import json
import math

from . import params as P
from .forecast import KPI_LABELS
from .geometry import FACILITIES
from .model import CONTROL_DEFAULTS, STATE_RU, feat
from .equipment import passport_for, PASSPORTS
from . import condition as CM

NS = "kz.bozshakol"
POLICY = "default:basic_policy"

LOADER_STATE_RU = {
    "loading": "погрузка", "spotting": "установка самосвала", "waiting": "ожидание самосвала",
    "relocating": "перегон на новый блок", "starved": "нет взорванной массы", "blast_standby": "укрытие (взрыв)",
    "slope_hold": "запрет (борт)", "breakdown": "отказ", "maintenance": "ТО", "down": "остановлен (сценарий)",
}
DRILL_STATE_RU = {"drilling": "бурение", "moving": "переезд", "idle": "ожидание фронта",
                  "breakdown": "отказ", "maintenance": "ТО", "blast_standby": "укрытие (взрыв)"}
BLOCK_STATE_RU = {"planned": "запланирован", "drilling": "бурение", "drilled": "обурен", "charging": "заряжание",
                  "charged": "заряжен", "blasted": "взорван", "mining": "отработка", "depleted": "отработан"}
MATERIAL_RU = {"ore": "руда", "ore_hg": "богатая руда", "clay": "глинистая руда", "waste": "вскрыша"}
DEST_TWIN = {"crusher": "gc-01", "lg": "lg-01", "dump": "wd-01", "dump_e": "wd-02", "clay_plant": "cp-01"}
DEST_RU = {"crusher": "ККД-1", "lg": "склад забаланса", "dump": "Северный отвал", "dump_e": "Восточный отвал",
           "clay_plant": "глинистая фабрика"}
ROAD_RU = {
    "road-ramp": "Спиральный съезд 10 %", "road-faces": "Забойные заезды", "road-main": "Магистраль от выезда",
    "road-crusher": "Дорога на ККД", "road-bypass": "Объездная (юг)", "road-lg": "Дорога на склад забаланса",
    "road-dump": "Дорога на отвал", "road-service": "Сервисная (АЗС, ремзона)", "road-clay": "Дорога на глинистую фабрику",
    "road-ramp-east": "Съезд Восточного карьера 10 %", "road-east": "Дорога Восточный карьер — ККД",
    "road-dump-east": "Дорога на Восточный отвал",
}

LABELS = {
    # common
    "state": "Состояние", "state_ru": "Состояние (рус.)", "x": "X, м", "y": "Y, м", "z": "Отметка, м",
    "heading": "Курс, °", "speed": "Скорость", "health": "Индекс техсостояния (расчётный, по данным мониторинга)", "availability": "КТГ",
    "p_fail_24h": "Вероятность отказа за 24 ч", "engine_hours": "Наработка", "fuel_lph": "Расход ДТ",
    # trucks
    "frames": "Кадры прогноза для 3D-сцены (JSON)",
    # condition monitoring (sim/condition.py)
    "cm_engine_coolant": "Температура ОЖ двигателя", "cm_engine_oil_pressure": "Давление масла двигателя",
    "cm_exhaust_temp": "Температура выхлопа", "cm_transmission_oil": "Температура масла трансмиссии",
    "cm_brake_oil": "Температура масла тормозов (ретардер)", "cm_tyre_temp": "Температура шин", "cm_tyre_pressure": "Давление в шинах",
    "cm_loads": "Рейсов с грузом", "cm_overload_share": "Доля рейсов выше номинальной грузоподъёмности",
    "cm_hydraulic_oil": "Температура гидравлического масла", "cm_hydraulic_pressure": "Пиковое давление гидросистемы",
    "cm_relief_events": "Срабатывания предохранительных клапанов", "cm_vibration": "Вибрация ходовой части",
    "cm_compressor_temp": "Температура на выходе компрессора", "cm_air_pressure": "Давление воздуха (бурение)",
    "cm_oil_fe": "Анализ масла: железо", "cm_oil_si": "Анализ масла: кремний (пыль)", "cm_oil_sample_age": "Возраст пробы масла",
    "cm_codes": "Активные коды неисправностей", "cm_codes_count": "Число активных кодов", "cm_weak_point": "Слабое место (по мониторингу)",
    "link_block": "Связь: отрабатываемый блок", "link_trucks": "Связь: самосвалы, назначенные на экскаватор",
    "link_loader": "Связь: экскаватор назначения", "link_destination": "Связь: пункт разгрузки",
    "payload": "Груз", "load_grade": "Содержание Cu в кузове", "material": "Материал", "destination": "Пункт разгрузки",
    "loader": "Экскаватор", "fuel": "Топливо в баке", "trips": "Рейсов", "tonnes": "Перевезено",
    "cycle_min": "Время цикла", "queue_min": "Ожидание погрузки", "road": "Дорога", "cas": "CAS: сближение",
    # loaders
    "block": "Блок", "block_grade": "Содержание Cu в блоке", "dig_rate": "Производительность", "passes": "Циклов ковша",
    "queue": "Самосвалов в очереди", "utilization": "Использование", "cycle_s": "Цикл экскавации",
    # blocks
    "code": "Код блока", "tonnes_total": "Запас блока", "remaining": "Остаток", "cu": "Cu", "au": "Au", "clay": "Глина",
    "ucs": "Крепость (UCS)", "ucs_mwd": "Крепость по MWD", "bwi": "Индекс Бонда", "holes_total": "Скважин",
    "holes_drilled": "Обурено", "holes_charged": "Заряжено", "burden": "ЛНС (B)", "spacing": "Расст. скважин (S)",
    "powder_factor": "Удельный расход ВВ", "explosive_t": "ВВ на блок", "x50": "Средний кусок x50",
    "x80": "Кусок x80", "heading_deg": "Ориентация блока",
    # drills
    "rop": "Скорость бурения", "pulldown": "Усилие подачи", "torque": "Крутящий момент", "rpm": "Обороты",
    "specific_energy": "Удельная энергия", "ucs_est": "Крепость по MWD", "metres": "Пробурено",
    "hole": "Скважина", "progress": "Обуренность блока",
    "air_rate": "Расход воздуха",
    "alarms_active": "Активные тревоги",
    "alert": "Тревога сближения",
    "au_oz_shift": "Золото за смену",
    "avg_cycle_min": "Средний цикл рейса",
    "avg_queue_min": "Среднее ожидание погрузки",
    "bays_busy": "Занято боксов",
    "belt_speed": "Скорость ленты",
    "blast_exclusion": "Опасная зона взрыва",
    "blast_state": "Состояние взрыва",
    "blasted_stock_kt": "Взорванная горная масса",
    "blasts_total": "Взрывов всего",
    "blend_share_hg": "Доля богатой руды (SH-02)",
    "blocks_charged": "Блоков заряжено",
    "blocks_drilled": "Блоков обурено",
    "blocks_mining": "Блоков в отработке",
    "cas_alerts_shift": "Срабатывания CAS за смену",
    "circulating_load": "Циркулирующая нагрузка",
    "clay_plant_tph": "Глинистая фабрика",
    "co": "CO",
    "co2_t_h": "CO₂",
    "co2_t_shift": "CO₂ за смену",
    "conc_grade": "Cu в концентрате",
    "conc_t_shift": "Концентрат за смену",
    "conc_tph": "Выход концентрата",
    "consumption_lph": "Расход ДТ (парк)",
    "cost_kzt_h": "Стоимость э/э",
    "cost_kzt_per_t_cu": "Затраты на 1 т меди (смена)",
    "cu_plan_pct": "Выполнение плана по меди",
    "cu_t_shift": "Медь за смену",
    "cu_tph": "Медь",
    "depth_m": "Глубина карьера",
    "design_pf": "Проектный удельный расход ВВ",
    "diesel_l_shift": "ДТ самосвалов за смену",
    "diesel_lph": "Расход ДТ",
    "diesel_m3": "Запас ДТ",
    "dispatch_policy": "Алгоритм диспетчеризации",
    "dumped_kt": "Отсыпано",
    "dumps_per_h": "Разгрузок в час",
    "dust_index": "Индекс пыления",
    "events": "Журнал событий",
    "explosive_t_shift": "ВВ за смену",
    "f80": "Крупность питания F80",
    "failures_total": "Отказов всего",
    "feed_clay": "Глина в питании",
    "feed_grade": "Cu в питании",
    "feed_grade_1h": "Cu в питании (1 ч)",
    "feed_x80": "Крупность x80 в бункере",
    "fleet_availability": "КТГ самосвалов",
    "flocculant": "Расход флокулянта",
    "freeboard": "Запас высоты дамбы",
    "fresh_m3h": "Свежая вода",
    "grade": "Cu",
    "grade_target": "Целевое Cu в питании",
    "height_m": "Высота отвала",
    "high_risk_units": "Машин с риском отказа >30 %",
    "hopper_t": "Бункер",
    "horizon_h": "Горизонт прогноза",
    "hours_cover": "Запас по времени",
    "humidity": "Влажность",
    "in_band_pct": "Время в коридоре качества",
    "in_workshop": "В ремзоне",
    "kwh_per_t": "Удельный расход э/э",
    "length_km": "Длина",
    "level_kt": "Запас",
    "level_pct": "Заполнение",
    "lg_stock_kt": "Склад забаланса",
    "limit": "Норматив",
    "liner_remaining": "Остаток футеровки",
    "load_bm": "Нагрузка: ШМ",
    "load_clay_plant": "Нагрузка: глинистая фабрика",
    "load_crushing": "Нагрузка: дробление и конвейер",
    "load_flotation": "Нагрузка: флотация",
    "load_other": "Нагрузка: прочее",
    "load_sag": "Нагрузка: МПСИ",
    "load_tph": "Загрузка",
    "loaders_working": "Экскаваторов в работе",
    "m2m_dig_rate_pct": "Mine-to-Mill: скорость экскавации",
    "m2m_explosive_kzt_t": "Mine-to-Mill: затраты на ВВ",
    "m2m_holes_per_100kt": "Mine-to-Mill: скважин на 100 кт",
    "m2m_sag_tph": "Mine-to-Mill: потенциал МПСИ",
    "m2m_x80_cm": "Mine-to-Mill: x80",
    "mantle_wear": "Износ брони",
    "mill_t_shift": "Переработано за смену",
    "mill_tph": "Переработка ОФ",
    "moisture": "Увлажнение полотна",
    "moved_t_shift": "Горная масса за смену",
    "mttr_h": "Среднее время ремонта",
    "mwh_shift": "Э/э за смену",
    "nearest_truck_m": "До ближайшего самосвала",
    "next_window": "Следующее взрывное окно",
    "no2": "NO₂",
    "on_belt_t": "Руда на ленте",
    "ore_t_shift": "Руда за смену",
    "overflow_ntu": "Мутность слива",
    "p80": "Крупность продукта P80",
    "pattern": "Сетка скважин",
    "peak_mw_15": "Пиковая мощность (15 мин)",
    "peak_shaving": "Снижение нагрузки в пик",
    "people_in_pit": "Людей в карьере",
    "plume_active": "Пылевое облако",
    "plume_mass": "Интенсивность облака",
    "plume_r": "Радиус облака",
    "plume_x": "Облако X",
    "plume_y": "Облако Y",
    "pm10": "PM10",
    "pm10_max": "PM10 максимум",
    "over_range": "Показание вне диапазона прибора",
    "in_operating_range": "Прибор в рабочем диапазоне температур",
    "pocket_t": "Приёмный бункер",
    "power_kw": "Мощность",
    "power_limit_mw": "Предел мощности",
    "power_mw": "Мощность",
    "price": "Тариф",
    "product_f80": "Крупность дроблёной руды",
    "productivity_tph": "Производительность парка",
    "pump_mw": "Насосы",
    "rain": "Осадки",
    "rate_k": "Константа флотации k",
    "reactive_mvar": "Реактивная мощность",
    "reclaim_m3h": "Оборотная вода",
    "reclaim_tph": "Подача со склада",
    "recovery": "Извлечение",
    "reentry": "Допуск в зону взрыва",
    "repairs_done": "Ремонтов выполнено",
    "residence_min": "Время флотации",
    "resource_note": "Ресурсы",
    "rolling_resistance": "Сопротивление качению",
    "scenario": "Сценарий",
    "shift": "Смена",
    "sim_speed": "Ускорение модели",
    "sim_time": "Модельное время",
    "slope_level": "Устойчивость бортов",
    "speed_limit": "Ограничение скорости",
    "speed_pct_cs": "Скорость вращения",
    "status": "Статус",
    "status_code": "Код статуса",
    "stock_kt": "Запас",
    "strategy": "Стратегия ТОиР",
    "strip_ratio_shift": "Коэф. вскрыши (смена)",
    "strip_ratio_design": "Проектный коэф. вскрыши участка (допущение)",
    "ore_kt_shift": "Руда за смену", "waste_kt_shift": "Вскрыша за смену",
    "exposed_ore_kt": "Вскрытые запасы руды", "exposed_months": "Обеспеченность вскрытыми запасами",
    "ore_plan_kt_month": "План руды участка на месяц",
    "east_ore_share": "Доля руды с Восточного карьера",
    "waste_central_tph": "Вскрыша Центрального, план", "waste_east_tph": "Вскрыша Восточного, план",
    "t80": "Продукт МПСИ T80",
    "tails_grade": "Cu в хвостах",
    "tariff_zone": "Тарифная зона",
    "task": "Задача",
    "temperature": "Температура",
    "throughput": "Производительность",
    "total_mw": "Нагрузка подстанции",
    "traffic": "Интенсивность движения",
    "truck": "Самосвал под погрузкой",
    "trucks_down": "В ремонте",
    "trucks_empty": "Порожних в пути",
    "trucks_loaded": "Груженых в пути",
    "trucks_queued": "В очередях",
    "trucks_refueling": "На заправке",
    "trucks_standby": "В резерве",
    "trucks_total": "Самосвалов всего",
    "trucks_working": "Самосвалов на линии",
    "underflow_solids": "Твёрдое в сгущённом",
    "units": "Машины в боксах",
    "voltage_kv": "Напряжение",
    "volume_mm3": "Объём",
    "waste_t_shift": "Вскрыша за смену",
    "water_m3": "Вода в цистерне",
    "wind_dir": "Направление ветра",
    "wind_speed": "Скорость ветра",
    "worst_level": "Худший уровень",
    "xanthate": "Расход ксантогената",
    "zone": "Зона",
    "w1_displacement": "W1: смещение",
    "w1_level": "W1: уровень",
    "w1_ttf_h": "W1: прогноз обрушения (1/v)",
    "w1_velocity": "W1: скорость смещения",
    "w2_displacement": "W2: смещение",
    "w2_level": "W2: уровень",
    "w2_ttf_h": "W2: прогноз обрушения (1/v)",
    "w2_velocity": "W2: скорость смещения",
    "w3_displacement": "W3: смещение",
    "w3_level": "W3: уровень",
    "w3_ttf_h": "W3: прогноз обрушения (1/v)",
    "w3_velocity": "W3: скорость смещения",
    "computed_at": "Рассчитан",
    # GeoMet + ML in blocks
    "geo_source": "Источник геологии", "geo_cu_ppm": "Cu по скважинам GeoMet (ML-сетка)", "geo_fe_ppm": "Fe по GeoMet",
    "geo_s_ppm": "S по GeoMet", "geo_k_ppm": "K по GeoMet (серицит/глина)", "t10_ml": "Индекс разрушаемости t (ML)",
    "hardness_factor": "Множитель крепости (ML)",
    # real-data replay twins
    "data_source": "Источник данных", "record_time": "Время записи в датасете", "record_no": "Запись №",
    "iron_feed": "Fe в питании", "silica_feed": "SiO₂ в питании", "starch_flow": "Крахмал (депрессор)",
    "amina_flow": "Амин (собиратель)", "pulp_flow": "Расход пульпы", "pulp_ph": "pH пульпы", "pulp_density": "Плотность пульпы",
    "air_mean": "Воздух, среднее по 7 колоннам", "level_mean": "Уровень пены, среднее по 7 колоннам",
    "silica_lab": "SiO₂ конц.: последний анализ лаборатории", "silica_ml": "SiO₂ конц.: ML-оценка сейчас",
    "silica_actual": "SiO₂ конц.: факт (станет известен через 3 ч)", "ml_error": "Ошибка ML на этой записи",
    "ml_mae_24h": "Средняя ошибка ML за 24 записи", "model_r2": "R² модели на отложенных данных",
    "naive_r2": "R² наивного прогноза (последний анализ)",
    "model_mae": "MAE модели на отложенных данных", "naive_mae": "MAE наивного прогноза (последний анализ)",
    "lab_delay_h": "Задержка лабораторного анализа", "model_auc": "ROC AUC модели на отложенных сменах",
    "expert_auc": "ROC AUC экспертной оценки на тех же сменах",
    "seismic": "Сейсмическая оценка (эксперт)", "seismoacoustic": "Сейсмоакустическая оценка", "ghazard": "Итоговая оценка опасности (эксперт)",
    "genergy": "Энергия сейсмики (геофон)", "gpuls": "Импульсов (геофон)", "nbumps": "Толчков за смену", "energy": "Суммарная энергия толчков",
    "maxenergy": "Максимальная энергия толчка", "hazard_ml": "ML: вероятность опасной следующей смены",
    "alarm_ml": "ML: тревога", "hazard_actual": "Факт: следующая смена опасная", "shift_type": "Смена",
    "hits_30": "Совпадений ML с фактом за 30 смен",
    # MWD -> rock type (NGI tunnels) and fragmentation reference (El Aljibe)
    "tunnel": "Тоннель (источник данных)", "chainage_m": "Пикет цикла", "round_length": "Длина заходки",
    "penetration": "Скорость проходки (норм.)", "rotation_pressure": "Давление вращения (норм.)",
    "feed_pressure": "Давление подачи (норм.)", "hammer_pressure": "Давление ударника (норм.)", "water_flow": "Расход воды (норм.)",
    "rock_ml": "ML: порода по MWD", "rock_ml_prob": "ML: уверенность", "rock_mapped": "Факт: порода по картированию",
    "rock_prev_round": "Порода прошлого цикла (картирование)", "ml_match": "ML совпал с картированием",
    "hits_48": "Совпадений ML за 48 циклов", "model_accuracy": "Точность ML на отложенных циклах",
    "majority_accuracy": "Точность «самая частая порода»", "prev_round_accuracy": "Точность «порода прошлого цикла»",
    "accuracy_on_changes": "Точность ML на сменах породы",
    "p_mw": "Активная мощность ГОК-аналога", "q_mvar": "Реактивная мощность ГОК-аналога", "cos_phi": "cos φ ГОК-аналога",
    "p_gpp1": "ГПП-1", "p_gpp2": "ГПП-2", "p_gpp3": "ГПП-3", "p_gpp4": "ГПП-4", "p_gpp5": "ГПП-5",
    "forecast_2h": "ML: нагрузка через 2 ч", "actual_2h": "Факт: нагрузка через 2 ч", "forecast_time": "На время",
    "now_mae_24h": "Ошибка «как сейчас» за 24 ч", "now_mae": "MAE «как сейчас» на отложенных данных",
    "day_ago_mae": "MAE «как вчера в это время»", "load_factor_ref": "Коэффициент заполнения графика (аналог)",
    "cos_phi_ref": "Средний cos φ (аналог)", "bozshakol_mw": "Нагрузка Бозшаколя (модель) сейчас",
    "bozshakol_cos_phi": "cos φ Бозшаколя (модель)",
    "frag_ref_source": "Эталон фрагментации", "frag_ref_x50": "Эталон: x50 развала", "frag_ref_x80": "Эталон: x80 развала",
    "frag_ref_n": "Эталон: однородность n (Розин–Раммлер)", "frag_ref_fit_rmse": "Эталон: ошибка подгонки",
    "frag_model_x50": "Модель Kuz-Ram: x50 взорванных блоков", "frag_model_x80": "Модель Kuz-Ram: x80 взорванных блоков",
    "frag_model_n": "Модель Kuz-Ram: однородность n",
    # ГОСТ 32144-2013
    "freq_dev": "Отклонение частоты Δf", "volt_dev": "Отклонение напряжения δU", "ku": "Суммарный коэффициент гармоник K_U",
    "ku5": "Коэффициент 5-й гармоники K_U(5)", "ku7": "Коэффициент 7-й гармоники K_U(7)", "k2u": "Несимметрия K_2U",
    "pst": "Кратковременная доза фликера P_st", "plt": "Длительная доза фликера P_lt", "harmonic_filter": "ФКУ (фильтр гармоник)",
    "plan_status": "Подбор плана: состояние", "plan_options": "Варианты плана месяца", "plan_best": "Лучший вариант плана",
    "plan_computed_at": "План подобран", "plan_calc_s": "Время подбора", "plan_traj": "Вскрытые запасы по месяцам",
    "trucks_777_east": "CAT 777D на вскрыше Восточного", "plan_optimize": "Запросов подбора плана",
    "window_intervals": "Интервалов 10 мин в окне оценки", "compliance_final": "Окно оценки полное (неделя)",
    "window_coverage": "Полнота окна оценки", "ku_95_share": "Время с K_U ≤ 2,0 %", "ku_max": "K_U максимум за окно",
    "ku5_95_share": "Время с K_U(5) ≤ 1,5 %", "freq_95_share": "Время с |Δf| ≤ 0,2 Гц", "volt_max": "|δU| максимум за окно",
    "compliance": "Соответствие ГОСТ 32144-2013", "dips": "Провалов напряжения", "last_dip": "Последний провал", "violations": "Нарушения сейчас",
    # ГОСТ 14180 / 13170 / 24598
    "lot_t": "Партия (смена): руда в мельницу", "v_cu": "Коэффициент вариации Cu V", "v_source": "V определён",
    "m_point": "Масса точечной пробы m = Q·b/(3600·v)", "n_min": "Минимум точечных проб N = 4V²/Δ²", "n_points": "Принято точечных проб",
    "period_min": "Период отбора T = 60·M/(Q·N)", "combined_kg": "Объединённая проба", "homogeneity": "Категория однородности (табл. 4)",
    "k_hom": "Коэффициент K", "m_min_10": "Мин. масса после сокращения при 10 мм (K·d²)", "m_min_3": "Мин. масса после сокращения при 3 мм",
    "n_conc": "Точечных проб от партии концентрата (V 5 %, Δ 1,1 %)", "shift_closed": "Последняя закрытая смена",
    "assay_feed": "Анализ: Cu в питании", "assay_conc": "Анализ: Cu в концентрате", "assay_tails": "Анализ: Cu в хвостах",
    "eps_lab": "Извлечение по 3 продуктам ε = c(f−t)/(f(c−t))", "eps_plant": "Извлечение по данным фабрики",
    "balance_gap": "Невязка баланса", "w_conc": "Влага концентрата (ГОСТ 13170)", "w_conc_d1": "Влага конц.: 1-е определение",
    "w_conc_d2": "Влага конц.: 2-е определение", "w_tol": "Допустимое расхождение (п. 4.2)", "w_repeated": "Было повторное определение",
    "w_ore": "Влага руды (ГОСТ 13170)", "conc_wet_t": "Концентрат за смену во влажной массе", "conc_dry_t": "Концентрат за смену, сухая масса",
    "sieve_minus_008": "Класс −0,08 мм (ГОСТ 24598)", "sieve_minus_004": "Класс −0,04 мм (седиментация)",
    "sieve_plus_0224": "Класс +0,224 мм", "sieve_q_min": "Мин. масса пробы q = 0,02d² + 0,5d",
    "calc_s": "Время расчёта",
}


def tid(name):
    return f"{NS}:{name}"


# ---------------------------------------------------------------------------
# OpenTwins types
# ---------------------------------------------------------------------------
# The original OpenTwins architecture separates *types* (templates, things
# with attributes._isType = true) from *twins* (instances, which carry the
# constant attribute ``type`` = the type's thingId). A type's _parents is a
# map {parent type: how many instances}, so instantiating the site type in
# the OpenEgiz app (Types -> Create twin) would create the whole mine.
TYPE_NS = f"{NS}.types"

KIND_RU = {
    "site": "ГОК (горно-обогатительный комбинат)", "area": "Участок", "control": "Пульт сценариев",
    "forecast": "Прогноз «что если»", "loader": "Выемочно-погрузочная машина", "block": "Взрывной блок",
    "slope-radar": "Радар мониторинга бортов", "gas-monitor": "Газоанализатор", "dust-monitor": "Пылемер",
    "road": "Карьерная дорога", "drill": "Буровой станок", "haul-truck": "Карьерный самосвал",
    "water-truck": "Поливочная машина", "light-vehicle": "Лёгкий автомобиль", "stockpile": "Склад руды",
    "waste-dump": "Отвал вскрыши", "crusher": "Дробилка", "conveyor": "Конвейер", "sag-mill": "Мельница ПСИ (SAG)",
    "ball-mill": "Шаровая мельница", "flotation": "Флотационная секция", "thickener": "Сгуститель",
    "tailings": "Хвостохранилище", "clay-plant": "Глинистая фабрика", "water": "Водовод",
    "substation": "Подстанция", "fuel-station": "АЗС и склад ГСМ", "workshop": "Ремонтная зона",
    "weather": "Метеостанция", "personnel": "Метка персонала",
    "analyzer": "Онлайн-анализатор качества", "seismic-station": "Сейсмостанция",
    "laboratory": "Лаборатория ОТК", "mwd-analyzer": "Классификатор пород по MWD", "energy-profile": "Энергопрофиль (реальные данные)", "power-quality-meter": "Анализатор качества электроэнергии",
}

# Attributes that differ per instance and therefore stay out of the type.
INSTANCE_ATTRS = {"relations", "relations_in", "flow_graph", "relation_types", "dataset", "ml_model", "standards", "name", "_isType", "_parents", "type", "section", "area", "geo", "layout", "catalog", "feature_labels",
                  "control_defaults", "sectors", "loader", "face", "bench_m", "role", "note", "footprint_m",
                  "pit_shells", "strip_ratio_design"}


def _slug(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def type_slug(attrs, name=None):
    """Type of a twin: its kind, refined by the equipment model when there is one.
    Every area twin is a type of its own: each area aggregates different KPIs."""
    kind = attrs["kind"]
    model = attrs.get("model")
    if kind == "area" and name:
        return f"area-{name}"
    return f"{kind}-{_slug(model)}" if model else kind


def type_id(slug):
    return f"{TYPE_NS}:{slug}"


def build_things(mine):
    """Every twin as a Ditto thing body, parents first: {thingId: body}."""
    cat = catalogue(mine)
    snap = snapshot(mine, {**whatif_features(None, "расчёт", "базовый режим"), **plan_features(None, "нет")})
    things = {}
    for name in ["site"] + [n for n in cat if n != "site"]:
        attrs = cat[name]
        features = control_features() if name == "control" else \
            {k: {"properties": v} for k, v in snap.get(name, {}).items()}
        things[tid(name)] = {"policyId": POLICY, "attributes": attrs, "features": features}
    return things


def build_types(things):
    """OpenTwins types derived from the twins: {typeId: body}, the site type first."""
    groups = {}
    for body in things.values():
        groups.setdefault(body["attributes"]["type"], []).append(body)
    site_type = things[tid("site")]["attributes"]["type"]
    out = {}
    for type_thing in [site_type] + sorted(t for t in groups if t != site_type):
        members = groups[type_thing]
        first = members[0]["attributes"]
        kind, model = first["kind"], first.get("model")
        title = first["name"] if kind == "area" else f"{KIND_RU.get(kind, kind)}{' ' + model if model else ''}"
        attrs = {"name": title,
                 "kind": kind, "_isType": True,
                 "text_description": f"Тип OpenTwins для двойников вида «{kind}» ГОК «Бозшаколь»; экземпляров: {len(members)}"}
        for k, v in first.items():
            if k not in INSTANCE_ATTRS and k not in attrs and all(m["attributes"].get(k) == v for m in members):
                attrs[k] = v
        if type_thing != site_type:
            attrs["_parents"] = {site_type: len(members)}
        # Relation schema of the type: which types its instances link to (OpenTwins-style typed links).
        type_of = {tid_: b["attributes"]["type"] for tid_, b in things.items()}
        schema = {}
        for mbr in members:
            for rel in mbr["attributes"].get("relations", []):
                key = (rel["type"], "out", type_of.get(rel["to"]))
                schema[key] = rel["label"]
            for rel in mbr["attributes"].get("relations_in", []):
                key = (rel["type"], "in", type_of.get(rel["from"]))
                schema[key] = rel["label"]
        if schema:
            attrs["relation_schema"] = [{"type": t, "direction": d, "label": lab, "with_type": wt}
                                        for (t, d, wt), lab in sorted(schema.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or ""))]
        features = {}
        for m in members:
            for fname, f in m["features"].items():
                props = f.get("properties", {})
                features.setdefault(fname, {"properties": {"value": None, **({"unit": props["unit"]} if "unit" in props else {})}})
        out[type_thing] = {"policyId": POLICY, "attributes": attrs, "features": features}
    return out


def r(v, n=1):
    return round(float(v), n)


# ---------------------------------------------------------------------------
# Relations between twins (explicit graph)
# ---------------------------------------------------------------------------
REL_RU = {
    "feeds": "поставляет материал", "water": "подаёт воду", "power": "питает электроэнергией",
    "fuel": "заправляет дизтопливом", "maintains": "обслуживает и ремонтирует", "monitors": "контролирует",
    "samples": "опробует", "digs": "отрабатывает блок", "analog_of": "реальные данные аналога для",
    "scenario": "задаёт сценарий",
}


def relation_edges(cat):
    """Static edges (source, type, target) between twin names; dynamic links
    (truck -> loader -> block, drill -> block) are features of the twins."""
    E = []
    names = set(cat)
    kinds = {n: a["kind"] for n, a in cat.items()}
    by_kind = lambda *k: sorted(n for n, kk in kinds.items() if kk in k)

    def add(src, rel, dst):
        if src in names and dst in names:
            E.append((src, rel, dst))
    # material flow: faces -> crusher / dump / clay plant -> concentrator -> concentrate and tailings
    for n in ("sh-01", "sh-02"):
        add(n, "feeds", "gc-01")
    add("sh-03", "feeds", "wd-01")
    add("sh-04", "feeds", "gc-01")
    add("ex-01", "feeds", "wd-02")
    add("ld-01", "feeds", "cp-01")
    add("lg-01", "feeds", "gc-01")
    for a, b in (("gc-01", "cv-01"), ("cv-01", "cos-01"), ("cos-01", "sag-01"), ("sag-01", "bm-01"), ("sag-01", "bm-02"),
                 ("bm-01", "fl-r"), ("bm-02", "fl-r"), ("fl-r", "fl-c"), ("fl-c", "th-c"), ("fl-r", "th-t"),
                 ("th-t", "tsf-01"), ("cp-01", "th-c"), ("cp-01", "tsf-01")):
        add(a, "feeds", b)
    for b in by_kind("block"):
        loader = cat[b].get("loader")
        if loader:
            add(loader, "digs", b)
    # water
    add("water-01", "water", "sag-01")
    add("water-01", "water", "cp-01")
    add("tsf-01", "water", "sag-01")
    add("th-t", "water", "fl-r")
    # electric power from the 220 kV substation
    for n in ("gc-01", "cv-01", "sag-01", "bm-01", "bm-02", "fl-r", "fl-c", "th-c", "th-t", "cp-01", "water-01", "ws-01", "lab-01"):
        add("ss-220", "power", n)
    # diesel (the EX3600-6 shovels are diesel too)
    for n in by_kind("haul-truck", "water-truck", "loader", "drill", "light-vehicle"):
        add("fs-01", "fuel", n)
    for n in by_kind("haul-truck", "water-truck", "loader", "drill"):
        add("ws-01", "maintains", n)
    # monitoring and sampling
    for a, b in (("sr-01", "pit-central"), ("gm-01", "drill-blast"), ("dm-01", "pit-central"), ("dm-02", "gc-01"),
                 ("wx-01", "haulage"), ("pq-01", "ss-220"), ("lab-01", "cos-01"), ("lab-01", "fl-r"), ("lab-01", "fl-c"),
                 ("lab-01", "th-c"), ("lab-01", "th-t")):
        add(a, "monitors" if not a.startswith("lab") else "samples", b)
    # twins that replay real data of other operations next to their Bozshakol counterpart
    for a, b in (("qc-01", "fl-r"), ("mwd-01", "drill-blast"), ("en-01", "ss-220"), ("sm-01", "pit-central")):
        add(a, "analog_of", b)
    add("control", "scenario", "whatif")
    return E


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def catalogue(mine):
    """name -> attributes.

    The hierarchy is flat, as in the platform's Example Mine: every twin is a
    direct child of the site (attributes._parents = kz.bozshakol:site), so the
    OpenEgiz app lists all equipment on the site's Children tab. The functional
    section (area twin) a twin belongs to is kept as the plain attribute
    ``section`` and the
    OpenTwins type it instantiates as ``type`` (see types_catalogue()).
    """
    c = {}

    def add(name, section, kind, title, **attrs):
        a = {"name": title, "kind": kind, "_isType": False}
        if name != "site":
            a["_parents"] = tid("site")
        if section and section != "site":
            a["section"] = section
        a.update(attrs)
        c[name] = a

    add("site", None, "site", "ГОК «Бозшаколь» (цифровой двойник)",
        operator="KAZ Minerals (открытые данные)", region="Павлодарская обл., Казахстан",
        description="Центральный и Восточный карьеры + сульфидная обогатительная фабрика 25 Мт/год + глинистая фабрика 5 Мт/год",
        layout=mine.net.layout())
    areas = {
        "pit-central": ("area", "Центральный карьер"),
        "pit-east": ("area", "Восточный карьер"),
        "drill-blast": ("area", "Участок буровзрывных работ"),
        "haulage": ("area", "Автотранспорт и диспетчерская"),
        "geology": ("area", "Геология и шихтовка"),
        "concentrator": ("area", "Обогатительная фабрика"),
        "energy": ("area", "Энергохозяйство"),
        "maintenance": ("area", "Служба ТОиР"),
        "safety": ("area", "Промышленная безопасность"),
        "control": ("control", "Пульт сценариев «что если»"),
    }
    for name, (kind, title) in areas.items():
        add(name, "site", kind, title)
    if P.PIT_SHELLS:
        common = {k: P.PIT_SHELLS[k] for k in ("method", "status", "block_m", "slope_deg", "economics")}
        for pit, g in P.PITS.items():
            c[f"pit-{pit}"]["pit_shells"] = {**common, **P.PIT_SHELLS["pits"][pit]}
            c[f"pit-{pit}"]["strip_ratio_design"] = g["strip_t_t"]
    for ld in mine.loaders.values():
        add(ld.id, f"pit-{ld.pit}", "loader", f"{'Экскаватор' if ld.model.startswith('Hitachi') else 'Погрузчик'} "
            f"{ld.id.upper()} ({ld.model})", model=ld.model, bucket_m3=ld.spec["bucket"],
            face=ld.spec["area"], bench_m=-P.BENCH_H * ld.spec["bench"], serves=f"CAT {ld.spec['serves']}")
    for b in mine.blocks:
        add(f"blk-{b.slot:02d}", f"pit-{mine.loaders[b.loader].pit}", "block", f"Взрывной блок, слот {b.slot:02d}",
            area=mine.loaders[b.loader].spec["area"], loader=b.loader, footprint_m=[100, 60])
    add("sr-01", "pit-central", "slope-radar", "Радар мониторинга бортов SR-01 (GroundProbe SSR-XT)", model="GroundProbe SSR-XT",
        geo=list(FACILITIES["radar"]), sectors=[{"id": s["id"], "geo": [r(v) for v in s["pos"]]} for s in mine.radar])
    add("gm-01", "pit-central", "gas-monitor", "Переносной газоанализатор GM-01 (Dräger X-am 8000), точка замера у взрыва",
        model="Dräger X-am 8000", mobile=True)
    add("dm-01", "pit-central", "dust-monitor", "Пылемер DM-01 (TSI DustTrak 8543), дно карьера", geo=list(FACILITIES["dm-01"]),
        model="TSI DustTrak 8543")
    for road in ("road-ramp", "road-faces"):
        add(road, "pit-central", "road", ROAD_RU[road])
    add("road-ramp-east", "pit-east", "road", ROAD_RU["road-ramp-east"])
    for d in mine.drills:
        add(d.id, "drill-blast", "drill", f"Буровой станок {d.id.upper()} (Sandvik D55SP)", model="Sandvik D55SP",
            hole_mm=P.HOLE_D_M * 1000)
    for t in mine.trucks:
        add(t.id, "haulage", "haul-truck", f"Самосвал {t.id.upper()} ({t.model})", model=t.model,
            payload_t=t.cap, power_kw=t.p_kw, tank_l=t.tank, empty_t=t.empty, max_load_t=r(t.max_load, 1))
    add("wt-01", "haulage", "water-truck", "Поливочная машина WT-01 (CAT 777 (07) + цистерна 75,7 м³)",
        model="CAT 777 (07) + цистерна", tank_m3=P.WATER_TRUCK_M3)
    add("lv-01", "haulage", "light-vehicle", "Автомобиль бригады взрывников LV-01 (Toyota Land Cruiser 79), без ВВ",
        model="Toyota Land Cruiser 79")
    add("lv-02", "haulage", "light-vehicle", "Автомобиль геолога LV-02 (Toyota Land Cruiser 79)", model="Toyota Land Cruiser 79")
    for road in ("road-main", "road-crusher", "road-bypass", "road-lg", "road-dump", "road-service", "road-clay",
                 "road-east", "road-dump-east"):
        add(road, "haulage", "road", ROAD_RU[road])
    add("lg-01", "geology", "stockpile", "Склад забалансовой руды", geo=list(FACILITIES["lg"]))
    add("wd-01", "geology", "waste-dump", "Северный отвал вскрыши (CWD), Центральный карьер", geo=list(FACILITIES["dump"]))
    add("wd-02", "geology", "waste-dump", "Восточный отвал вскрыши (EWD), Восточный карьер", geo=list(FACILITIES["dump_e"]))
    plant = {
        "gc-01": ("crusher", "Гирационная дробилка ККД-1 (Metso Superior MKIII 60-89)", "crusher"),
        "cv-01": ("conveyor", "Магистральный конвейер CV-01, 2,1 км (TAKRAF, на заказ)", "cos"),
        "cos-01": ("stockpile", "Склад крупнодроблёной руды", "cos"),
        "sag-01": ("sag-mill", "Мельница ПСИ (SAG) 40 фут, ABB GMD 28 МВт", "sag"),
        "bm-01": ("ball-mill", "Шаровая мельница ШМ-1 28 фут, ABB GMD 22 МВт", "bm-01"),
        "bm-02": ("ball-mill", "Шаровая мельница ШМ-2 28 фут, ABB GMD 22 МВт", "bm-02"),
        "fl-r": ("flotation", "Основная/контрольная флотация (8 × Metso TankCell e300)", "flot_r"),
        "fl-c": ("flotation", "Перечистная флотация (4 × Metso TankCell e100)", "flot_c"),
        "th-c": ("thickener", "Сгуститель концентрата (Metso High Rate)", "th_c"),
        "th-t": ("thickener", "Сгуститель хвостов (Metso High Rate)", "th_t"),
        "tsf-01": ("tailings", "Хвостохранилище", "tsf"),
        "cp-01": ("clay-plant", "Глинистая фабрика 5 Мт/год", "clay_plant"),
        "water-01": ("water", "Водовод от канала им. Сатпаева (насосная KSB RDLO)", "water"),
    }
    plant_models = {"gc-01": "Metso Superior MKIII 60-89", "cv-01": "TAKRAF Troughed Belt Conveyor",
                    "sag-01": "SAG 40 ft + ABB GMD 28 MW", "bm-01": "Ball mill 28 ft + ABB GMD 22 MW",
                    "bm-02": "Ball mill 28 ft + ABB GMD 22 MW", "fl-r": "Metso TankCell e300 x8",
                    "fl-c": "Metso TankCell e100 x4", "th-c": "Metso High Rate Thickener",
                    "th-t": "Metso High Rate Thickener", "water-01": "KSB RDLO"}
    for name, (kind, title, fac) in plant.items():
        extra = {"model": plant_models[name]} if name in plant_models else {}
        add(name, "concentrator", kind, title, geo=list(FACILITIES[fac]), **extra)
    add("ss-220", "energy", "substation", "Подстанция 220 кВ (от Экибастузской ГРЭС-1), учёт PowerLogic PM5560",
        geo=list(FACILITIES["substation"]), model="Schneider PowerLogic PM5560")
    add("fs-01", "energy", "fuel-station", "АЗС и склад ГСМ: пост самосвалов + пост малой техники (PIUSI Panther 72)", geo=list(FACILITIES["fuel"]),
        tank_m3=400, model="High-flow + PIUSI Panther 72")
    add("ws-01", "maintenance", "workshop", "Ремонтная зона (4 бокса, кран Konecranes CXT 20 т)", geo=list(FACILITIES["workshop"]),
        bays=P.WORKSHOP_BAYS, model="Konecranes CXT")
    add("wx-01", "safety", "weather", "Метеостанция WX-01 (Vaisala WXT536)", geo=list(FACILITIES["weather"]), model="Vaisala WXT536")
    add("dm-02", "safety", "dust-monitor", "Пылемер DM-02 (TSI DustTrak 8543), ККД", geo=list(FACILITIES["dm-02"]),
        model="TSI DustTrak 8543")
    add("dm-03", "safety", "dust-monitor", "Пылемер DM-03 (TSI DustTrak 8543), вахтовый посёлок", geo=list(FACILITIES["dm-03"]),
        model="TSI DustTrak 8543")
    add("qc-01", "concentrator", "analyzer", "Анализатор качества флотации QC-01 (реальные данные + ML)",
        geo=list(FACILITIES["qc"]), dataset="Quality Prediction in a Mining Process (Kaggle, CC0)", ml_model="GBM, ml/models/flotation_silica.json")
    add("lab-01", "concentrator", "laboratory", "Лаборатория ОТК: опробование и анализы (ГОСТ 14180, 13170, 24598)",
        geo=list(FACILITIES["lab"]), standards="ГОСТ 14180-80; ГОСТ 13170-80; ГОСТ 24598-81")
    add("pq-01", "energy", "power-quality-meter", "Анализатор качества электроэнергии ПС 220 кВ (ГОСТ 32144-2013)",
        geo=list(FACILITIES["pq"]), standards="ГОСТ 32144-2013, сеть 110–220 кВ")
    add("en-01", "energy", "energy-profile", "Энергопрофиль ГОК-аналога EN-01 (реальные данные + ML-прогноз нагрузки)",
        geo=list(FACILITIES["en"]), dataset="Energy consumption data of a mining and processing plant (Zenodo 20647907, CC BY-SA 4.0)",
        ml_model="GBM, прогноз нагрузки на 2 ч, ml/models/energy_load.json")
    add("mwd-01", "drill-blast", "mwd-analyzer", "Классификатор пород по MWD MWD-01 (реальные данные + ML)",
        geo=list(FACILITIES["mwd"]), dataset="MWD + породы, 15 тоннелей Норвегии (NGI, Zenodo 10358374, CC BY 4.0)",
        ml_model="GBM, 10 классов, ml/models/mwd_rocktype.json")
    add("sm-01", "safety", "seismic-station", "Сейсмостанция SM-01 (реальные данные + ML)",
        geo=list(FACILITIES["seis"]), dataset="seismic-bumps (UCI, CC BY 4.0)", ml_model="GBM-классификатор, ml/models/seismic_hazard.json")
    for pid, p in mine.people.items():
        add(pid, "safety", "personnel", f"Метка персонала {pid.upper()} (Teltonika TMT250): {p['role']}", role=p["role"],
            model="Teltonika TMT250", note="Вымышленная метка роли, без персональных данных")
    add("whatif", "control", "forecast", "Прогноз «что если» на 48 ч (база vs сценарий)",
        kpi_labels={k: {"label": v[0], "unit": v[1]} for k, v in KPI_LABELS.items()})
    for n, a in c.items():
        a["type"] = type_id(type_slug(a, n))
        pas = passport_for(n, a)
        if pas:
            a["passport"] = pas
    edges = relation_edges(c)
    for n, a in c.items():
        out = [{"type": rel, "label": REL_RU[rel], "to": tid(dst)} for src, rel, dst in edges if src == n]
        inc = [{"type": rel, "label": REL_RU[rel], "from": tid(src)} for src, rel, dst in edges if dst == n]
        if out:
            a["relations"] = out
        if inc:
            a["relations_in"] = inc
    c["site"]["flow_graph"] = {"relation_types": REL_RU, "edges": [[src, rel, dst] for src, rel, dst in edges]}
    c["site"]["catalog"] = [{"id": n, "name": a["name"], "kind": a["kind"], "type": a["type"],
                             "parent": a.get("_parents", "").split(":")[-1] or None,
                             "section": a.get("section"), **({"model": a["model"]} if a.get("model") else {}),
                             **({"passport": a["passport"]["id"]} if a.get("passport") else {})} for n, a in c.items()]
    c["site"]["feature_labels"] = LABELS
    c["site"]["control_defaults"] = dict(CONTROL_DEFAULTS)
    return c


def control_features():
    return {k: {"properties": {"value": v}} for k, v in CONTROL_DEFAULTS.items()}


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
def _pos(f, p, heading=None):
    f["x"] = feat(r(p[0]), "м")
    f["y"] = feat(r(p[1]), "м")
    f["z"] = feat(r(p[2]), "м")
    if heading is not None:
        f["heading"] = feat(r(heading), "°")


def _blast_state(m):
    if m.blast is None:
        return "нет"
    return "эвакуация" if m.blast["phase"] == "clearing" else "проветривание"


def snapshot(m, forecast=None):
    s = {}
    k = m.shift_kpi
    e = m.energy
    sag, f, c, cos = m.sag, m.flot, m.crusher, m.cos
    hours_shift = max(k["feed_s"] / 3600, 0.05)
    trucks = m.trucks
    working = [t for t in trucks if t.state not in ("in_workshop", "breakdown", "towing", "parked", "to_park")]
    alarms = sum(1 for x in m.radar if x["level"] != "green") + (1 if m.blast else 0) + \
        sum(1 for t in trucks if t.state == "breakdown") + (1 if c["state"] in ("down", "mantle_change") else 0) + \
        sum(1 for v in m.dust.values() if v > 150)
    cost = k["el_cost"] + k["diesel_all_l"] * P.DIESEL_KZT_PER_L + k["explosive_kg"] * P.EXPLOSIVE_KZT_PER_KG
    recent = [ev for ev in list(m.events)[:25]]
    s["site"] = {
        "sim_time": feat(m.now.strftime("%Y-%m-%d %H:%M")),
        "shift": feat(m.shift_id),
        "sim_speed": feat(int(m.control["sim_speed"]), "x"),
        "scenario": feat(m.control["preset"]),
        "mill_tph": feat(r(sag["tph"]), "т/ч"),
        "feed_grade": feat(r(cos["cu"], 3), "% Cu"),
        "recovery": feat(r(f["rec"] * 100), "%"),
        "cu_tph": feat(r(f["cu_tph"] + m.clay_plant["cu_tph"], 2), "т/ч"),
        "cu_t_shift": feat(r(k["cu_t"]), "т"),
        "cu_plan_pct": feat(r(k["cu_t"] / (hours_shift * 10.7) * 100 if k["feed_s"] else 0), "%"),
        "au_oz_shift": feat(r(k["au_oz"]), "унц"),
        "moved_t_shift": feat(r(k["moved_t"]), "т"),
        "ore_t_shift": feat(r(k["ore_t"]), "т"),
        "waste_t_shift": feat(r(k["waste_t"]), "т"),
        "power_mw": feat(r(e["mw"]), "МВт"),
        "kwh_per_t": feat(r(k["mwh"] * 1000 / k["mill_t"] if k["mill_t"] else 0), "кВт·ч/т"),
        "diesel_lph": feat(r(e.get("diesel_lph", 0)), "л/ч"),
        "cost_kzt_per_t_cu": feat(r(cost / k["cu_t"] if k["cu_t"] > 1 else 0, 0), "₸/т"),
        "co2_t_shift": feat(r(k["co2_t"]), "т"),
        "fleet_availability": feat(r(sum(t.avail for t in trucks) / len(trucks) * 100), "%"),
        "trucks_working": feat(len(working), "шт"),
        "alarms_active": feat(alarms, "шт"),
        "events": feat(json.dumps(recent, ensure_ascii=False)),
    }
    # Areas -------------------------------------------------------------------------
    ready = sum(b.remaining for b in m.blocks if b.state in ("blasted", "mining"))
    for pit, g in P.PITS.items():
        lds = [ld for ld in m.loaders.values() if ld.pit == pit]
        ids = {ld.id for ld in lds}
        st = m.pits[pit]
        ore_s, waste_s = k[f"ore_t_{pit}"], k[f"waste_t_{pit}"]
        s[f"pit-{pit}"] = {
            "loaders_working": feat(sum(1 for ld in lds if ld.state in ("loading", "spotting", "waiting")), "шт"),
            "blasted_stock_kt": feat(r(sum(b.remaining for b in m.blocks if b.loader in ids
                                           and b.state in ("blasted", "mining")) / 1000), "кт"),
            "blocks_mining": feat(sum(1 for b in m.blocks if b.loader in ids and b.state == "mining"), "шт"),
            "depth_m": feat(P.BENCH_H * g["n"], "м"),
            "strip_ratio_shift": feat(r(waste_s / ore_s, 2) if ore_s > 0 else 0.0, "т/т"),
            "strip_ratio_design": feat(g["strip_t_t"], "т/т"),
            "ore_kt_shift": feat(r(ore_s / 1000), "кт"),
            "waste_kt_shift": feat(r(waste_s / 1000), "кт"),
            "exposed_ore_kt": feat(r(st["exposed_t"] / 1000, 0), "кт"),
            "exposed_months": feat(r(m.exposed_months(pit), 2), "мес"),
            "ore_plan_kt_month": feat(r(m.pit_plan_month_t(pit) / 1000, 0), "кт"),
        }
    charged = [b for b in m.blocks if b.state == "charged"]
    pf = float(m.control["powder_factor"])
    m2m = mine_to_mill(pf)
    nxt = None
    for w in P.BLAST_WINDOWS:
        if m.hour() < w:
            nxt = f"{int(w):02d}:{int(w % 1 * 60):02d}"
            break
    s["drill-blast"] = {
        "blast_state": feat(_blast_state(m)),
        "next_window": feat(nxt or f"{int(P.BLAST_WINDOWS[0]):02d}:00 (завтра)"),
        "blocks_charged": feat(len(charged), "шт"),
        "blocks_drilled": feat(sum(1 for b in m.blocks if b.state == "drilled"), "шт"),
        "blasts_total": feat(m.blasts, "шт"),
        "explosive_t_shift": feat(r(k["explosive_kg"] / 1000), "т"),
        "design_pf": feat(r(pf, 2), "кг/м³"),
        "pattern": feat(f"{m2m['burden']:.1f}×{m2m['spacing']:.1f} м"),
        "m2m_x80_cm": feat(r(m2m["x80"] * 100), "см"),
        "m2m_dig_rate_pct": feat(r(m2m["dig_pct"]), "%"),
        "m2m_sag_tph": feat(r(m2m["sag_tph"], 0), "т/ч"),
        "m2m_holes_per_100kt": feat(r(m2m["holes_100kt"]), "скв"),
        "m2m_explosive_kzt_t": feat(r(m2m["kzt_t"]), "₸/т"),
    }
    s["drill-blast"].update(fragmentation_features(m))
    in_ws = len(m.workshop["bays"])
    s["haulage"] = {
        "trucks_total": feat(len(trucks), "шт"),
        "trucks_loaded": feat(sum(1 for t in trucks if t.state == "hauling"), "шт"),
        "trucks_empty": feat(sum(1 for t in trucks if t.state == "to_loader"), "шт"),
        "trucks_queued": feat(sum(1 for t in trucks if t.state in ("queue_loader", "queue_dump")), "шт"),
        "trucks_down": feat(sum(1 for t in trucks if t.state in ("breakdown", "towing", "in_workshop")), "шт"),
        "trucks_standby": feat(sum(1 for t in trucks if t.state in ("standby", "parked", "to_reserve")), "шт"),
        "avg_cycle_min": feat(r(m.kpi["cycle_min_sum"] / m.kpi["cycles"] if m.kpi["cycles"] else 0), "мин"),
        "avg_queue_min": feat(r(m.kpi["queue_min_sum"] / m.kpi["queue_n"] if m.kpi["queue_n"] else 0), "мин"),
        "dispatch_policy": feat(m.control["dispatch_policy"]),
        "speed_limit": feat(int(m.control["speed_limit_kmh"]), "км/ч"),
        "productivity_tph": feat(r(k["moved_t"] / hours_shift if k["feed_s"] else 0, 0), "т/ч"),
        "diesel_l_shift": feat(r(k["diesel_l"]), "л"),
    }
    fg = m._feed_grade_1h()
    s["geology"] = {
        "grade_target": feat(r(float(m.control["grade_target"]), 3), "% Cu"),
        "feed_grade_1h": feat(r(fg, 3), "% Cu"),
        "in_band_pct": feat(r(k["inband_s"] / k["feed_s"] * 100 if k["feed_s"] else 100), "%"),
        "blend_share_hg": feat(r(getattr(m, "blend_x", 0.3) * 100), "%"),
        "lg_stock_kt": feat(r(m.lg_stock["t"] / 1000), "кт"),
        "resource_note": feat("1,22 млрд т при 0,36 % Cu; Au 5,25 млн унц (S3)"),
    }
    s["concentrator"] = {
        "throughput": feat(r(sag["tph"]), "т/ч"),
        "recovery": feat(r(f["rec"] * 100), "%"),
        "cu_tph": feat(r(f["cu_tph"], 2), "т/ч"),
        "conc_tph": feat(r(f["conc_tph"]), "т/ч"),
        "conc_grade": feat(r(f["conc_grade"]), "% Cu"),
        "p80": feat(r(m.p80), "мкм"),
        "clay_plant_tph": feat(r(m.clay_plant["tph"]), "т/ч"),
        "mill_t_shift": feat(r(k["mill_t"]), "т"),
    }
    zone, price = m.tariff()
    s["energy"] = {
        "power_mw": feat(r(e["mw"]), "МВт"),
        "tariff_zone": feat({"night": "ночь", "day": "день", "peak": "пик"}[zone]),
        "price": feat(price, "₸/кВт·ч"),
        "cost_kzt_h": feat(r(e.get("cost_h", 0), 0), "₸/ч"),
        "peak_mw_15": feat(r(e["peak_mw"]), "МВт"),
        "mwh_shift": feat(r(k["mwh"]), "МВт·ч"),
        "diesel_lph": feat(r(e.get("diesel_lph", 0)), "л/ч"),
        "co2_t_h": feat(r(e.get("co2_h", 0), 2), "т/ч"),
        "peak_shaving": feat(bool(m.control["peak_shaving"])),
    }
    ws = m.workshop
    risky = sum(1 for t in trucks if t.p_fail_24h_est() > 0.3)
    s["maintenance"] = {
        "strategy": feat(m.control["maintenance_strategy"]),
        "in_workshop": feat(in_ws, "шт"),
        "queue": feat(len(ws["queue"]), "шт"),
        "repairs_done": feat(ws["done"], "шт"),
        "mttr_h": feat(r(ws["mttr_sum"] / ws["done"] if ws["done"] else 0), "ч"),
        "fleet_availability": feat(r(sum(t.avail for t in trucks) / len(trucks) * 100), "%"),
        "failures_total": feat(int(sum(t.failures for t in trucks) + sum(x.failures for x in m.loaders.values())
                                   + sum(d.failures for d in m.drills)), "шт"),
        "high_risk_units": feat(risky, "шт"),
    }
    worst = max(m.radar, key=lambda x: x["v"])
    s["safety"] = {
        "cas_alerts_shift": feat(int(k["cas_alerts"]), "шт"),
        "blast_exclusion": feat(m.blast is not None),
        "reentry": feat("разрешён" if m.gas["status"] == "open" else "запрещён"),
        "pm10_max": feat(r(max(m.dust.values())), "мкг/м³"),
        "slope_level": feat({"green": "норма", "amber": "жёлтый", "red": "красный"}[worst["level"]]),
        "plume_active": feat(m.plume is not None),
        "plume_x": feat(r(m.plume["x"]) if m.plume else 0.0, "м"),
        "plume_y": feat(r(m.plume["y"]) if m.plume else 0.0, "м"),
        "plume_r": feat(r(m.plume.get("r", 60)) if m.plume else 0.0, "м"),
        "plume_mass": feat(r(m.plume["mass"]) if m.plume else 0.0, "у.е."),
        "people_in_pit": feat(sum(1 for p in m.people.values() if p["pos"][2] < -5), "чел."),
    }
    # Loaders --------------------------------------------------------------------------
    for ld in m.loaders.values():
        fs = {
            "state": feat(ld.state), "state_ru": feat(LOADER_STATE_RU.get(ld.state, ld.state)),
            "block": feat(ld.block.code if ld.block else "—"),
            "block_grade": feat(r(ld.block.cu, 3) if ld.block else 0.0, "% Cu"),
            "material": feat(MATERIAL_RU[ld.material]),
            "queue": feat(sum(1 for t in ld.queue if t.state == "queue_loader" and t.loader == ld.id), "шт"),
            "truck": feat(ld.truck.id if ld.truck else "—"),
            # dynamic links (thing ids): the block being dug and the trucks dispatched to this loader
            "link_block": feat(tid(f"blk-{ld.block.slot:02d}") if ld.block else ""),
            "link_trucks": feat(",".join(tid(t.id) for t in trucks if t.loader == ld.id)),
            "passes": feat(ld.passes, "шт"),
            "tonnes": feat(r(ld.tonnes, 0), "т"),
            "utilization": feat(r(ld.busy_s / ld.total_s * 100 if ld.total_s else 0), "%"),
            "availability": feat(r(ld.avail * 100), "%"),
            "p_fail_24h": feat(r(ld.p_fail_24h_est() * 100), "%"), "fuel_lph": feat(r(ld.lph), "л/ч"),
            "engine_hours": feat(r(ld.engine_h, 0), "мч"),
        }
        heading = 0.0
        if ld.truck is not None:
            heading = math.degrees(math.atan2(ld.truck.pos[1] - ld.pos[1], ld.truck.pos[0] - ld.pos[0]))
        _pos(fs, ld.pos, heading)
        fs.update(CM.features(CM.ensure(ld, "loader", m), "loader", feat, r))
        s[ld.id] = fs
    # Blocks -----------------------------------------------------------------------------
    for b in m.blocks:
        ex, ey = b.spur.point_at(min(b.spur.length, b.dist + 1))[:2]
        fs = {
            "code": feat(b.code), "state": feat(b.state), "state_ru": feat(BLOCK_STATE_RU[b.state]),
            "loader": feat(b.loader), "material": feat(MATERIAL_RU[b.material]),
            "tonnes_total": feat(r(b.tonnes, 0), "т"), "remaining": feat(r(b.remaining, 0), "т"),
            "cu": feat(r(b.cu, 3), "%"), "au": feat(r(b.au, 3), "г/т"), "clay": feat(r(b.clay * 100), "%"),
            "ucs": feat(r(b.ucs), "МПа"), "ucs_mwd": feat(r(b.ucs_mwd) if b.ucs_mwd else 0.0, "МПа"),
            "bwi": feat(r(b.bwi, 2), "кВт·ч/т"), "holes_total": feat(b.holes_total, "шт"),
            "holes_drilled": feat(int(b.holes_drilled), "шт"), "holes_charged": feat(int(b.holes_charged), "шт"),
            "burden": feat(r(b.burden, 2), "м"), "spacing": feat(r(b.spacing, 2), "м"),
            "powder_factor": feat(r(b.pf, 2), "кг/м³"), "explosive_t": feat(r(b.explosive_kg / 1000, 2), "т"),
            "x50": feat(r(b.x50 * 100) if b.x50 else 0.0, "см"), "x80": feat(r(b.x80 * 100) if b.x80 else 0.0, "см"),
            "heading_deg": feat(r(math.degrees(math.atan2(ey - b.pos[1], ex - b.pos[0]))), "°"),
        }
        if b.geo:
            a = b.geo["assay"]
            fs.update({
                "geo_source": feat("GeoMet (Zenodo 7051975) → ML-сетка, уровень откалиброван на Бозшаколь"),
                "geo_cu_ppm": feat(r(a["Cu ppm"], 0), "ppm"), "geo_fe_ppm": feat(r(a["Fe ppm"], 0), "ppm"),
                "geo_s_ppm": feat(r(a["S ppm"], 0), "ppm"), "geo_k_ppm": feat(r(a["K ppm"], 0), "ppm"),
                "t10_ml": feat(r(b.geo["t_index"], 3)), "hardness_factor": feat(r(b.geo["hard"], 3), "×"),
            })
        _pos(fs, b.pos)
        s[f"blk-{b.slot:02d}"] = fs
    # Drills -------------------------------------------------------------------------------
    for d in m.drills:
        fs = {
            "state": feat(d.state), "state_ru": feat(DRILL_STATE_RU.get(d.state, d.state)),
            "block": feat(d.block.code if d.block else "—"),
            "link_block": feat(tid(f"blk-{d.block.slot:02d}") if d.block else ""),
            "progress": feat(r(d.block.holes_drilled / d.block.holes_total * 100) if d.block else 0.0, "%"),
            "rop": feat(r(d.rop if d.state == "drilling" else 0.0), "м/ч"),
            "pulldown": feat(r(d.pulldown if d.state == "drilling" else 0.0), "кН"),
            "torque": feat(r(d.torque if d.state == "drilling" else 0.0, 2), "кН·м"),
            "rpm": feat(90 if d.state == "drilling" else 0, "об/мин"),
            "specific_energy": feat(r(d.se if d.state == "drilling" else 0.0), "МДж/м³"),
            "ucs_est": feat(r(d.ucs_est if d.state == "drilling" else 0.0), "МПа"),
            "metres": feat(r(d.metres, 0), "м"),
            "availability": feat(r(d.avail * 100), "%"),
            "p_fail_24h": feat(r(d.p_fail_24h_est() * 100), "%"), "fuel_lph": feat(r(d.lph), "л/ч"),
        }
        _pos(fs, d.pos)
        fs.update(CM.features(CM.ensure(d, "drill", m), "drill", feat, r))
        s[d.id] = fs
    # Trucks -----------------------------------------------------------------------------------
    for t in trucks:
        fs = {
            "state": feat(t.state), "state_ru": feat(STATE_RU.get(t.state, t.state)),
            "speed": feat(r(t.v), "км/ч"), "payload": feat(r(t.payload), "т"),
            "load_grade": feat(r(t.grade, 3), "% Cu"),
            "material": feat(MATERIAL_RU.get(t.mat, "—") if t.mat else "—"),
            "destination": feat(DEST_RU.get(t.dest, "—") if t.dest else "—"),
            "loader": feat(t.loader or "—"),
            "link_loader": feat(tid(t.loader) if t.loader else ""),
            "link_destination": feat(tid(DEST_TWIN[t.dest]) if t.dest in DEST_TWIN else ""),
            "fuel": feat(r(t.fuel / t.tank * 100), "%"), "fuel_lph": feat(r(t.lph), "л/ч"),
            "availability": feat(r(t.avail * 100), "%"),
            "p_fail_24h": feat(r(t.p_fail_24h_est() * 100), "%"), "engine_hours": feat(r(t.engine_h, 0), "мч"),
            "trips": feat(t.trips, "шт"), "tonnes": feat(r(t.tonnes, 0), "т"),
            "cycle_min": feat(r(t.last_cycle), "мин"), "queue_min": feat(r(t.last_queue), "мин"),
            "road": feat(t.edge or "—"), "cas": feat(bool(t.cas)),
        }
        _pos(fs, t.pos, t.heading)
        fs.update(CM.features(CM.ensure(t, "truck", m), "truck", feat, r))
        s[t.id] = fs
    w = m.wt
    fs = {"state": feat(w.state), "speed": feat(r(w.v), "км/ч"), "water_m3": feat(r(w.water), "м³"),
          "road": feat(w.edge or "—")}
    _pos(fs, w.pos, w.heading)
    s["wt-01"] = fs
    for lid, lv in m.lvs.items():
        pos = getattr(lv, "park", None) or lv.pos
        fs = {"state": feat(lv.state), "speed": feat(r(lv.v if lv.state == "driving" else 0), "км/ч"),
              "task": feat("заряжание / взрыв" if lid == "lv-01" else "опробование забоев")}
        _pos(fs, pos, lv.heading)
        s[lid] = fs
    # Roads -------------------------------------------------------------------------------------
    for rid, rd in m.roads.items():
        edges = [e for e in m.net.edges.values() if e.road == rid]
        base_rr = sum(e.rr for e in edges) / len(edges)
        s[rid] = {
            "status": feat({"open": "открыта", "closed": "закрыта", "restricted": "ограничение 15 км/ч"}[rd["status"]]),
            "status_code": feat(rd["status"]),
            "moisture": feat(r(rd["moisture"] * 100), "%"),
            "rolling_resistance": feat(r((base_rr + rd["rr_add"]) * 100, 2), "%"),
            "traffic": feat(r(rd["traffic"] * 30, 1), "маш/ч"),
            "length_km": feat(r(sum(e.length for e in edges) / 1000, 2), "км"),
            "dust_index": feat(r(rd["traffic"] * (1 - 0.85 * rd["moisture"]) * 100), "у.е."),
        }
    s["lg-01"] = {"stock_kt": feat(r(m.lg_stock["t"] / 1000), "кт"), "grade": feat(r(m.lg_stock["cu"], 3), "% Cu"),
                  "clay": feat(r(m.lg_stock["clay"] * 100), "%"), "reclaim_tph": feat(r(c["reclaim"]), "т/ч")}
    s["wd-01"] = {"dumped_kt": feat(r(m.dump_t / 1000), "кт"), "height_m": feat(r(30 + m.dump_t / 2e6, 2), "м")}
    s["wd-02"] = {"dumped_kt": feat(r(m.dump_e_t / 1000), "кт"), "height_m": feat(r(20 + m.dump_e_t / 1e6, 2), "м")}
    # Plant -----------------------------------------------------------------------------------------
    s["gc-01"] = {
        "state": feat(c["state"]), "throughput": feat(r(c["tph"]), "т/ч"), "pocket_t": feat(r(c["pocket"]), "т"),
        "feed_x80": feat(r(c["lot"]["x80"] * 100), "см"),
        "product_f80": feat(r(135.0 * (c["lot"]["x80"] / 0.7) ** 0.6), "мм"),
        "mantle_wear": feat(r(c["wear"]), "%"),
        "power_kw": feat(r(e["breakdown"].get("ККД-1", 0) * 1000), "кВт"),
        "trucks_queued": feat(sum(1 for t in trucks if t.dest == "crusher" and t.state == "queue_dump"), "шт"),
        "dumps_per_h": feat(len(c["dumps"]), "шт/ч"),
        "feed_grade": feat(r(c["lot"]["cu"], 3), "% Cu"),
    }
    on_belt = sum(t for _, t, _ in m.conveyor)
    s["cv-01"] = {"load_tph": feat(r(m.conv_tph), "т/ч"), "on_belt_t": feat(r(on_belt), "т"),
                  "belt_speed": feat(P.CONVEYOR_SPEED if on_belt > 0 else 0.0, "м/с"),
                  "power_kw": feat(r(e["breakdown"].get("Конвейер", 0) * 1000), "кВт")}
    s["cos-01"] = {"level_kt": feat(r(cos["t"] / 1000), "кт"),
                   "level_pct": feat(r(cos["t"] / P.COS_TOTAL_T * 100), "%"),
                   "grade": feat(r(cos["cu"], 3), "% Cu"), "clay": feat(r(cos["clay"] * 100), "%"),
                   "bwi": feat(r(cos["bwi"], 2), "кВт·ч/т"), "f80": feat(r(cos["f80"]), "мм"),
                   "hours_cover": feat(r(cos["t"] / max(sag["tph"], 1)), "ч")}
    s["sag-01"] = {"state": feat(sag["state"]), "throughput": feat(r(sag["tph"]), "т/ч"),
                   "power_mw": feat(r(sag["power"], 2), "МВт"), "specific_energy": feat(r(sag["e"], 2), "кВт·ч/т"),
                   "speed_pct_cs": feat(r(sag["speed"]), "% Nкр"), "f80": feat(r(cos["f80"]), "мм"),
                   "t80": feat(r(sag["t80"], 0), "мкм"), "liner_remaining": feat(r(sag["liner"]), "%"),
                   "power_limit_mw": feat(r(P.SAG_DRAW_MAX * (0.8 if m.control["peak_shaving"] and zone == "peak"
                                                                else 1.0), 1), "МВт")}
    for b in m.bm:
        s[b["id"]] = {"state": feat(b["state"] if sag["tph"] > 300 else "idle"),
                      "power_mw": feat(r(b["power"], 2), "МВт"), "p80": feat(r(m.p80), "мкм"),
                      "circulating_load": feat(r(250 + 30 * (sag["tph"] / 3150 - 1)), "%")}
    s["fl-r"] = {"recovery": feat(r(f["rec"] * 100), "%"), "rate_k": feat(r(f["k"], 3), "1/мин"),
                 "residence_min": feat(r(f["tau"]), "мин"), "feed_grade": feat(r(cos["cu"], 3), "% Cu"),
                 "tails_grade": feat(r(f["tails_cu"], 3), "% Cu"), "air_rate": feat(r(f["air"], 2), "м/мин"),
                 "feed_clay": feat(r(cos["clay"] * 100), "%")}
    s["fl-c"] = {"conc_grade": feat(r(f["conc_grade"]), "% Cu"), "conc_tph": feat(r(f["conc_tph"]), "т/ч"),
                 "cu_tph": feat(r(f["cu_tph"], 2), "т/ч"), "xanthate": feat(r(f["xanthate"]), "г/т")}
    th = m.thick
    s["th-c"] = {"underflow_solids": feat(r(th["c_ud"]), "%"), "conc_t_shift": feat(r(k["cu_t"] / 0.22), "т")}
    s["th-t"] = {"underflow_solids": feat(r(th["t_ud"]), "%"), "overflow_ntu": feat(r(th["ntu"]), "NTU"),
                 "flocculant": feat(r(th["floc"]), "г/т")}
    s["tsf-01"] = {"volume_mm3": feat(r(m.tsf["volume"] / 1e6, 3), "млн м³"), "freeboard": feat(r(m.tsf["freeboard"], 3), "м"),
                   "reclaim_m3h": feat(r(m.tsf["reclaim"]), "м³/ч")}
    cp = m.clay_plant
    s["cp-01"] = {"throughput": feat(r(cp["tph"]), "т/ч"), "hopper_t": feat(r(cp["hopper"]), "т"),
                  "feed_grade": feat(r(cp["lot"]["cu"], 3), "% Cu"), "feed_clay": feat(r(cp["lot"]["clay"] * 100), "%"),
                  "recovery": feat(r(cp["rec"] * 100), "%"), "cu_tph": feat(r(cp["cu_tph"], 2), "т/ч"),
                  "power_mw": feat(r(e["breakdown"].get("Глинистая фабрика", 0), 2), "МВт")}
    s["water-01"] = {"fresh_m3h": feat(r(m.water["fresh"]), "м³/ч"), "reclaim_m3h": feat(r(m.water["reclaim"]), "м³/ч"),
                     "pump_mw": feat(r(e["breakdown"].get("Водовод", 0), 2), "МВт")}
    br = e["breakdown"]
    s["ss-220"] = {"total_mw": feat(r(e["mw"], 2), "МВт"), "reactive_mvar": feat(r(e.get("mvar", 0), 2), "Мвар"),
                   "voltage_kv": feat(r(220 - 0.05 * e["mw"] + 0.8 * math.sin(m.t / 900), 1), "кВ"),
                   "peak_mw_15": feat(r(e["peak_mw"], 2), "МВт"),
                   "load_sag": feat(r(br.get("МПСИ", 0), 2), "МВт"),
                   "load_bm": feat(r(br.get("ШМ-1", 0) + br.get("ШМ-2", 0), 2), "МВт"),
                   "load_flotation": feat(r(br.get("Флотация", 0), 2), "МВт"),
                   "load_crushing": feat(r(br.get("ККД-1", 0) + br.get("Конвейер", 0), 2), "МВт"),
                   "load_clay_plant": feat(r(br.get("Глинистая фабрика", 0), 2), "МВт"),
                   "load_other": feat(r(br.get("Насосы и сгустители", 0) + br.get("Водовод", 0) +
                                        br.get("Вспомогательные", 0), 2), "МВт"),
                   "tariff_zone": feat({"night": "ночь", "day": "день", "peak": "пик"}[zone])}
    s["fs-01"] = {"diesel_m3": feat(r(m.fuel_tank), "м³"),
                  "trucks_refueling": feat(sum(1 for t in trucks if t.state == "refueling"), "шт"),
                  "consumption_lph": feat(r(e.get("diesel_lph", 0)), "л/ч")}
    units = ", ".join(f"{j['truck'].id.upper()}({ {'repair': 'ремонт', 'pm': 'ТО', 'pdm': 'ТОпс'}[j['kind']] })"
                      for j in ws["bays"]) or "—"
    s["ws-01"] = {"bays_busy": feat(in_ws, "шт"), "queue": feat(len(ws["queue"]), "шт"), "units": feat(units),
                  "repairs_done": feat(ws["done"], "шт"),
                  "mttr_h": feat(r(ws["mttr_sum"] / ws["done"] if ws["done"] else 0), "ч")}
    wx = m.wx
    s["wx-01"] = {"temperature": feat(r(min(60.0, max(-52.0, wx["temp"]))), "°C"),
                  "wind_speed": feat(r(min(60.0, wx["wind"])), "м/с"),
                  "wind_dir": feat(r(wx["wind_dir"], 0), "°"), "rain": feat(r(wx["rain"]), "мм/ч"),
                  "humidity": feat(r(wx["humidity"]), "%")}
    rad = {"worst_level": feat(worst["level"])}
    for sec in m.radar:
        p = sec["id"].lower()
        rad[f"{p}_velocity"] = feat(r(sec["v"], 2), "мм/сут")
        rad[f"{p}_displacement"] = feat(r(sec["disp"], 2), "мм")
        rad[f"{p}_level"] = feat(sec["level"])
        rad[f"{p}_ttf_h"] = feat(r(sec["ttf"]), "ч")
    s["sr-01"] = rad
    g = m.gas
    # Dräger X-am 8000: CO 0-2000 ppm, resolution 1; NO2 0-50 ppm, resolution 0.1 (passport).
    gm = {"co": feat(int(round(min(2000.0, max(0.0, g["co"])))), "ppm"),
          "no2": feat(r(min(50.0, max(0.0, g["no2"])), 1), "ppm"), "status": feat(g["status"]),
          "over_range": feat(g["co"] > 2000 or g["no2"] > 50)}
    _pos(gm, g["pos"])
    s["gm-01"] = gm
    for mid, v in m.dust.items():
        s[mid] = {"pm10": feat(r(v), "мкг/м³"), "limit": feat(150, "мкг/м³"),
                  "in_operating_range": feat(m.wx["temp"] >= P.DUST_MIN_TEMP_C)}
    for pid, p in m.people.items():
        near = min((math.dist(p["pos"], t.pos) for t in trucks), default=999)
        fs = {"zone": feat("карьер" if p["pos"][2] < -5 else "поверхность"),
              "nearest_truck_m": feat(r(near), "м"), "alert": feat(near < 22)}
        _pos(fs, p["pos"])
        s[pid] = fs
    if forecast is not None:
        s["whatif"] = forecast
    realdata_features(m, s)
    standards_features(m, s)
    return s


def mine_to_mill(pf):
    """Steady-state effect of the powder factor on the chain (design block,
    UCS 118 MPa): pattern, x80, dig rate, SAG throughput, explosive cost."""
    col = (P.BENCH_H + P.SUBDRILL - P.STEMMING) * math.pi / 4 * P.HOLE_D_M ** 2 * P.EXPLOSIVE_DENSITY * 1000
    q = 0.9 * col
    area = q / (pf * P.BENCH_H)
    burden = math.sqrt(area / 1.15)
    ucs = 118.0
    a = 3.0 + 0.05 * ucs
    x50 = a * pf ** -0.8 * q ** (1 / 6) * (115.0 / P.EXPLOSIVE_RWS) ** (19 / 30) / 100
    x80 = x50 * (math.log(5) / math.log(2)) ** (1 / 1.35)
    dig0 = 0.75 + 0.30
    dig = 0.75 + 0.30 * x80 / 0.7
    f80 = 135.0 * (x80 / 0.7) ** 0.6
    e = 7.9 * (14.8 / 14.5) ** 0.9 * (f80 / 135.0) ** 0.45 * (1 + 0.35 * 0.05)
    sag = min(P.SAG_DRAW_MAX * 1000 / e, 4300.0)
    holes_100kt = 1e5 / 2.68 / (area * P.BENCH_H)
    return {"burden": burden, "spacing": 1.15 * burden, "x80": x80, "dig_pct": dig0 / dig * 100,
            "sag_tph": sag, "holes_100kt": holes_100kt, "kzt_t": pf / 2.68 * P.EXPLOSIVE_KZT_PER_KG}


def whatif_features(result, status, scenario_label):
    fs = {"status": feat(status), "scenario": feat(scenario_label), "horizon_h": feat(48, "ч")}
    if result and result.get("ok"):
        fs["computed_at"] = feat(result["at"][:16].replace("T", " "))
        fs["calc_s"] = feat(r(result.get("calc_s", 0), 1), "с")
        if result.get("frames"):
            # spatial consequences, drawn on the 3D scene (one compact JSON string per forecast)
            fs["frames"] = feat(json.dumps(result["frames"], ensure_ascii=False, separators=(",", ":")))
        b, sc = result["baseline"], result["scenario"]
        # Six-month exposed-ore trajectories of both pits, base and scenario (for the plan panel).
        fs["plan_traj"] = feat(json.dumps({"base": {p: b.get(f"traj_{p}") for p in P.PITS},
                                           "scen": {p: sc.get(f"traj_{p}") for p in P.PITS},
                                           "min_months": 1.5}, separators=(",", ":")))
        for key, (label, unit) in KPI_LABELS.items():
            fs[f"base_{key}"] = feat(r(b.get(key, 0), 2), unit)
            fs[f"scen_{key}"] = feat(r(sc.get(key, 0), 2), unit)
            base = b.get(key, 0)
            fs[f"delta_{key}"] = feat(r((sc.get(key, 0) - base) / abs(base) * 100 if abs(base) > 1e-9 else 0.0, 1), "%")
    return fs


def plan_features(result, status):
    """Auto-selected monthly plan: every candidate allocation with its month and
    six-month outcome, the best one flagged (sim/forecast.py, Planner)."""
    fs = {"plan_status": feat(status)}
    if result and result.get("ok"):
        fs["plan_computed_at"] = feat(result["at"][:16].replace("T", " "))
        fs["plan_calc_s"] = feat(r(result.get("calc_s", 0), 1), "с")
        fs["plan_options"] = feat(json.dumps({"options": result["options"], "min_months": result["min_months"],
                                              "ore_share": result["ore_share"], "any_feasible": result.get("any_feasible", True)},
                                             ensure_ascii=False, separators=(",", ":")))
        best = next(o for o in result["options"] if o["best"])
        fs["plan_best"] = feat(best["name"])
        fs["plan_feasible"] = feat(bool(result.get("any_feasible", True)))
    elif result and not result.get("ok"):
        fs["plan_error"] = feat(str(result.get("error"))[:200])
    return fs


def fragmentation_features(m):
    """Kuz-Ram of the twin vs a drone-measured muckpile (El Aljibe, Zenodo 10666378)."""
    from . import ml as ML
    if not ML.available("fragmentation_ref"):
        return {}
    ref = ML.load("fragmentation_ref")["blasts"]
    if not ref:
        return {}
    name, b = sorted(ref.items())[0]
    blasted = [x for x in m.blocks if x.x50]
    x50 = sum(x.x50 for x in blasted) / len(blasted) * 1000 if blasted else 0.0
    x80 = sum(x.x80 for x in blasted) / len(blasted) * 1000 if blasted else 0.0
    return {
        "frag_ref_source": feat(f"дрон-фотограмметрия развала, карьер El Aljibe, взрыв {name[4:]} (Zenodo 10666378, CC BY 4.0)"),
        "frag_ref_x50": feat(b["x50_mm_measured"], "мм"), "frag_ref_x80": feat(b["x80_mm_measured"], "мм"),
        "frag_ref_n": feat(b["rr_n"]), "frag_ref_fit_rmse": feat(r(b["rr_rmse"] * 100, 2), "п.п."),
        "frag_model_x50": feat(r(x50, 0), "мм"), "frag_model_x80": feat(r(x80, 0), "мм"),
        "frag_model_n": feat(1.35),
    }


def realdata_features(m, s):
    """qc-01 and sm-01: real records replayed with live ML inference (sim/realdata.py)."""
    from . import ml as ML
    rd = m.realdata
    if rd.ok_flot and rd.flot_last:
        mm = ML.load("flotation_silica")["metrics"]
        L = rd.flot_last
        row, x = L["row"], L["x"]
        s["qc-01"] = {
            "data_source": feat("Kaggle: Quality Prediction in a Mining Process (CC0), отложенная тестовая часть"),
            "record_time": feat(row["hour"]), "record_no": feat(rd.flot_i),
            "iron_feed": feat(r(row["iron_feed"], 2), "% Fe"), "silica_feed": feat(r(row["silica_feed"], 2), "% SiO₂"),
            "starch_flow": feat(r(row["starch_flow"], 0), "м³/ч"), "amina_flow": feat(r(row["amina_flow"], 0), "м³/ч"),
            "pulp_flow": feat(r(row["pulp_flow"], 0), "т/ч"), "pulp_ph": feat(r(row["pulp_ph"], 2)),
            "pulp_density": feat(r(row["pulp_density"], 3), "кг/см³"),
            "air_mean": feat(r(sum(row[f"air_{i}"] for i in range(1, 8)) / 7, 0), "Нм³/ч"),
            "level_mean": feat(r(sum(row[f"level_{i}"] for i in range(1, 8)) / 7, 0), "мм"),
            "silica_lab": feat(r(x["silica_lab"], 2), "%"), "silica_ml": feat(r(L["pred"], 2), "%"),
            "silica_actual": feat(r(row["silica_conc"], 2), "%"), "ml_error": feat(r(L["err"], 2), "п.п."),
            "ml_mae_24h": feat(r(sum(rd.flot_err) / max(1, len(rd.flot_err)), 3), "п.п."),
            "model_r2": feat(mm["r2"]), "naive_r2": feat(mm["r2_naive"]), "model_mae": feat(mm["mae"], "п.п."), "naive_mae": feat(mm["mae_naive"], "п.п."),
            "lab_delay_h": feat(mm["lab_delay_h"], "ч"),
        }
    if rd.ok_seis and rd.seis_last:
        mm = ML.load("seismic_hazard")["metrics"]
        L = rd.seis_last
        row = L["row"]
        from .realdata import LEVEL_RU
        hits = sum(1 for a, b in rd.seis_hits if a == b)
        s["sm-01"] = {
            "data_source": feat("UCI: seismic-bumps (CC BY 4.0), отложенные последние 20 % смен"),
            "record_no": feat(rd.seis_i), "shift_type": feat("ночная/ремонтная" if row["shift"] == "N" else "добычная"),
            "seismic": feat(LEVEL_RU[row["seismic"]]), "seismoacoustic": feat(LEVEL_RU[row["seismoacoustic"]]),
            "ghazard": feat(LEVEL_RU[row["ghazard"]]),
            "genergy": feat(r(float(row["genergy"]), 0), "Дж"), "gpuls": feat(int(float(row["gpuls"])), "шт"),
            "nbumps": feat(int(float(row["nbumps"])), "шт"), "energy": feat(r(float(row["energy"]), 0), "Дж"),
            "maxenergy": feat(r(float(row["maxenergy"]), 0), "Дж"),
            "hazard_ml": feat(r(L["p"] * 100, 1), "%"), "alarm_ml": feat(bool(L["alarm"])),
            "hazard_actual": feat(bool(L["actual"])), "hits_30": feat(hits, "из " + str(len(rd.seis_hits))),
            "model_auc": feat(mm["roc_auc_holdout"]), "expert_auc": feat(mm["roc_auc_expert_holdout"]),
        }
    if rd.ok_en and rd.en_last:
        mm = ML.load("energy_load")["metrics"]
        L = rd.en_last
        row = L["row"]
        p, q = row["P_MW"], row["Q_Mvar"]
        e = m.energy
        mw, mvar = e["mw"], e.get("mvar", 0.0)
        s["en-01"] = {
            "data_source": feat("ГОК-аналог (5 главных подстанций), январь и июнь 2019, Zenodo 20647907 (CC BY-SA 4.0), отложенные 25 % получасов"),
            "record_time": feat(f"{row['date']} {row['time']}"),
            "p_mw": feat(r(p, 1), "МВт"), "q_mvar": feat(r(q, 1), "Мвар"), "cos_phi": feat(r(p / max(1e-6, (p * p + q * q) ** 0.5), 3)),
            **{f"p_gpp{g}": feat(r(row[f"P_GPP{g}_MW"], 1), "МВт") for g in range(1, 6) if f"P_GPP{g}_MW" in row},
            "forecast_2h": feat(r(L["pred"], 1), "МВт"), "actual_2h": feat(r(L["actual"], 1), "МВт"),
            "forecast_time": feat(L["target_time"]),
            "ml_mae_24h": feat(r(sum(rd.en_err) / max(1, len(rd.en_err)), 2), "МВт"),
            "now_mae_24h": feat(r(sum(rd.en_err_now) / max(1, len(rd.en_err_now)), 2), "МВт"),
            "model_mae": feat(mm["mae_mw"], "МВт"), "now_mae": feat(mm["mae_now_mw"], "МВт"), "day_ago_mae": feat(mm["mae_day_ago_mw"], "МВт"),
            "load_factor_ref": feat(mm["load_factor"]), "cos_phi_ref": feat(mm["cos_phi"]),
            "bozshakol_mw": feat(r(mw, 1), "МВт"),
            "bozshakol_cos_phi": feat(r(mw / max(1e-6, (mw * mw + mvar * mvar) ** 0.5), 3)),
        }
    if rd.ok_mwd and rd.mwd_last:
        from .realdata import ROCK_RU
        mm = ML.load("mwd_rocktype")["metrics"]
        L = rd.mwd_last
        row = L["row"]
        f = lambda k, n=2: r(float(row[k]), n)
        s["mwd-01"] = {
            "data_source": feat("NGI: MWD + картирование пород, 15 тоннелей Норвегии (Zenodo 10358374, CC BY 4.0), отложенные 25 % циклов"),
            "tunnel": feat(row["Tunnel"]), "chainage_m": feat(r(float(row["PegStart"]) % 100000, 0), "м"),
            "round_length": feat(f("round_length", 1), "м"),
            "penetration": feat(f("PenetrNormMean"), "норм."), "rotation_pressure": feat(f("RotaPressNormMean"), "норм."),
            "feed_pressure": feat(f("FeedPressNormMean"), "норм."), "hammer_pressure": feat(f("HammerPressNormMean"), "норм."),
            "water_flow": feat(f("WaterFlowNormMean"), "норм."),
            "rock_ml": feat(ROCK_RU.get(L["rock"], L["rock"])), "rock_ml_prob": feat(r(L["p"] * 100, 0), "%"),
            "rock_mapped": feat(ROCK_RU.get(row["Rock"], row["Rock"])),
            "rock_prev_round": feat(ROCK_RU.get(L["prev"], L["prev"]) if L["prev"] else "—"),
            "ml_match": feat(L["rock"] == row["Rock"]),
            "hits_48": feat(sum(rd.mwd_hits), "из " + str(len(rd.mwd_hits))),
            "model_accuracy": feat(r(mm["accuracy"] * 100, 1), "%"),
            "majority_accuracy": feat(r(mm["accuracy_majority"] * 100, 1), "%"),
            "prev_round_accuracy": feat(r(mm["accuracy_previous_round"] * 100, 1), "%"),
            "accuracy_on_changes": feat(r(mm["accuracy_on_changes"] * 100, 1), "%"),
        }


def standards_features(m, s):
    """pq-01 (ГОСТ 32144-2013) and lab-01 (ГОСТ 14180, 13170, 24598)."""
    pq = m.pq
    c = pq.compliance()
    cur = pq.cur
    fs = {
        "freq_dev": feat(r(cur["freq"], 3), "Гц"), "volt_dev": feat(r(cur["volt"], 2), "%"),
        "ku": feat(r(cur["ku"], 2), "%"), "ku5": feat(r(cur["ku5"], 2), "%"), "ku7": feat(r(cur["ku7"], 2), "%"),
        "k2u": feat(r(cur["k2u"], 2), "%"), "pst": feat(r(cur["pst"], 2)),
        "plt": feat(r(c.get("plt_max", cur["pst"]), 2)),
        "harmonic_filter": feat("включена" if m.control.get("harmonic_filter", True) else "ОТКЛЮЧЕНА"),
        "dips": feat(pq.dips, "шт"),
        "last_dip": feat(f"{pq.last_dip[0]} % · {pq.last_dip[1]} с" if pq.last_dip else "нет"),
        "violations": feat(", ".join(pq.violation) if pq.violation else "нет"),
        "window_intervals": feat(c.get("n", 0), "из 1008"),
    }
    if c.get("n"):
        fs.update({
            "ku_95_share": feat(r(c["ku_95"], 1), "%"), "ku_max": feat(r(c["ku_max"], 2), "%"),
            "ku5_95_share": feat(r(c["ku5_95"], 1), "%"), "freq_95_share": feat(r(c["freq_95"], 1), "%"),
            "volt_max": feat(r(c["volt_max"], 2), "%"),
            "compliance": feat(("соответствует" if c["ok"] else "НЕ соответствует") if c["complete"] else
                               f"предварительно ({c['n']} из 1008 интервалов): "
                               + ("в нормах" if c["ok"] else "есть нарушения")),
            "compliance_final": feat(bool(c["complete"])),
            "window_coverage": feat(r(c["coverage_pct"], 1), "%"),
        })
    s["pq-01"] = fs
    qc = m.qc
    p = qc.live(m)
    fs = {
        "lot_t": feat(r(m.sag["tph"] * 12, 0), "т/смену"), "v_cu": feat(r(p["v"], 1), "%"), "v_source": feat(p["v_src"]),
        "m_point": feat(r(p["m_point"], 2), "кг"), "n_min": feat(p["n_min"], "шт"), "n_points": feat(p["n"], "шт"),
        "period_min": feat(r(p["period"], 1), "мин"), "combined_kg": feat(r(p["combined"], 1), "кг"),
        "homogeneity": feat(p["category"]), "k_hom": feat(p["k"]), "m_min_10": feat(r(p["m_min_10"], 1), "кг"),
        "m_min_3": feat(r(p["m_min_3"], 2), "кг"), "n_conc": feat(p["n_conc"], "шт"),
    }
    L = qc.last
    if L:
        fs.update({
            "shift_closed": feat(L["shift"]),
            "assay_feed": feat(r(L["feed"], 3), "% Cu"), "assay_conc": feat(r(L["conc"], 2), "% Cu"),
            "assay_tails": feat(r(L["tails"], 3), "% Cu"), "eps_lab": feat(r(L["eps_lab"], 1), "%"),
            "eps_plant": feat(r(L["eps_plant"], 1), "%"), "balance_gap": feat(r(L["eps_lab"] - L["eps_plant"], 2), "п.п."),
            "w_conc": feat(L["w_conc"]["final"], "%"), "w_conc_d1": feat(L["w_conc"]["d1"], "%"),
            "w_conc_d2": feat(L["w_conc"]["d2"], "%"), "w_tol": feat(L["w_conc"]["tol"], "%"),
            "w_repeated": feat(bool(L["w_conc"]["repeated"])), "w_ore": feat(L["w_ore"]["final"], "%"),
            "conc_dry_t": feat(r(L["conc_t"], 0), "т"), "conc_wet_t": feat(r(L["conc_wet_t"], 0), "т"),
            "sieve_minus_008": feat(r(L["sieve"]["minus_008"], 1), "%"), "sieve_minus_004": feat(r(L["sieve"]["minus_004"], 1), "%"),
            "sieve_plus_0224": feat(r(L["sieve"]["plus_0224"], 1), "%"), "sieve_q_min": feat(r(L["sieve"]["q_min"], 2), "кг"),
        })
    s["lab-01"] = fs
