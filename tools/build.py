"""Turns picked pictures into Lumen wallpapers: downloads, crops, optimizes, updates the catalog.

    py -I tools/build.py commons <Collection>   # picks in .cache/picks/<Collection>.json
    py -I tools/build.py legacy <collections.json>  # the app's old Met/NASA list
    py -I tools/build.py originals [--collection Originals]  # everything in originals/inbox/
    py -I tools/build.py credits                # rewrites CREDITS.md from the catalog

Every picture becomes img/<id>/full.webp (a 3:5 band around its focus point, at most 1920×3200)
and img/<id>/thumb.webp (540 px wide). The app shows a 9:20-ish window of the band, centered on
the focus, so the band leaves room for wider and narrower phones.
"""
import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    BASE_URL, CACHE, IMAGES, LANGUAGES, ROOT, commons_api, get, load_catalog, save_catalog,
)

from PIL import Image, ImageChops, ImageCms, ImageOps, ImageStat  # noqa: E402

Image.MAX_IMAGE_PIXELS = 400_000_000

BAND = 0.6  # width / height of what is kept
MAX_HEIGHT = 3200
THUMB_WIDTH = 540
MIN_ORIGINAL_SHORT_SIDE = 1440

COLLECTION_NAMES = {
    "Originals": dict(en="Lumen Originals", es="Lumen Originals", de="Lumen Originals", fr="Lumen Originals",
                      it="Lumen Originals", pt="Lumen Originals"),
    "Travel": dict(en="Travel", es="Viajes", de="Reisen", fr="Voyages", it="Viaggi", pt="Viagens"),
    "Nature": dict(en="Nature", es="Naturaleza", de="Natur", fr="Nature", it="Natura", pt="Natureza"),
    "Wildlife": dict(en="Wildlife", es="Animales", de="Tierwelt", fr="Faune", it="Animali", pt="Animais"),
    "SeaSky": dict(en="Sea & sky", es="Mar y cielo", de="Meer & Himmel", fr="Mer et ciel", it="Mare e cielo",
                   pt="Mar e céu"),
    "Space": dict(en="Space", es="Espacio", de="Weltraum", fr="Espace", it="Spazio", pt="Espaço"),
    "Japan": dict(en="Japan", es="Japón", de="Japan", fr="Japon", it="Giappone", pt="Japão"),
    "Sports": dict(en="Sports", es="Deportes", de="Sport", fr="Sports", it="Sport", pt="Esportes"),
    "Night": dict(en="Night", es="Noche", de="Nacht", fr="Nuit", it="Notte", pt="Noite"),
    "Minimal": dict(en="Minimal", es="Minimal", de="Minimal", fr="Minimal", it="Minimal", pt="Minimal"),
    "Rain": dict(en="Rain", es="Lluvia", de="Regen", fr="Pluie", it="Pioggia", pt="Chuva"),
    "Fantasy": dict(en="Fantasy", es="Fantasía", de="Fantasie", fr="Imaginaire", it="Fantasia", pt="Fantasia"),
    "Psychedelic": dict(en="Psychedelic", es="Psicodélicas", de="Psychedelisch", fr="Psychédélique", it="Psichedelia", pt="Psicodélicas"),
    "Pirates": dict(en="Pirates", es="Piratas", de="Piraten", fr="Pirates", it="Pirati", pt="Piratas"),
    "Details": dict(en="Little things", es="Detalles", de="Kleinigkeiten", fr="Petits riens", it="Dettagli", pt="Detalhes"),
    "Roads": dict(en="Roads", es="Carreteras", de="Straßen", fr="Routes", it="Strade", pt="Estradas"),
    "Warriors": dict(en="Warriors", es="Guerreros", de="Krieger", fr="Guerriers", it="Guerrieri", pt="Guerreiros"),
    "Kawaii": dict(en="Kawaii", es="Kawaii", de="Kawaii", fr="Kawaii", it="Kawaii", pt="Kawaii"),
    "Stickers": dict(en="Stickers", es="Stickers", de="Sticker", fr="Stickers", it="Sticker", pt="Adesivos"),
    "Windows": dict(en="Windows & doors", es="Ventanas y puertas", de="Fenster & Türen", fr="Fenêtres et portes",
                    it="Finestre e porte", pt="Janelas e portas"),
}
FREE_PER_COLLECTION = 2


# --- catalog -------------------------------------------------------------------------------------

