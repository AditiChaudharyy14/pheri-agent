"""Draw Birgunj Saree Ghar's synthetic catalogue photos: one image per catalogue item and wholesale lot, named by its
photo id (PH-101.png ...), into data/synth/birgunj/photos and web/public/catalog. Drawn by code (a draped cloth in the
item's colours, its name, "synthetic"): no real product photo, nothing we don't have rights to. Deterministic.

    python scripts/make_catalog_photos.py
"""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
SHOP = REPO / "data" / "synth" / "birgunj" / "shop.json"
OUT = [REPO / "data" / "synth" / "birgunj" / "photos", REPO / "web" / "public" / "catalog"]
COLOURS = {  # item id -> (cloth, border)
    "BSG-S01": ((178, 34, 34), (212, 175, 55)), "BSG-S02": ((110, 20, 40), (212, 175, 55)),
    "BSG-S03": ((30, 90, 140), (230, 120, 40)), "BSG-S04": ((240, 230, 210), (60, 130, 90)),
    "BSG-S05": ((240, 190, 30), (190, 40, 40)), "BSG-S06": ((200, 90, 140), (250, 240, 240)),
    "BSG-L01": ((150, 20, 60), (230, 190, 90)), "BSG-K01": ((40, 110, 100), (240, 220, 160)),
    "BSG-P01": ((120, 100, 80), (220, 200, 170)), "BSG-B01": ((90, 60, 140), (230, 200, 120)),
}


def draw(item: dict, cloth: tuple, border: tuple) -> Image.Image:
    rnd = random.Random(item["photo"])
    w, h = 480, 600
    img = Image.new("RGB", (w, h), (247, 244, 238))
    d = ImageDraw.Draw(img)
    for i in range(14):  # folds of a draped cloth
        x = 60 + i * 26 + rnd.randint(-4, 4)
        shade = tuple(max(0, min(255, c + (18 if i % 2 else -18))) for c in cloth)
        d.polygon([(x, 80), (x + 30, 80), (x + 46 + rnd.randint(-6, 6), 470), (x + 8, 470)], fill=shade)
    d.rectangle([60, 440, 420, 470], fill=border)  # the border (pallu)
    for x in range(70, 420, 22):
        d.ellipse([x, 448, x + 12, 460], fill=cloth)
    font = ImageFont.load_default(size=22) if hasattr(ImageFont, "load_default") else None
    d.text((40, 500), item["name"], fill=(30, 30, 30), font=font)
    small = ImageFont.load_default(size=15) if font else None
    # the customer sees this image: no photo id or any internal code on it
    d.text((40, 540), "Birgunj Saree Ghar · synthetic catalogue photo", fill=(110, 110, 110), font=small)
    return img


def main() -> None:
    shop = json.loads(SHOP.read_text(encoding="utf-8"))
    items = shop["catalog"] + shop.get("bundles", [])
    for folder in OUT:
        folder.mkdir(parents=True, exist_ok=True)
    seen = set()
    for it in items:
        if it["photo"] in seen:
            continue
        seen.add(it["photo"])
        base = it["id"] if it["id"] in COLOURS else next(
            (c["id"] for c in shop["catalog"] if c["photo"] == it["photo"]), "BSG-S04")
        img = draw(it, *COLOURS.get(base, ((120, 120, 120), (200, 200, 200))))
        for folder in OUT:
            img.save(folder / f"{it['photo']}.png", optimize=True)
    print(f"{len(seen)} photos into {', '.join(str(f) for f in OUT)}")


if __name__ == "__main__":
    main()
