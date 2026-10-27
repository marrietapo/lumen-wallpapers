"""Packs Lawnicons (Apache 2.0) for Lumen's line icons: one zip the app downloads whole.

    py -I tools/lawnicons.py v2.19.0

Downloads that release of github.com/LawnchairLauncher/lawnicons and writes:
  v1/icons/lawnicons-<version>.zip   index.tsv, svg/<drawable>.svg, LICENSE, NOTICE
  v1/icons/lawnicons.json            the manifest the app checks: version, url, size, sha256

index.tsv maps "package/class" to a drawable; dynamic calendars map to "@" + the prefix of their
31 day icons. Only SVGs the app can draw are kept (shapes, groups and the stroke/fill attributes
Lumen reads); the rest are listed and left out, so those apps fall back to Lumen's own glyph.
One zip on purpose: the app never asks for single icons, so the server never learns which apps
anyone has.
"""
import argparse
import hashlib
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE_URL, ROOT, get  # noqa: E402

OUT = ROOT / "v1" / "icons"
SOURCE = "https://codeload.github.com/LawnchairLauncher/lawnicons/zip/refs/tags/{tag}"

SHAPES = {"path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}
TAGS = SHAPES | {"svg", "g"}
ATTRIBUTES = {
    "xmlns", "width", "height", "viewBox", "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2",
    "points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "fill-rule", "clip-rule", "space", "version",
}
INKS = {"#000", "#000000", "black", "none", "#fff", "#ffffff", "white"}
# Fixed timestamp, so the same release always packs to the same bytes (and sha256).
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
    if box and [float(v) for v in re.split(r"[ ,]+", box.strip())][:2] != [0, 0]:
        return f"viewBox={box}"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Lawnicons release tag, e.g. v2.19.0")
    args = parser.parse_args()
    version = args.tag.lstrip("v")

    print(f"Downloading Lawnicons {args.tag}...")
    source = zipfile.ZipFile(io.BytesIO(get(SOURCE.format(tag=args.tag))))
    names = source.namelist()
    top = names[0].split("/", 1)[0]
    appfilter = source.read(f"{top}/app/assets/appfilter.xml")
    license_text = source.read(f"{top}/LICENSE")
    svgs = {
        Path(name).stem: name for name in names
        if name.startswith(f"{top}/svgs/") and name.endswith(".svg")
    }

    usable, problems = {}, {}
    for drawable, name in svgs.items():
        data = source.read(name)
        problem = drawable_problem(data)
        if problem:
            problems[drawable] = problem
        else:
            usable[drawable] = data

    index, used = {}, set()
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

    OUT.mkdir(parents=True, exist_ok=True)
    pack_name = f"lawnicons-{version}.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as pack:
        def put(path, data):
            pack.writestr(zipfile.ZipInfo(path, STAMP), data, zipfile.ZIP_DEFLATED)

        put("index.tsv", f"#lawnicons\t{version}\n" + "".join(f"{c}\t{d}\n" for c, d in sorted(index.items())))
        for drawable in sorted(used):
            put(f"svg/{drawable}.svg", usable[drawable])
        put("LICENSE", license_text)
        put("NOTICE", (
            f"Lawnicons {version}\n"
            "Copyright the Lawnchair team and Lawnicons contributors.\n"
            "Licensed under the Apache License, Version 2.0 (see LICENSE).\n"
            "https://github.com/LawnchairLauncher/lawnicons\n"
            "Packed unmodified for Lumen; Lumen tints and scales the outlines when drawing them.\n"
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

    print(f"{len(svgs)} SVGs, {len(usable)} drawable, {len(used)} packed; {len(index)} components")
    print(f"{pack_name}: {len(data) / 1e6:.2f} MB, sha256 {manifest['sha256']}")
    if problems:
        kinds = {}
        for problem in problems.values():
            kinds[problem.split("=")[0]] = kinds.get(problem.split("=")[0], 0) + 1
        print(f"Left out {len(problems)}: " + ", ".join(f"{k} x{n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])))
        for drawable, problem in sorted(problems.items())[:40]:
            print(f"  {drawable}: {problem}")


if __name__ == "__main__":
    main()
