# Lumen wallpapers

The wallpaper collections of [Lumen Launcher](https://github.com/marrietapo/lumen-launcher).
The app reads `v1/catalog.json` from this site and downloads the pictures in `img/` as people
browse them. Adding pictures here makes them appear in Lumen without an app update.

Every picture keeps the license of its source. See [CREDITS.md](CREDITS.md) for each author,
license and original.

## Adding your own pictures (Lumen Originals)

1. **Make the picture.** Use a generator whose terms allow commercial use with your plan
   (Midjourney paid, ChatGPT, Adobe Firefly, Gemini…). Don't ask for "in the style of" a living
   artist, and don't include brands, logos or real people.
2. **Make it tall.** Use a portrait shape (9:16 or 9:20). If the short side is under 1440 px,
   `build.py` upscales it 4× with Real-ESRGAN, which must be unzipped into `.cache/esrgan/`
   ([realesrgan-ncnn-vulkan for Windows](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0)).
   It takes about two minutes per picture.
3. **Drop it in `originals/inbox/`.** Add a `.json` with the same name if you want to set details:
   ```json
   { "id": "22-neon-dunes", "title": "Neon dunes", "focus": [0.5, 0.5], "free": true }
   ```
   - `id` names the picture for good and sets its place in the collection (sorted by id).
   - `focus` is the point the phone keeps centered (x, y from 0 to 1).
   - `free: true` makes the picture free. Otherwise the first two of a collection are free and the
     rest need Pro.
   - Write the platform, plan, date and prompt in `originals/SOURCES.md`. That way you can show
     where each picture came from if anyone ever asks.
4. **Build and check:**
   ```
   .venv\Scripts\python -I tools\build.py originals
   .venv\Scripts\python -I tools\check.py
   ```
5. **Commit and push.** Cloudflare Pages publishes the site, and Lumen picks up the new catalog
   within 12 hours, or right away on a fresh install.

To start a new collection, use `--collection <Id>`. Then add its names in the six languages to
`COLLECTION_NAMES` in `tools/build.py`, or straight into `v1/catalog.json`.

## Photos from Wikimedia Commons

1. `tools/commons_candidates.py` lists featured pictures that Lumen can use. They must have the
   right license, be big enough, and carry no personality-rights, trademark or
   freedom-of-panorama warning.
2. `tools/contact_sheet.py` draws them as a phone would show them.
3. The picks go in `.cache/picks/<Collection>.json`: pool index, focus, title, and the creator if
   the metadata is messy.
4. `tools/build.py commons <Collection>` downloads, crops and adds them.

## Setup

```
py -m venv .venv
.venv\Scripts\python -m pip install pillow
```