def catalog():
    try:
        return load_catalog()
    except FileNotFoundError:
        return {"schema": 1, "collections": [
            {"id": cid, "names": names, "photos": []} for cid, names in COLLECTION_NAMES.items()
        ]}


def collection(cat, cid):
    for c in cat["collections"]:
        if c["id"] == cid:
            return c
    names = COLLECTION_NAMES.get(cid) or {lang: cid for lang in LANGUAGES}
    c = {"id": cid, "names": names, "photos": []}
    cat["collections"].append(c)
    return c


def put(cat, cid, entry):
    """Adds or replaces [entry] in collection [cid], keeping its place if it was there."""
    photos = collection(cat, cid)["photos"]
    for i, p in enumerate(photos):
        if p["id"] == entry["id"]:
            if entry.get("free") is None and "free" in p:
                entry["free"] = p["free"]
            photos[i] = entry
            return
    photos.append(entry)


def mark_free(cat):
    """The first pictures of each collection are free, unless a picture already says otherwise."""
    for c in cat["collections"]:
        for i, p in enumerate(c["photos"]):
            p.setdefault("free", i < FREE_PER_COLLECTION)


# --- images --------------------------------------------------------------------------------------

def to_srgb(img):
    img = ImageOps.exif_transpose(img)
    icc = img.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            img = ImageCms.profileToProfile(img, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
        except Exception:  # noqa: BLE001 - a broken profile: keep the pixels as they are
            pass
    return img.convert("RGB")


def band(img, crop, focus):
    """Cuts [crop] (fractions), then a BAND-wide strip around [focus]. Returns the strip and the focus in it."""
    w, h = img.size
    l, t, r, b = crop
    img = img.crop((round(l * w), round(t * h), round(r * w), round(b * h)))
    w, h = img.size
    fx, fy = focus
    if w / h > BAND:
        bw = round(h * BAND)
        left = min(max(round(fx * w - bw / 2), 0), w - bw)
        img = img.crop((left, 0, left + bw, h))
        fx = (fx * w - left) / bw
    if img.height > MAX_HEIGHT:
        img = img.resize((round(img.width * MAX_HEIGHT / img.height), MAX_HEIGHT), Image.LANCZOS)
    return img, [round(min(max(fx, 0), 1), 3), round(fy, 3)]


def write(pid, img):
    out = IMAGES / pid
    out.mkdir(parents=True, exist_ok=True)
    img.save(out / "full.webp", "WEBP", quality=80, method=6)
    thumb = img.resize((THUMB_WIDTH, round(img.height * THUMB_WIDTH / img.width)), Image.LANCZOS)
    thumb.save(out / "thumb.webp", "WEBP", quality=74, method=6)
    size = (out / "full.webp").stat().st_size // 1024
    print(f"  {pid}: {img.width}×{img.height}, {size} KB")
    return f"{BASE_URL}/img/{pid}/full.webp", f"{BASE_URL}/img/{pid}/thumb.webp"


def download(url, name):
    path = CACHE / "originals" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(url))
        time.sleep(1)
    return Image.open(path)


# --- commands ------------------------------------------------------------------------------------

def commons(args):
    pool = json.loads((CACHE / "sheets" / f"{args.collection}-pool.json").read_text(encoding="utf-8"))
    picks = json.loads((CACHE / "picks" / f"{args.collection}.json").read_text(encoding="utf-8"))
    cat = catalog()
    for pick in picks:
        c = pool[pick["pool"]]
        pid = f"wm-{c['pageid']}"
        # A rendition just tall enough, not the original (often 30+ MB).
        width = c["width"] if c["height"] <= MAX_HEIGHT else round(c["width"] * MAX_HEIGHT / c["height"])
        url = c["original"]
        if width < c["width"]:
            info = commons_api(action="query", titles="File:" + c["file"], prop="imageinfo", iiprop="url",
                               iiurlwidth=str(width))["query"]["pages"][0]["imageinfo"][0]
            url = info.get("thumburl") or url
        img, focus = band(to_srgb(download(url, f"{pid}.jpg")), [0, 0, 1, 1], pick.get("focus", [0.5, 0.5]))
        image, thumb = write(pid, img)
        put(cat, args.collection, {
            "id": pid, "title": pick.get("title") or c["title"], "creator": pick.get("creator") or c["creator"],
            "date": year(c["date"]), "source": "wikimedia", "license": c["license"], "page": c["page"],
            "image": image, "thumb": thumb, "crop": [0, 0, 1, 1], "focus": focus, "free": pick.get("free", None),
        })
    for p in collection(cat, args.collection)["photos"]:
        if p.get("free") is None:
            del p["free"]
    mark_free(cat)
    save_catalog(cat)
    credits(None)


