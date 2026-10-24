# Лицензии данных

Код решения — MIT (`LICENSE`). Файлы данных сохраняют свои лицензии.

| Датасет | Папка | Лицензия | Атрибуция и изменения |
|---|---|---|---|
| GeoMet (Zenodo 7051975) | `bozshakol/data/geomet/` | CC BY 4.0 | [README](bozshakol/data/geomet/README.md); файлы без изменений |
| Контуры карьеров по Лерчу–Гроссману (производные от GeoMet) | `bozshakol/data/pit-shells/` | CC BY 4.0 (как исходные данные GeoMet) | [README](bozshakol/data/pit-shells/README.md); синтетическая блочная модель, расчёт `bozshakol/tools/pit_optimize.py` |
| Quality Prediction in a Mining Process (Kaggle) | `bozshakol/data/flotation-plant/` | CC0 1.0 | [README](bozshakol/data/flotation-plant/README.md); усреднено до часов (`ml/prepare.py`) |
| seismic-bumps (UCI) | `bozshakol/data/seismic-bumps/` | CC BY 4.0 | [README](bozshakol/data/seismic-bumps/README.md); без изменений |
| OpenMines `north_pit_mine.json` | `bozshakol/data/openmines/` | MIT | [README](bozshakol/data/openmines/README.md), `LICENSE` сохранён |
| MWD + породы, 15 тоннелей Норвегии (NGI, Zenodo 10358374) | `bozshakol/data/mwd-rocktype/` | CC BY 4.0; на странице записи: «only available for research, no commercial use» | [README](bozshakol/data/mwd-rocktype/README.md); без изменений |
| Фрагментация по дрону, карьер El Aljibe (Zenodo 10666378) | `bozshakol/data/fragmentation/` | CC BY 4.0 | [README](bozshakol/data/fragmentation/README.md); без изменений |
| Энергопотребление ГОК, получасовые данные (Zenodo 20647907) | `bozshakol/data/energy-gok/` | **CC BY-SA 4.0** | [README](bozshakol/data/energy-gok/README.md); оригинал без изменений, `energy_30min.csv` — производный (сумма подстанций, кВт·ч → МВт) |

Обученные модели (`bozshakol/ml/models/`) — производные работы от этих данных; распространяются на тех же условиях (атрибуция CC BY; `energy_load.json` и `energy_30min.csv` — CC BY-SA 4.0), код обучения — MIT.

Все данные лежат в репозитории: стенду ничего не нужно скачивать.
