from pathlib import Path

from brand import VIOLET, logo
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, S = 460, 250, 4
R = 10
BG, BORDER, TEXT, MUTED, ACCENT = "#0E0E11", "#26262E", "#EDEDF0", "#8B8B96", (229, 72, 77)
FONTS = Path("C:/Windows/Fonts")

img = Image.new("RGB", (W * S, H * S), BG)

glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse((-40 * S, -60 * S, 200 * S, 170 * S), fill=(*ACCENT, 40))
ImageDraw.Draw(glow).ellipse((40 * S, 20 * S, 260 * S, 200 * S), fill=(*VIOLET, 22))
img.paste(glow.filter(ImageFilter.GaussianBlur(40 * S)), (0, 0), glow.filter(ImageFilter.GaussianBlur(40 * S)))

d = ImageDraw.Draw(img)
d.rounded_rectangle((0, 0, W * S - 1, H * S - 1), radius=R * S, outline=BORDER, width=S)

x, y, size = 36, 46, 56
mark = logo(size * S)
img.paste(mark, (x * S, y * S), mark)

title = ImageFont.truetype(str(FONTS / "seguisb.ttf"), 22 * S)
sub = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 12 * S)
d.text(((x + size + 16) * S, (y + 6) * S), "Salvaí", font=title, fill=TEXT)
d.text(((x + size + 17) * S, (y + 36) * S), "Viu, gostou, salvaí.", font=sub, fill=MUTED)

mask = Image.new("L", img.size, 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, W * S - 1, H * S - 1), radius=R * S, fill=255)
mask = mask.resize((W, H), Image.BOX).point(lambda v: 255 if v >= 128 else 0)

out = Path(__file__).resolve().parent.parent / "assets" / "splash.png"
final = img.resize((W, H), Image.LANCZOS).convert("RGBA")
final.putalpha(mask)
final.save(out)
print(out)
