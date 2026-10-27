"""Packs Lumen's line icons: Lawnicons and Material Symbols (both Apache 2.0) in one zip the app
downloads whole.

    py -I tools/lawnicons.py v2.19.0 --symbols s1

Downloads that release of github.com/LawnchairLauncher/lawnicons, plus Google's Material Symbols
(Rounded, weight 200: the closest to Lawnicons' thin round strokes), and writes:
  v1/icons/lawnicons-<version>.zip   index.tsv, catalog.tsv, svg/<name>.svg, licenses, NOTICE
  v1/icons/lawnicons.json            the manifest the app checks: version, url, size, sha256

index.tsv maps "package/class" to a drawable; dynamic calendars map to "@" + the prefix of their
31 day icons. catalog.tsv lists every icon a user can pick for an app (name, kind, label,
category, keywords): Lawnicons by app name, and the symbols (as svg/ms_<name>.svg) by their
English tags plus tools/symbol_keywords.tsv in Lumen's other languages. Only SVGs the app can draw
are kept (shapes, groups and the stroke/fill attributes Lumen reads); the rest are listed and
left out. One zip on purpose: the app never asks for single icons, so the server never learns
which apps anyone has.
"""
import argparse
import hashlib
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE_URL, CACHE, ROOT, get  # noqa: E402

OUT = ROOT / "v1" / "icons"
SOURCE = "https://codeload.github.com/LawnchairLauncher/lawnicons/zip/refs/tags/{tag}"
SYMBOLS_META = "https://fonts.google.com/metadata/icons?key=material_symbols&incomplete=true"
SYMBOL_SVG = (
    "https://raw.githubusercontent.com/google/material-design-icons/master/"
    "symbols/web/{name}/materialsymbolsrounded/{name}_wght200_24px.svg"
)
SYMBOLS_LICENSE = "https://raw.githubusercontent.com/google/material-design-icons/master/LICENSE"
SYMBOL_FAMILY = "Material Symbols Rounded"
# Arrows, checkboxes and text formatting make poor app icons, unless symbol_keywords.tsv names them.
SKIPPED_CATEGORIES = {"Text", "UI actions"}
SYMBOL_CACHE = CACHE / "symbols"
KEYWORDS = Path(__file__).resolve().parent / "symbol_keywords.tsv"
LANGUAGES = ["es", "de", "fr", "it", "pt"]

SHAPES = {"path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}
TAGS = SHAPES | {"svg", "g"}
ATTRIBUTES = {
    "xmlns", "width", "height", "viewBox", "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2",
    "points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "fill-rule", "clip-rule", "space", "version",
}
INKS = {"#000", "#000000", "black", "none", "#fff", "#ffffff", "white"}
# Fixed timestamp, so the same sources always pack to the same bytes (and sha256).
STAMP = (2026, 1, 1, 0, 0, 0)


def drawable_problem(svg_bytes):
    """Why the app can't draw this SVG, or None when it can."""
    try:
        root = ET.fromstring(svg_bytes)
    except ET.ParseError as e:
        return f"xml: {e}"
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in TAGS:
            return f"<{tag}>"
        for name, value in element.attrib.items():
            name = name.rsplit("}", 1)[-1]
            if name not in ATTRIBUTES:
                return f"{name}="
            if name in ("fill", "stroke") and value.lower() not in INKS:
                return f"{name}={value}"
    box = root.get("viewBox")
    if box:
        values = [float(v) for v in re.split(r"[ ,]+", box.strip())]
        if len(values) != 4 or values[2] <= 0 or values[2] != values[3]:
            return f"viewBox={box}"
    return None


def clean(text):
    """One line of a TSV field: no tabs or newlines."""
    return re.sub(r"[\t\r\n]+", " ", text).strip()


def lawnicons(tag):
    """The release's drawable SVGs, its index, the pickable app icons and its license."""
    print(f"Downloading Lawnicons {tag}...")
    source = zipfile.ZipFile(io.BytesIO(get(SOURCE.format(tag=tag))))
    names = source.namelist()
    top = names[0].split("/", 1)[0]
    appfilter = source.read(f"{top}/app/assets/appfilter.xml")
    license_text = source.read(f"{top}/LICENSE")
    svgs = {Path(n).stem: n for n in names if n.startswith(f"{top}/svgs/") and n.endswith(".svg")}

    usable, problems = {}, {}
    for drawable, name in svgs.items():
        data = source.read(name)
        problem = drawable_problem(data)
        if problem:
            problems[drawable] = problem
        else:
            usable[drawable] = data

    index, used, labels = {}, set(), {}
    for element in ET.fromstring(appfilter):
        component = re.fullmatch(r"ComponentInfo\{(.+)\}", element.get("component") or "")
        if not component or component.group(1) in index:
            continue
        if element.tag == "calendar":
            prefix = element.get("prefix")
            if prefix and all(f"{prefix}{day}" in usable for day in range(1, 32)):
                index[component.group(1)] = "@" + prefix
                used.update(f"{prefix}{day}" for day in range(1, 32))
        elif element.tag == "item":
            drawable = element.get("drawable")
            if drawable in usable:
                index[component.group(1)] = drawable
                used.add(drawable)
                if element.get("name") and drawable not in labels:
                    labels[drawable] = clean(element.get("name"))
    # Every drawn app icon can be picked, except the calendar's day numbers.
    pickable = sorted(d for d in used if not d.startswith("themed_icon_calendar_"))
    catalog = [(d, "app", labels.get(d, d.replace("_", " ")), "app", "") for d in pickable]
    print(f"Lawnicons: {len(svgs)} SVGs, {len(usable)} drawable, {len(used)} packed; {len(index)} components")
    report(problems)
    return {d: usable[d] for d in used}, index, catalog, license_text


def symbol_keywords():
    """symbol → words in Lumen's other languages, from tools/symbol_keywords.tsv."""
    words = {}
    for line in KEYWORDS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        symbol, translations = fields[0], fields[1:]
        for text in translations:
            words.setdefault(symbol, []).extend(w.strip() for w in text.split(",") if w.strip())
    return words


def symbols():
    """Material Symbols for app icons: SVGs (cached in .cache/symbols), catalog lines and license."""
    meta = json.loads(get(SYMBOLS_META).decode("utf-8").split("\n", 1)[1])
    translations = symbol_keywords()
    chosen = [
        icon for icon in meta["icons"]
        if SYMBOL_FAMILY not in icon.get("unsupported_families", [])
        and (icon["name"] in translations or not SKIPPED_CATEGORIES.intersection(icon.get("categories", [])))
    ]
    SYMBOL_CACHE.mkdir(parents=True, exist_ok=True)

    def fetch(icon):
        file = SYMBOL_CACHE / f"{icon['name']}.svg"
        if not file.exists():
            try:
                file.write_bytes(get(SYMBOL_SVG.format(name=icon["name"])))
            except Exception as e:  # noqa: BLE001 - a missing symbol is left out, not fatal
                return icon["name"], None, f"download: {e}"
        data = file.read_bytes()
        return icon["name"], data, drawable_problem(data)

    print(f"Material Symbols: {len(chosen)} candidates, downloading the missing ones...")
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(fetch, chosen))
    unknown = sorted(set(translations) - {i["name"] for i in chosen})
    svgs, catalog, problems = {}, [], {}
    by_name = {i["name"]: i for i in chosen}
    for name, data, problem in results:
        if problem:
            problems[name] = problem
            continue
        icon = by_name[name]
        svgs[f"ms_{name}"] = data
        words = icon.get("tags", []) + translations.get(name, [])
        catalog.append((
            f"ms_{name}", "symbol", name.replace("_", " "),
            clean((icon.get("categories") or ["Other"])[0]),
            clean(",".join(dict.fromkeys(w.lower() for w in words))),
        ))
    print(f"Material Symbols: {len(svgs)} packed")
    report(problems)
    if unknown:
        print(f"symbol_keywords.tsv names no such symbol: {', '.join(unknown)}")
    return svgs, catalog, get(SYMBOLS_LICENSE)


