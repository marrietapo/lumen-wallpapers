"""Finds wallpaper candidates among Wikimedia Commons' featured pictures.

    py -I tools/commons_candidates.py              # every collection in COLLECTIONS
    py -I tools/commons_candidates.py Wildlife     # just one

Writes .cache/candidates/<Collection>.json: files with a license Lumen can use, big enough for a
phone, without personality-rights / trademark / freedom-of-panorama warnings, best first.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, commons_api, normalize_license, strip_html

COLLECTIONS = {
    "Travel": [
        "Featured pictures of cityscapes", "Featured pictures of skylines", "Featured pictures of castles",
        "Featured pictures of bridges", "Featured pictures of Japan", "Featured pictures of towers",
        "Featured pictures of palaces", "Featured pictures of Paris", "Featured pictures of Portugal",
        "Featured pictures of Greece", "Featured pictures of New York City", "Featured pictures of roads",
    ],
    "Nature": [
        "Featured pictures of landscapes", "Featured pictures of mountains", "Featured pictures of lakes",
        "Featured pictures of forests", "Featured pictures of fog", "Featured pictures of waterfalls",
        "Featured pictures of trees", "Featured pictures of the Alps in Switzerland",
        "Featured pictures of landscapes in Iceland", "Featured pictures of volcanoes", "Featured pictures of snow",
        "Featured pictures of reflections",
    ],
    "Wildlife": [
        "Featured pictures of mammals by Charlesjsharp", "Featured pictures of mammals", "Featured pictures of Felidae",
        "Featured pictures of Canidae", "Featured pictures of Equidae", "Featured pictures of Bovidae",
        "Featured pictures of Cercopithecidae", "Featured pictures of animals in Tanzania",
        "Featured pictures of animals in Namibia", "Featured pictures of birds in flight",
        "Featured pictures of birds by Charlesjsharp", "Featured pictures of Cetacea",
        "Featured pictures of coral", "Featured pictures of fish by Charlesjsharp",
    ],
    "SeaSky": [
        "Featured pictures of coasts", "Featured pictures of beaches", "Featured pictures of islands",
        "Featured pictures of clouds", "Featured pictures of sunsets", "Featured pictures of sunrises",
        "Featured pictures of aurora", "Featured pictures of astronomy", "Featured pictures of bodies of water",
        "Featured pictures of oceans", "Featured pictures of seas",
    ],
}

# Commons marks these; any of them makes a file unfit for a wallpaper sold in an app.
RISKY_CATEGORY_WORDS = (
    "personality rights", "trademark", "fop", "freedom of panorama", "non-free", "portrait", "people",
    "women", "men ", "children", "girls", "boys", "nude", "logo",
)

MIN_SHORT_SIDE = 2400
# A phone shows a 9:20 window; wider than this and too little of the picture is left.
MAX_ASPECT = 1.8


def members(category):
    params = dict(
        action="query", generator="categorymembers", gcmtitle="Category:" + category, gcmtype="file",
        gcmlimit="50", prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth="480",
        iiextmetadatafilter="LicenseShortName|Artist|ObjectName|DateTimeOriginal|Categories|Restrictions",
    )
    while True:
        data = commons_api(**params)
        for page in data.get("query", {}).get("pages", []):
            yield page
        if "continue" not in data:
            break
        params.update(data["continue"])


def candidate(page, category):
    info = (page.get("imageinfo") or [None])[0]
    if not info or info.get("mime") != "image/jpeg":
        return None
    meta = {k: v.get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
    license_ = normalize_license(meta.get("LicenseShortName"))
    if not license_:
        return None
    if strip_html(meta.get("Restrictions")):
        return None
    categories = (meta.get("Categories") or "").lower()
    if any(word in categories for word in RISKY_CATEGORY_WORDS):
        return None
    width, height = info["width"], info["height"]
    if min(width, height) < MIN_SHORT_SIDE or width / height > MAX_ASPECT:
        return None
    title = page["title"].removeprefix("File:")
    return {
        "pageid": page["pageid"],
        "file": title,
        "title": strip_html(meta.get("ObjectName")) or title.rsplit(".", 1)[0],
        "creator": strip_html(meta.get("Artist")),
        "date": strip_html(meta.get("DateTimeOriginal"))[:10],
        "license": license_,
        "page": info["descriptionurl"],
        "original": info["url"],
        "thumb": info["thumburl"],
        "width": width,
        "height": height,
        "category": category,
    }


def main(names):
    out_dir = CACHE / "candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        seen, found = set(), []
        for category in COLLECTIONS[name]:
            kept = 0
            for page in members(category):
                if page["pageid"] in seen:
                    continue
                seen.add(page["pageid"])
                c = candidate(page, category)
                if c:
                    found.append(c)
                    kept += 1
            print(f"{name}: {category}: {kept}")
        # Portrait pictures first (they fill a phone without losing anything), then the biggest.
        found.sort(key=lambda c: (c["width"] > c["height"], -c["width"] * c["height"]))
        (out_dir / f"{name}.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: {len(found)} candidates")


if __name__ == "__main__":
    main(sys.argv[1:] or list(COLLECTIONS))
