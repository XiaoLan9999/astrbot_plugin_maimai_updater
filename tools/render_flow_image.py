from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "maimai-updater-flow.png"
WIDTH = 1400
HEIGHT = 860


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    for path in font_candidates:
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def centered(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.ImageFont, fill: tuple[int, int, int, int]) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) / 2, y), text, font=font, fill=fill)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGBA", (WIDTH, HEIGHT), (230, 250, 255, 255))
    draw = ImageDraw.Draw(img)

    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        red = int(232 * (1 - t) + 130 * t)
        green = int(251 * (1 - t) + 212 * t)
        blue = 255
        draw.line([(0, y), (WIDTH, y)], fill=(red, green, blue, 255))

    for x in range(0, WIDTH, 36):
        for y in range(0, HEIGHT, 36):
            draw.ellipse((x + 7, y + 7, x + 11, y + 11), fill=(255, 255, 255, 130))
            draw.ellipse((x + 24, y + 25, x + 28, y + 29), fill=(50, 170, 220, 45))

    wave = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    wave_draw = ImageDraw.Draw(wave)
    wave_draw.polygon(
        [
            (0, 715),
            (120, 680),
            (250, 710),
            (390, 675),
            (545, 720),
            (710, 675),
            (875, 715),
            (1030, 665),
            (1190, 700),
            (1400, 650),
            (1400, 860),
            (0, 860),
        ],
        fill=(242, 253, 255, 188),
    )
    wave_draw.polygon(
        [
            (0, 755),
            (180, 705),
            (350, 760),
            (525, 718),
            (720, 758),
            (910, 730),
            (1110, 698),
            (1270, 736),
            (1400, 706),
            (1400, 860),
            (0, 860),
        ],
        fill=(214, 246, 255, 210),
    )
    img.alpha_composite(wave)

    title_font = load_font(50, bold=True)
    subtitle_font = load_font(24)
    card_title_font = load_font(28, bold=True)
    body_font = load_font(22)
    foot_font = load_font(20)
    mark_font = load_font(24, bold=True)

    centered(draw, "maimai 水鱼更新器", 54, title_font, (17, 107, 156, 255))
    centered(draw, "绑定水鱼 Token 后，发送“更新水鱼 SGID”更新 B50", 120, subtitle_font, (47, 126, 168, 255))

    def rounded_rect_with_shadow(box: tuple[int, int, int, int], radius: int = 24) -> None:
        x1, y1, x2, y2 = box
        shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle((x1, y1 + 10, x2, y2 + 10), radius=radius, fill=(47, 143, 189, 48))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        img.alpha_composite(shadow)
        draw.rounded_rectangle(box, radius=radius, fill=(250, 254, 255, 244), outline=(106, 200, 242, 255), width=3)

    def card(x: int, y: int, number: int, title: str, line1: str, line2: str, foot: str) -> None:
        rounded_rect_with_shadow((x, y, x + 288, y + 250))
        draw.ellipse((x + 20, y + 20, x + 72, y + 72), fill=(27, 167, 225, 255))
        number_text = str(number)
        bbox = draw.textbbox((0, 0), number_text, font=card_title_font)
        draw.text(
            (x + 46 - (bbox[2] - bbox[0]) / 2, y + 46 - (bbox[3] - bbox[1]) / 2 - 3),
            number_text,
            font=card_title_font,
            fill=(255, 255, 255, 255),
        )
        draw.text((x + 82, y + 31), title, font=card_title_font, fill=(18, 101, 143, 255))
        draw.text((x + 40, y + 98), line1, font=body_font, fill=(36, 95, 122, 255))
        draw.text((x + 40, y + 134), line2, font=body_font, fill=(36, 95, 122, 255))
        draw.text((x + 40, y + 186), foot, font=foot_font, fill=(92, 135, 152, 255))

    def arrow(x1: int, y: int, x2: int) -> None:
        draw.line((x1, y, x2, y), fill=(23, 158, 213, 255), width=7)
        draw.polygon([(x2, y), (x2 - 24, y - 16), (x2 - 24, y + 16)], fill=(23, 158, 213, 255))

    card(72, 220, 1, "绑定水鱼", "maimaitoken", "<Import-Token>", "只保存水鱼 Token")
    arrow(374, 344, 456)
    card(474, 220, 2, "获取 SGID", "官方公众号 / 网页", "识别二维码文本", "180 秒内使用")
    arrow(776, 344, 858)
    card(876, 220, 3, "触发更新", "更新水鱼", "SGWCMAID...", "群聊自动尝试撤回")

    rounded_rect_with_shadow((286, 526, 1114, 708))
    draw.text((340, 581), "完成后", font=card_title_font, fill=(18, 101, 143, 255))
    draw.text((340, 629), "水鱼数据已更新，可以继续用现有 B50 插件查询。", font=subtitle_font, fill=(36, 95, 122, 255))
    draw.text((340, 669), "插件不保存 SGID，也不保存官方临时凭据。", font=foot_font, fill=(92, 135, 152, 255))
    draw.ellipse((994, 599, 1082, 668), fill=(27, 167, 225, 42))
    draw.ellipse((1038, 594, 1062, 618), fill=(27, 167, 225, 82))

    centered(draw, "Designed by XiaoLan9999", 807, mark_font, (21, 143, 202, 230))
    img.convert("RGB").save(OUTPUT, quality=95)


if __name__ == "__main__":
    main()
