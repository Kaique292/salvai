from PIL import Image, ImageDraw

CORAL, VIOLET = (242, 84, 91), (142, 78, 198)


def gradient(size: int) -> Image.Image:
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(CORAL, VIOLET, strict=False))
    return g


def logo(size: int, radius_ratio: float = 0.27) -> Image.Image:
    s = size * 4
    base = gradient(64).resize((s, s), Image.BICUBIC).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * radius_ratio), fill=255)
    base.putalpha(mask)

    d = ImageDraw.Draw(base)
    w = max(4, int(s * 0.085))
    cx = s / 2
    top, tip = s * 0.24, s * 0.60
    d.line([(cx, top), (cx, tip)], fill="white", width=w)
    arm = s * 0.17
    d.line([(cx - arm, tip - arm), (cx, tip), (cx + arm, tip - arm)], fill="white", width=w, joint="curve")
    tray_y, tray_x = s * 0.76, s * 0.25
    d.line([(tray_x, tray_y), (s - tray_x, tray_y)], fill="white", width=w)
    r = w / 2
    for px, py in [
        (cx, top),
        (cx - arm, tip - arm),
        (cx + arm, tip - arm),
        (tray_x, tray_y),
        (s - tray_x, tray_y),
        (cx, tip),
    ]:
        d.ellipse((px - r, py - r, px + r, py + r), fill="white")
    return base.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    img = logo(256)
    img.save(
        root / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    img.save(root / "assets" / "logo.png")
    print("assets/icon.ico e assets/logo.png gerados")
