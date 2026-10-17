"""Shows whole previews with a ruler, to choose focus points, and checks picks.

    py -I tools/focus_sheet.py Wildlife 63 67 74     # whole pictures, ruler every 0.1
    py -I tools/focus_sheet.py Wildlife --picks      # every pick as the phone would show it

Writes .cache/sheets/<Collection>-focus.jpg or <Collection>-picks.jpg.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE  # noqa: E402
from contact_sheet import preview  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

HEIGHT = 300
PHONE = 9 / 20


def window(img, fx, fy):
    w, h = img.size
    if w / h > PHONE:
        cw = round(h * PHONE)
        left = min(max(round(fx * w - cw / 2), 0), w - cw)
        return img.crop((left, 0, left + cw, h))
    ch = round(w / PHONE)
    top = min(max(round(fy * h - ch / 2), 0), h - ch)
    return img.crop((0, top, w, top + ch))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("collection")
    parser.add_argument("indices", nargs="*", type=int)
    parser.add_argument("--picks", action="store_true")
    args = parser.parse_args()
    pool = json.loads((CACHE / "sheets" / f"{args.collection}-pool.json").read_text(encoding="utf-8"))
    font = ImageFont.load_default(size=20)
    tiles = []
    if args.picks:
        picks = json.loads((CACHE / "picks" / f"{args.collection}.json").read_text(encoding="utf-8"))
        for n, pick in enumerate(picks):
            img = window(preview(pool[pick["pool"]]), *pick.get("focus", [0.5, 0.5]))
            img = img.resize((round(img.width * 400 / img.height), 400), Image.LANCZOS)
            tiles.append((f"{n}:{pick['pool']}", img))
    else:
        for i in args.indices:
            img = preview(pool[i])
            img = img.resize((round(img.width * HEIGHT / img.height), HEIGHT), Image.LANCZOS)
            d = ImageDraw.Draw(img)
            for k in range(1, 10):
                x = round(img.width * k / 10)
                d.line((x, 0, x, img.height), fill="yellow" if k == 5 else "red", width=1)
                d.text((x + 2, img.height - 22), str(k), fill="yellow", font=font)
            tiles.append((str(i), img))
    per_row = 8 if args.picks else 3
    tw = max(t.width for _, t in tiles)
    th = max(t.height for _, t in tiles)
    rows = (len(tiles) + per_row - 1) // per_row
    sheet = Image.new("RGB", (per_row * (tw + 6), rows * (th + 6)), "black")
    d = ImageDraw.Draw(sheet)
    for n, (label, t) in enumerate(tiles):
        x, y = (n % per_row) * (tw + 6), (n // per_row) * (th + 6)
        sheet.paste(t, (x, y))
        d.rectangle((x, y, x + 70, y + 24), fill="black")
        d.text((x + 3, y + 1), label, fill="yellow", font=font)
    out = CACHE / "sheets" / f"{args.collection}-{'picks' if args.picks else 'focus'}.jpg"
    sheet.save(out, quality=85)
    print(out)


if __name__ == "__main__":
    main()
