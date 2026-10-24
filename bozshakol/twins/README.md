# twins/ — определения двойников Бозшаколя

Файлы загружаются в Eclipse Ditto командой `python -m sim.setup_twins` (сервис `bozshakol-setup` в `make bozshakol`). Так же Example Mine загружает свой `twins.json`.

| Файл | Что внутри |
|---|---|
| `types.json` | 48 типов OpenTwins (`attributes._isType = true`): схема признаков с единицами и постоянные атрибуты модели техники. `_parents = {"kz.bozshakol.types:site": N}` — сколько экземпляров входит в ГОК |
| `twins.json` | 113 двойников с начальным состоянием. Корень `kz.bozshakol:site`; остальные — его прямые дети (`_parents = "kz.bozshakol:site"`), у каждого `type` (ссылка на тип) и `section` (участок) |

Файлы генерируются из модели, руками их не правят:

```bash
cd bozshakol
python3 -m sim.export_twins          # пересобрать
python3 -m sim.export_twins --check  # проверить, что не устарели
```

Где смотреть в Grafana: **OpenEgiz → Twins** → «ГОК «Бозшаколь»» → вкладка **Children** (вся техника и объекты); **OpenEgiz → Types** — типы и состав комбината.
