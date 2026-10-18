from pathlib import Path

from brand import CORAL, VIOLET, logo
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, S = 1280, 400, 2
FONTS = Path("C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parent.parent

img = Image.new("RGB", (W * S, H * S), "#0E0E11")
glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
g = ImageDraw.Draw(glow)
g.ellipse((80 * S, -120 * S, 620 * S, 420 * S), fill=(*CORAL, 70))
g.ellipse((700 * S, 60 * S, 1340 * S, 560 * S), fill=(*VIOLET, 60))
glow = glow.filter(ImageFilter.GaussianBlur(110 * S))
img.paste(glow, (0, 0), glow)

d = ImageDraw.Draw(img)
size = 150
mark = logo(size * S)
x, y = 190, (H - size) // 2
img.paste(mark, (x * S, y * S), mark)

title = ImageFont.truetype(str(FONTS / "seguisb.ttf"), 92 * S)
sub = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 30 * S)
tx = x + size + 48
d.text((tx * S, (y - 4) * S), "Salvaí", font=title, fill="#EDEDF0")
d.text((tx * S, (y + 108) * S), "Viu, gostou, salvaí.", font=sub, fill="#B4B4BE")

chips = ["YouTube", "Instagram", "TikTok", "X", "Facebook", "+1800 sites"]
chip_font = ImageFont.truetype(str(FONTS / "seguisb.ttf"), 17 * S)
cx = tx
for label in chips:
    w = d.textlength(label, font=chip_font) / S + 28
    d.rounded_rectangle(
        (cx * S, 312 * S, (cx + w) * S, 344 * S), radius=16 * S, fill="#1F1F25", outline="#34343E", width=S
    )
    d.text(((cx + 14) * S, 317 * S), label, font=chip_font, fill="#D6D6DE")
    cx += w + 10

out = ROOT / "docs" / "images" / "banner.png"
out.parent.mkdir(parents=True, exist_ok=True)
img.resize((W, H), Image.LANCZOS).save(out, optimize=True)
print(out)
