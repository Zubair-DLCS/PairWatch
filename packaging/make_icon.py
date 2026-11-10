"""Draws the PairWatch icon: two heads (blue and orange) sharing one screen with </>."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([40, 40, S - 40, S - 40], radius=210, fill=(32, 36, 43))
# screen
d.rounded_rectangle([200, 170, 824, 560], radius=40, fill=(245, 247, 250))
d.rectangle([470, 560, 554, 620], fill=(245, 247, 250))
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 210)
except OSError:
    font = ImageFont.load_default()
d.text((512, 365), "</>", fill=(46, 125, 50), font=font, anchor="mm")
# two heads and shoulders
for cx, col in ((350, (47, 109, 181)), (674, (224, 123, 57))):
    d.ellipse([cx - 95, 640, cx + 95, 830], fill=col)
    d.pieslice([cx - 170, 820, cx + 170, 1160], 180, 360, fill=col)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=210, fill=255)
img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (S, S), 0), mask))
out = Path(__file__).parent
img.save(out / "pairwatch.png")
img.save(out / "pairwatch.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("saved")