def legacy(args):
    old = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cat = catalog()
    for oc in old["collections"]:
        for p in oc["photos"]:
            ext = ".png" if p["image"].endswith(".png") else ".jpg"
            img, focus = band(to_srgb(download(p["image"], p["id"] + ext)), p["crop"], p["focus"])
            image, thumb = write(p["id"], img)
            put(cat, oc["id"], {
                "id": p["id"], "title": p["title"], "creator": p["creator"], "date": p.get("date", ""),
                "source": p["source"], "license": "Public domain", "page": p["page"], "image": image,
                "thumb": thumb, "crop": [0, 0, 1, 1], "focus": focus, "free": None,
            })
    for c in cat["collections"]:
        for p in c["photos"]:
            if p.get("free") is None:
                p.pop("free", None)
    mark_free(cat)
    save_catalog(cat)
    credits(None)


def year(text):
    m = re.search(r"(?<!\d)(1[5-9]\d\d|20\d\d)(?!\d)", text or "")
    return m.group(1) if m else ""


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "untitled"


def matches(src, out):
    """Whether [out] shows the same picture as [src]: the GPU sometimes returns black or half-done images."""
    a = Image.open(src).convert("RGB").resize((96, 170))
    b = Image.open(out).convert("RGB").resize((96, 170))
    # Region by region: a dark picture with a black strip still averages close to its source.
    cells = ImageChops.difference(a, b).convert("L").resize((12, 20), Image.BOX)
    if max(cells.getextrema()) >= 40:
        return False
    # Nor its brightest pixels: a black strip over a night sky only loses a few stars.
    a = Image.open(src).convert("L")
    b = Image.open(out).convert("L").resize(a.size)
    w, h = a.size
    for gy in range(16):
        for gx in range(4):
            box = (w * gx // 4, h * gy // 16, w * (gx + 1) // 4, h * (gy + 1) // 16)
            peak = a.crop(box).getextrema()[1]
            if peak > 40 and b.crop(box).getextrema()[1] < 0.4 * peak:
                return False
    return True


def upscaled(f):
    """[f] made 4× larger with Real-ESRGAN (.cache/esrgan, see README), cached; None if that fails."""
    out = CACHE / "upscaled" / (f.stem + ".png")
    exe = CACHE / "esrgan" / "realesrgan-ncnn-vulkan.exe"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Smaller tiles when the GPU runs out of memory.
    for tile in (None, 128, 64):
        if out.exists() and matches(f, out):
            return out
        if not exe.exists():
            return None
        print(f"  upscaling {f.name}" + (f" (tiles of {tile})" if tile else "") + "…")
        subprocess.run([str(exe), "-i", str(f), "-o", str(out), "-n", "realesrgan-x4plus"]
                       + (["-t", str(tile)] if tile else []),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out if out.exists() and matches(f, out) else None


# Folder names people may use in originals/inbox/ for a collection, besides its id.
FOLDER_ALIASES = {
    "animales": "Wildlife", "animals": "Wildlife", "japon": "Japan", "japón": "Japan",
    "deporte": "Sports", "deportes": "Sports", "noche": "Night", "viajes": "Travel",
    "naturaleza": "Nature", "espacio": "Space", "mar": "SeaSky", "minimal": "Minimal",
    "lluvia": "Rain", "fantasia": "Fantasy", "fantasía": "Fantasy", "psicodelicas": "Psychedelic",
    "piratas": "Pirates", "detalles": "Details", "mar y cielo": "SeaSky", "carreteras": "Roads",
    "guerrero": "Warriors", "guerreros": "Warriors", "ventanas": "Windows",
}


def collection_for(folder):
    name = folder.name
    known = {cid.lower(): cid for cid in COLLECTION_NAMES}
    return FOLDER_ALIASES.get(name.lower()) or known.get(name.lower()) or name


def originals(args):
    """Adds the pictures in originals/inbox/ as Lumen Originals.

    Files right in inbox/ go to --collection (Originals); a subfolder is a collection, named by its
    id or an alias ("japon", "deportes"…). Each picture may come with <name>.json: {"id", "title",
    "focus", "free"}. Pictures go in the order of their "id" (else their file name). Small ones are
    upscaled first. The catalog is saved after every picture, so a long run can be resumed.
    """
    inbox = ROOT / "originals" / "inbox"
    done = ROOT / "originals" / "done"
    cat = catalog()

    def meta_of(f):
        m = f.with_suffix(".json")
        return json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}

    def pictures(folder):
        return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")),
                      key=lambda p: meta_of(p).get("id") or p.stem)

    batches = [(args.collection, inbox)] + [(collection_for(d), d) for d in sorted(inbox.iterdir()) if d.is_dir()]
    if not any(pictures(folder) for _, folder in batches):
        print("originals/inbox/ is empty")
        return
    for cid, folder in batches:
        for f in pictures(folder):
            meta_file = f.with_suffix(".json")
            meta = meta_of(f)
            img = to_srgb(Image.open(f))
            if min(img.size) < MIN_ORIGINAL_SHORT_SIDE:
                big = upscaled(f)
                if big is None:
                    print(f"! {f.name} is {img.width}×{img.height}: upscale it so its short side is at least "
                          f"{MIN_ORIGINAL_SHORT_SIDE} px (or install Real-ESRGAN, see README). Skipped.")
                    continue
                img = to_srgb(Image.open(big))
            title = meta.get("title") or f.stem.replace("_", " ").replace("-", " ").strip().capitalize()
            pid = "lumen-" + slug(meta.get("id") or f.stem)
            img, focus = band(img, [0, 0, 1, 1], meta.get("focus", [0.5, 0.5]))
            image, thumb = write(pid, img)
            entry = {
                "id": pid, "title": title, "creator": meta.get("creator", "Lumen"), "date": meta.get("date", ""),
                "source": "lumen", "license": "Lumen", "page": meta.get("page", ""), "image": image, "thumb": thumb,
                "crop": [0, 0, 1, 1], "focus": focus,
            }
            if "free" in meta:
                entry["free"] = bool(meta["free"])
            put(cat, cid, entry)
            target = done / folder.relative_to(inbox)
            target.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), target / f.name)
            if meta_file.exists():
                shutil.move(str(meta_file), target / meta_file.name)
            mark_free(cat)
            save_catalog(cat)
        if folder != inbox and folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
    credits(None)


