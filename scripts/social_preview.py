from pathlib import Path

from brand import CORAL, VIOLET, logo
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 640
BG = (14, 14, 17)
FONTS = Path("C:/Windows/Fonts")


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)


def glow(img: Image.Image) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((-260, -320, 520, 420), fill=(*CORAL, 70))
    d.ellipse((760, 260, 1540, 980), fill=(*VIOLET, 80))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(140)))


def screenshot(root: Path, width: int) -> Image.Image:
    shot = Image.open(root / "docs" / "images" / "app-escuro.png").convert("RGBA")
    shot.thumbnail((width, H - 120), Image.LANCZOS)
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, shot.width - 1, shot.height - 1), radius=18, fill=255)
    shot.putalpha(mask)
    return shot


def build(root: Path) -> Image.Image:
    img = Image.new("RGBA", (W, H), (*BG, 255))
    glow(img)
    d = ImageDraw.Draw(img)

    img.alpha_composite(logo(96), (72, 84))
    d.text((188, 92), "Salvaí", font=font(True, 64), fill="white")
    headline = font(True, 44)
    d.text((72, 212), "Baixe vídeos e músicas", font=headline, fill="white")
    d.text((72, 266), "em MP4 e MP3 no Windows", font=headline, fill=(242, 120, 126))
    text_right = 72 + max(d.textlength(t, font=headline) for t in ("Baixe vídeos e músicas", "em MP4 e MP3 no Windows"))
    d.text(
        (72, 346),
        "YouTube · Instagram · TikTok · X · Facebook\ne mais de 1.800 sites",
        font=font(False, 26),
        fill=(190, 190, 200),
        spacing=10,
    )

    x = 72
    for label in ("Grátis", "Sem anúncios", "Modo celular"):
        width = d.textlength(label, font=font(True, 22)) + 36
        d.rounded_rectangle((x, 470, x + width, 516), radius=23, fill=(38, 38, 46), outline=(60, 60, 70))
        d.text((x + 18, 478), label, font=font(True, 22), fill="white")
        x += width + 12
    d.text((72, 552), "github.com/Kaique292/salvai", font=font(False, 22), fill=(139, 139, 150))

    shot = screenshot(root, int(W - text_right - 48 - 40))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    left, top = W - shot.width - 40, (H - shot.height) // 2
    ImageDraw.Draw(shadow).rounded_rectangle(
        (left + 10, top + 18, left + shot.width + 10, top + shot.height + 18), radius=22, fill=(0, 0, 0, 150)
    )
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    img.alpha_composite(shot, (left, top))
    return img.convert("RGB")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    out = root / "docs" / "images" / "social-preview.png"
    build(root).save(out, optimize=True)
    print(f"{out.relative_to(root)} gerado")
