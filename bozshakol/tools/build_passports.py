#!/usr/bin/env python3
"""Render the equipment passports of the twin to docs/equipment_passports.pdf.

    python3 bozshakol/tools/build_passports.py     # needs Playwright with Chromium

The document is generated from sim/equipment.py (the same records the twins
carry in their `passport` attribute) and from twins/twins.json (which twins use
each passport), so the PDF, the twins and the simulator cannot drift apart.
"""

import asyncio
import datetime as dt
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim.equipment import PASSPORTS, PROJECT_NOTE, STATUS_RU  # noqa: E402

TWINS = os.path.join(ROOT, "twins", "twins.json")
HTML_OUT = os.path.join(ROOT, "docs", "equipment_passports.html")
PDF_OUT = os.path.join(ROOT, "docs", "equipment_passports.pdf")


def ranges(ids):
    """ht-01, ht-02, ht-03 -> ht-01…03"""
    groups = {}
    for i in sorted(ids):
        m = re.match(r"(.*?)(\d+)$", i)
        if m:
            groups.setdefault(m.group(1), []).append((int(m.group(2)), len(m.group(2))))
        else:
            groups.setdefault(i, [])
    out = []
    for pre, nums in groups.items():
        if not nums:
            out.append(pre)
            continue
        nums.sort()
        start = prev = nums[0]
        for n in nums[1:] + [None]:
            if n is not None and n[0] == prev[0] + 1:
                prev = n
                continue
            a = f"{pre}{start[0]:0{start[1]}d}"
            out.append(a if start == prev else f"{a}…{prev[0]:0{prev[1]}d}")
            if n is not None:
                start = prev = n
    return ", ".join(out)


def main():
    twins = json.load(open(TWINS))
    used = {}
    for tid, t in twins.items():
        p = t.get("attributes", {}).get("passport")
        if p:
            used.setdefault(p["id"], []).append(tid.split(":", 1)[1])
    e = html.escape
    parts = []
    for n, (pid, p) in enumerate(PASSPORTS.items(), 1):
        rows = "".join(f"<tr><td>{e(s['label'])}</td><td class=r>{e(str(s['value']))}</td><td>{e(s['unit'])}</td></tr>"
                       for s in p["specs"].values())
        notes = "".join(f"<li>{e(x)}</li>" for x in p["notes"])
        src = p["source"]
        link = f' — <a href="{e(src["url"])}">{e(src["url"])}</a>' if src.get("url") else ""
        parts.append(f"""
<section>
  <h2>{n:02d}. {e(p['model'])} <span class=v>{e(p['variant'])}</span></h2>
  <div class=meta>{e(p['manufacturer'])} · статус: <b>{e(p['status_ru'])}</b> · двойники: <code>{e(ranges(used.get(pid, [])) or '—')}</code></div>
  {'<table><tr><th>Характеристика</th><th class=r>Значение</th><th>Ед.</th></tr>' + rows + '</table>' if rows else ''}
  {'<ul>' + notes + '</ul>' if notes else ''}
  <div class=src>Источник: {e(src['title'])}{(', ' + e(src['ref'])) if src.get('ref') else ''}{link}</div>
</section>""")
    proj = ranges(used.get("project", []))
    status = "".join(f"<li><b>{e(v)}</b> ({e(k)})</li>" for k, v in STATUS_RU.items())
    doc = f"""<!doctype html><html lang=ru><head><meta charset=utf-8><title>Паспорта оборудования — двойник ГОК «Бозшаколь»</title>
<style>
body {{ font: 10.5pt/1.4 "Inter","Segoe UI",Arial,sans-serif; color:#1b1f24; margin:0; }}
h1 {{ font-size:18pt; margin:0 0 4px; }} h2 {{ font-size:12pt; margin:0 0 3px; color:#8a4b22; }} h2 .v {{ color:#6b7480; font-weight:400; font-size:10pt; }}
.lead {{ color:#4b5563; }} section {{ break-inside:avoid; border-top:1px solid #d8dde3; padding:8px 0; }}
.meta {{ color:#4b5563; font-size:9.5pt; margin-bottom:4px; }} code {{ font-size:9pt; }}
table {{ border-collapse:collapse; width:100%; font-size:9.5pt; }} th,td {{ border-bottom:1px solid #eceff2; padding:2px 6px; text-align:left; }} .r {{ text-align:right; }}
ul {{ margin:4px 0 2px 18px; padding:0; font-size:9.5pt; }} .src {{ font-size:8.5pt; color:#4b5563; word-break:break-all; }}
</style></head><body>
<h1>Паспорта оборудования цифрового двойника ГОК «Бозшаколь»</h1>
<p class=lead>Документ собран автоматически из <code>bozshakol/sim/equipment.py</code> — тех же записей, которые двойники Ditto
несут в атрибуте <code>passport</code>; список двойников — из <code>bozshakol/twins/twins.json</code>. Значения — паспортные
характеристики из документации производителей со ссылками. Рабочие скорости, расход топлива, сроки ремонта и расчётная
производительность модели — не паспортные значения, они в <code>sim/params.py</code> с пометкой «(A)». Наличие модели здесь не
означает, что она установлена на реальном Бозшаколе: статус у каждой записи.</p>
<ul>{status}</ul>
<p class=lead>Объекты без серийного паспорта (дороги, блоки, склады, отвалы, хвостохранилище, глинистая фабрика): <code>{e(proj)}</code> — {e(PROJECT_NOTE)}</p>
<p class=lead>Сформировано {dt.date.today().isoformat()} командой <code>python3 bozshakol/tools/build_passports.py</code>.</p>
{''.join(parts)}
</body></html>"""
    with open(HTML_OUT, "w") as f:
        f.write(doc)
    asyncio.run(render())
    os.remove(HTML_OUT)
    print(PDF_OUT)


async def render():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        await page.goto("file://" + HTML_OUT)
        await page.pdf(path=PDF_OUT, format="A4", print_background=True,
                       margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"})
        await b.close()


if __name__ == "__main__":
    sys.exit(main())
