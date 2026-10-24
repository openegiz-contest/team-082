#!/usr/bin/env python3
"""Render bozshakol/docs/presentation.html to presentation.pdf (repository root).

Development tool: needs Playwright with Chromium (pip install playwright).
The screenshots in bozshakol/docs/img/ are taken from the running stand.
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "bozshakol", "docs", "presentation.html")
OUT = os.path.join(ROOT, "presentation.pdf")


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 900})
        await page.goto("file://" + SRC)
        await page.wait_for_timeout(1500)
        await page.pdf(path=OUT, width="1600px", height="900px", print_background=True,
                       margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        await browser.close()
    print(OUT)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
