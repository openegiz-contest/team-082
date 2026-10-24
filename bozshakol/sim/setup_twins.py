#!/usr/bin/env python3
"""Create (or reset) the Bozshakol types and twins in Eclipse Ditto. Idempotent PUTs.

Loads the declarative definitions from bozshakol/twins/ (types.json, then
twins.json) exactly as the platform's Example Mine loads its twins.json:

- types first (attributes._isType = true), so the OpenEgiz app's Types page
  shows the templates and their composition;
- then the site twin, then every other twin as its direct child
  (attributes._parents = kz.bozshakol:site, attributes.type = its type).

The control twin is reset to the baseline scenario on every run.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080").rstrip("/")
AUTH = "Basic " + base64.b64encode(
    f"{os.environ.get('DITTO_USER', 'ditto')}:{os.environ.get('DITTO_PASSWORD', '')}".encode()).decode()
TWINS_DIR = os.environ.get("TWINS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "twins"))


def load(name):
    with open(os.path.join(TWINS_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def put(thing_id, body):
    req = urllib.request.Request(f"{DITTO_URL}/api/2/things/{thing_id}", data=json.dumps(body).encode(),
                                 method="PUT", headers={"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status


def put_with_retry(thing_id, body):
    for attempt in range(30):
        try:
            status = put(thing_id, body)
            print(f"{'created' if status == 201 else 'updated'}  {thing_id}")
            return True
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            if exc.code in (408, 429, 500, 502, 503, 504) and attempt < 29:
                time.sleep(3)
                continue
            print(f"FAILED   {thing_id}: HTTP {exc.code} {detail}", file=sys.stderr)
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 29:
                print(f"FAILED   {thing_id}: {exc}", file=sys.stderr)
                return False
            time.sleep(3)
    return False


def main():
    types, things = load("types.json"), load("twins.json")
    if "--print" in sys.argv:
        print(json.dumps({"types": list(types), "twins": list(things)}, ensure_ascii=False, indent=1))
        return 0
    for thing_id, body in list(types.items()) + list(things.items()):
        if not put_with_retry(thing_id, body):
            return 1
    print(f"{len(types)} types and {len(things)} Bozshakol twins ready in {DITTO_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
