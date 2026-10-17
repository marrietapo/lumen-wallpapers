"""Shared helpers for the Lumen wallpaper tools: HTTP with a polite User-Agent, licenses, paths."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "v1" / "catalog.json"
IMAGES = ROOT / "img"
CACHE = ROOT / ".cache"

# Wikimedia's User-Agent policy asks for a name, a way to reach us and what the client is.
USER_AGENT = (
    "LumenWallpapers/1.0 (https://github.com/marrietapo/lumen-wallpapers; marrietaporras@gmail.com) "
    "python-urllib"
)

# Where the catalog's images are served from. The app accepts only URLs under this base.
BASE_URL = "https://fondos.fungicode.io"

LANGUAGES = ["en", "es", "de", "fr", "it", "pt"]


def get(url, *, retries=4, accept=None):
    """GETs [url] and returns the body, backing off on 429/5xx."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def commons_api(**params):
    params = {"format": "json", "formatversion": "2", **params}
    return json.loads(get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)))


def strip_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text)
    return (
        text.replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'").replace("&nbsp;", " ").strip()
    )


_LICENSE = re.compile(r"^(?:cc[- ])?(by(?:-sa)?)[- ](\d\.\d)", re.I)


def normalize_license(short_name):
    """The license as shown in the app ("CC BY-SA 4.0", "CC0", "Public domain"), or None if Lumen can't use it."""
    s = (short_name or "").strip()
    low = s.lower()
    if not s or "nc" in re.split(r"[- ]", low) or "-nd" in low or " nd" in low:
        return None
    if low in ("public domain", "pd", "no restrictions") or low.startswith("pd-") or low.startswith("public domain"):
        return "Public domain"
    if low in ("cc0", "cc0 1.0", "cc-zero"):
        return "CC0"
    m = _LICENSE.match(low)
    if m:
        kind, version = m.groups()
        return f"CC {kind.upper()} {version}"
    return None


ALLOWED_LICENSES = re.compile(r"^(Public domain|CC0|CC BY \d\.\d|CC BY-SA \d\.\d|Lumen)$")


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def save_catalog(catalog):
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