def report(problems):
    if not problems:
        return
    kinds = {}
    for problem in problems.values():
        kind = problem.split("=")[0].split(":")[0]
        kinds[kind] = kinds.get(kind, 0) + 1
    print(f"  left out {len(problems)}: " + ", ".join(f"{k} x{n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])))
    for name, problem in sorted(problems.items())[:20]:
        print(f"    {name}: {problem}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Lawnicons release tag, e.g. v2.19.0")
    parser.add_argument("--symbols", required=True, help="revision of the symbols part, e.g. s1")
    args = parser.parse_args()
    version = f"{args.tag.lstrip('v')}-{args.symbols}"

    app_svgs, index, app_catalog, lawnicons_license = lawnicons(args.tag)
    symbol_svgs, symbol_catalog, symbols_license = symbols()

    OUT.mkdir(parents=True, exist_ok=True)
    pack_name = f"lawnicons-{version}.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as pack:
        def put(path, data):
            pack.writestr(zipfile.ZipInfo(path, STAMP), data, zipfile.ZIP_DEFLATED)

        put("index.tsv", f"#lawnicons\t{version}\n" + "".join(f"{c}\t{d}\n" for c, d in sorted(index.items())))
        put("catalog.tsv", f"#catalog\t{version}\n" + "".join("\t".join(row) + "\n" for row in app_catalog + symbol_catalog))
        for name, data in sorted({**app_svgs, **symbol_svgs}.items()):
            put(f"svg/{name}.svg", data)
        put("LICENSE", lawnicons_license)
        put("LICENSE-material-symbols", symbols_license)
        put("NOTICE", (
            f"Lumen line icons {version}\n"
            "Lawnicons, copyright the Lawnchair team and Lawnicons contributors,\n"
            "Apache License 2.0 (see LICENSE). https://github.com/LawnchairLauncher/lawnicons\n"
            "Material Symbols (svg/ms_*), copyright Google LLC,\n"
            "Apache License 2.0 (see LICENSE-material-symbols). https://github.com/google/material-design-icons\n"
            "Packed unmodified for Lumen; Lumen tints and scales the drawings when showing them.\n"
        ))
    data = buffer.getvalue()
    for old in OUT.glob("lawnicons-*.zip"):
        if old.name != pack_name:
            old.unlink()
    (OUT / pack_name).write_bytes(data)
    manifest = {
        "schema": 1,
        "version": version,
        "url": f"{BASE_URL}/v1/icons/{pack_name}",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    (OUT / "lawnicons.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{pack_name}: {len(data) / 1e6:.2f} MB, {len(app_catalog)} app icons + {len(symbol_catalog)} symbols to pick")
    print(f"sha256 {manifest['sha256']}")


if __name__ == "__main__":
    main()
