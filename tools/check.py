"""Checks the catalog before a push: format, ids, licenses, files on disk, and (with --online) the server.

    py -I tools/check.py            # local checks
    py -I tools/check.py --online   # also asks the server for every image (after a deploy)
"""
import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ALLOWED_LICENSES, BASE_URL, LANGUAGES, ROOT, USER_AGENT, load_catalog  # noqa: E402

KEYS = {"id", "title", "creator", "date", "source", "license", "page", "image", "thumb", "crop", "focus"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    cat = load_catalog()
    errors = []
    if cat.get("schema") != 1:
        errors.append("schema must be 1")
    seen_collections, seen_photos, urls = set(), set(), []
    for c in cat["collections"]:
        cid = c["id"]
        if cid in seen_collections:
            errors.append(f"duplicate collection {cid}")
        seen_collections.add(cid)
        missing = [lang for lang in LANGUAGES if not c.get("names", {}).get(lang)]
        if missing:
            errors.append(f"{cid}: no name in {missing}")
        if c["photos"] and not any(p.get("free") for p in c["photos"]):
            errors.append(f"{cid}: no free picture")
        for p in c["photos"]:
            where = f"{cid}/{p.get('id')}"
            if KEYS - p.keys():
                errors.append(f"{where}: missing {sorted(KEYS - p.keys())}")
                continue
            if p["id"] in seen_photos:
                errors.append(f"{where}: duplicate id")
            seen_photos.add(p["id"])
            if not ALLOWED_LICENSES.match(p["license"]):
                errors.append(f"{where}: license {p['license']!r}")
            if not p["title"].strip() or not p["creator"].strip():
                errors.append(f"{where}: no title or creator")
            if p["page"] and not p["page"].startswith("https://"):
                errors.append(f"{where}: page not https")
            for key in ("image", "thumb"):
                url = p[key]
                if not url.startswith(BASE_URL + "/"):
                    errors.append(f"{where}: {key} not on {BASE_URL}")
                    continue
                local = ROOT / url[len(BASE_URL) + 1:]
                if not local.exists():
                    errors.append(f"{where}: {local.relative_to(ROOT)} missing")
                urls.append(url)
            numbers = p["crop"] + p["focus"]
            if len(numbers) != 6 or not all(0 <= n <= 1 for n in numbers):
                errors.append(f"{where}: crop/focus out of 0..1")
    if args.online:
        for url in urls:
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as r:
                    if r.status != 200:
                        errors.append(f"{url}: HTTP {r.status}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{url}: {e}")
    total = sum(len(c["photos"]) for c in cat["collections"])
    if errors:
        print("\n".join(errors))
        print(f"{len(errors)} problem(s)")
        sys.exit(1)
    print(f"OK: {len(cat['collections'])} collections, {total} pictures")


if __name__ == "__main__":
    main()