def arrange(args):
    """Puts Lumen's own pictures first in every collection, the collections in --order, and makes
    exactly the first FREE_PER_COLLECTION pictures of each collection free."""
    cat = catalog()
    order = [cid for cid in (args.order or "").split(",") if cid]
    rank = {cid: i for i, cid in enumerate(order)}
    cat["collections"].sort(key=lambda c: rank.get(c["id"], len(rank)))
    for c in cat["collections"]:
        c["photos"].sort(key=lambda p: p["source"] != "lumen")
        for i, p in enumerate(c["photos"]):
            p["free"] = i < FREE_PER_COLLECTION
    save_catalog(cat)
    credits(None)
    for c in cat["collections"]:
        print(f"{c['id']}: {len(c['photos'])}")


SOURCE_NAMES = {"wikimedia": "Wikimedia Commons", "met": "The Metropolitan Museum of Art",
                "nasa": "NASA", "usgov": "U.S. Government", "lumen": "Lumen Originals"}


def credits(_):
    cat = catalog()
    lines = [
        "# Credits", "",
        "The pictures in this repository are resized and cropped to a phone's shape (that is the only change).",
        "Each keeps the license of its source, listed below with its author and a link to the original.",
        "Lumen Originals are made for Lumen.", "",
    ]
    for c in cat["collections"]:
        if not c["photos"]:
            continue
        lines += [f"## {c['names']['en']}", ""]
        for p in c["photos"]:
            source = SOURCE_NAMES.get(p["source"], p["source"])
            link = f" — <{p['page']}>" if p.get("page") else ""
            date = f", {p['date']}" if p.get("date") else ""
            lines.append(f"- **{p['title']}** — {p['creator']}{date} — {p['license']} — {source}{link}")
        lines.append("")
    (ROOT / "CREDITS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("commons")
    p.add_argument("collection")
    p.set_defaults(run=commons)
    p = sub.add_parser("legacy")
    p.add_argument("file")
    p.set_defaults(run=legacy)
    p = sub.add_parser("originals")
    p.add_argument("--collection", default="Originals")
    p.set_defaults(run=originals)
    p = sub.add_parser("arrange")
    p.add_argument("--order", help="collection ids, comma-separated, in gallery order")
    p.set_defaults(run=arrange)
    sub.add_parser("credits").set_defaults(run=credits)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
