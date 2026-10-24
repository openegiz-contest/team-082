#!/usr/bin/env python3
"""Write the declarative twin definitions in bozshakol/twins/ from the model.

    python -m sim.export_twins          # from bozshakol/: regenerate twins/*.json
    python -m sim.export_twins --check  # fail if the committed files are stale

twins/types.json  OpenTwins types (attributes._isType = true)
twins/twins.json  the twins with their initial state (attributes.type, _parents)

The files are what sim.setup_twins loads into Ditto, the same way the
platform's Example Mine loads examples/mine/twins.json.
"""

import json
import os
import sys

from . import twins as T
from .model import Mine

TWINS_DIR = os.environ.get("TWINS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "twins"))
SEED = 42


def render():
    things = T.build_things(Mine(SEED))
    types = T.build_types(things)
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, indent=1) + "\n"  # noqa: E731
    return {"types.json": dump(types), "twins.json": dump(things)}


def main(argv):
    files = render()
    if "--check" in argv:
        stale = [n for n, text in files.items()
                 if not os.path.exists(os.path.join(TWINS_DIR, n)) or open(os.path.join(TWINS_DIR, n), encoding="utf-8").read() != text]
        if stale:
            print(f"stale: {', '.join(stale)}; run: cd bozshakol && python3 -m sim.export_twins", file=sys.stderr)
            return 1
        print("twins/*.json are up to date")
        return 0
    os.makedirs(TWINS_DIR, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(TWINS_DIR, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    types, things = json.loads(files["types.json"]), json.loads(files["twins.json"])
    print(f"wrote {len(types)} types and {len(things)} twins to {TWINS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
