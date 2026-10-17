"""Draws numbered contact sheets of candidates, each cropped the way a phone would show it.

    py -I tools/contact_sheet.py Wildlife [--pool 120]

Picks a varied pool from .cache/candidates/<Collection>.json (few per category and per author),
downloads small previews and writes .cache/sheets/<Collection>-<n>.jpg plus <Collection>-pool.json,
whose index matches the numbers on the sheets.
"""
import argparse
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, get  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

TILE_W, TILE_H = 180, 400  # 9:20, a phone
COLUMNS, ROWS = 8, 3


def pool(candidates, size, per_category, per_author):
    by_category, by_author, out = Counter(), Counter(), []
    for c in candidates:
        author = c["creator"][:40]
        if by_category[c["category"]] >= per_category or by_author[author] >= per_author:
            continue
        by_category[c["category"]] += 1
        by_author[author] += 1
        out.append(c)
        if len(out) == size:
            break
    return out


def preview(c):
    path = CACHE / "previews" / f"{c['pageid']}.jpg"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(c["thumb"]))
        time.sleep(0.3)
    return Image.open(io.BytesIO(path.read_bytes())).convert("RGB")


def phone_crop(img):
    w, h = img.size
    target = TILE_W / TILE_H
    if w / h > target:
        cw = int(h * target)
        img = img.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
    else:
        ch = int(w / target)
        img = img.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch))
    return img.resize((TILE_W, TILE_H), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("collection")
    parser.add_argument("--pool", type=int, default=120)
    parser.add_argument("--per-category", type=int, default=14)
    parser.add_argument("--per-author", type=int, default=8)
    args = parser.parse_args()

    candidates = json.loads((CACHE / "candidates" / f"{args.collection}.json").read_text(encoding="utf-8"))
    chosen = pool(candidates, args.pool, args.per_category, args.per_author)
    sheets = CACHE / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    (sheets / f"{args.collection}-pool.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")

    font = ImageFont.load_default(size=28)
    per_sheet = COLUMNS * ROWS
    for start in range(0, len(chosen), per_sheet):
        sheet = Image.new("RGB", (COLUMNS * TILE_W, ROWS * TILE_H), "black")
        draw = ImageDraw.Draw(sheet)
        for i, c in enumerate(chosen[start:start + per_sheet]):
            x, y = (i % COLUMNS) * TILE_W, (i // COLUMNS) * TILE_H
            try:
                sheet.paste(phone_crop(preview(c)), (x, y))
            except Exception as e:  # noqa: BLE001 - a broken preview just leaves its tile empty
                print("preview failed", c["file"], e)
            draw.rectangle((x, y, x + 52, y + 34), fill="black")
            draw.text((x + 4, y + 2), str(start + i), fill="yellow", font=font)
        out = sheets / f"{args.collection}-{start // per_sheet}.jpg"
        sheet.save(out, quality=82)
        print(out)


if __name__ == "__main__":
    main()
