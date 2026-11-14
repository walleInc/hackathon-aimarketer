"""Бренд-кит компании и рендер изображений по правилам брендбука.

Реализованные правила (по брендбуку САЛАВАТСТЕКЛО, их можно задать любой компании через бренд-кит):
- логотип используется только из оригинальных файлов: без искажений, поворотов, обводок и смены цветов;
- на светлом фоне — основной цветной логотип, на тёмном — белый; чёрный — запасной монохромный вариант;
- логотип не ставится на границу контрастных элементов (выбирается самый ровный угол);
- охранное поле вокруг логотипа (≈ высота буквы «О» ≈ 0,6 высоты блока) и минимальный размер (110 px);
- шрифты: заголовок — Intro Black, основной текст — Avenir Next Cyr; цвета — только фирменная палитра.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .media import media_path, new_media_file
from .models import BrandAsset, Company

DEFAULT_FONTS = Path(__file__).resolve().parents[1] / "brand_packs" / "salavatsteklo" / "fonts"
FALLBACK_PRIMARY = "#196C7F"
LIGHT_BG = "#DDE1E1"
DARK_TEXT = "#285055"
MIN_LOGO_PX = 110

LOGO_KINDS = ("logo_color", "logo_white", "logo_black")
ASSET_KINDS = (*LOGO_KINDS, "icon", "pattern", "font_heading", "font_body", "example")


@dataclass
class Brand:
    colors: list[str] = field(default_factory=list)
    assets: dict[str, list[Path]] = field(default_factory=dict)

    @property
    def primary(self) -> str:
        return self.colors[0] if self.colors else FALLBACK_PRIMARY

    def first(self, *kinds: str) -> Path | None:
        for k in kinds:
            for p in self.assets.get(k, []):
                if p.exists():
                    return p
        return None

    @property
    def has_logo(self) -> bool:
        return self.first(*LOGO_KINDS) is not None


def parse_colors(raw: str) -> list[str]:
    return [c.upper() for c in re.findall(r"#[0-9a-fA-F]{6}", raw or "")]


async def load_brand(session: AsyncSession, company: Company) -> Brand:
    rows = (await session.execute(select(BrandAsset).where(BrandAsset.company_id == company.id))).scalars()
    assets: dict[str, list[Path]] = {}
    for a in rows:
        assets.setdefault(a.kind, []).append(media_path(a.path))
    return Brand(colors=parse_colors(company.brand_colors), assets=assets)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _logo_image(brand: Brand, *kinds: str) -> Image.Image | None:
    path = brand.first(*kinds)
    if path is None:
        return None
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()  # файлы логотипов лежат на холсте с полями — обрезаем до самого знака
    return img.crop(bbox) if bbox else img


def _font(brand: Brand, role: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    uploaded = brand.first("font_heading" if role == "heading" else "font_body")
    default = DEFAULT_FONTS / ("Intro.ttf" if role == "heading" else "avenirnextcyr-regular.ttf")
    # запасные шрифты с кириллицей (в Docker-образе ставится fonts-dejavu-core)
    dejavu = Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if role == "heading" else "DejaVuSans.ttf")
    mac = Path("/System/Library/Fonts/Supplemental") / ("Arial Bold.ttf" if role == "heading" else "Arial.ttf")
    for path in (uploaded, default, dejavu, mac):
        if path and Path(path).exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        cur = ""
        for word in paragraph.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _fit(draw, brand: Brand, role: str, text: str, max_w: int, max_h: int, start: int, min_size: int = 26):
    """Подбирает наибольший размер шрифта, при котором текст помещается в блок."""
    size = start
    while True:
        font = _font(brand, role, size)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.18)
        if len(lines) * line_h <= max_h or size <= min_size:
            return font, lines, line_h
        size -= 2


def _paste_logo(img: Image.Image, logo: Image.Image, box_x: int, box_y: int, width: int) -> None:
    w = max(width, MIN_LOGO_PX)
    h = int(logo.height * w / logo.width)
    img.alpha_composite(logo.resize((w, h), Image.LANCZOS), (box_x, box_y))


def place_logo(img: Image.Image, brand: Brand, scale: float = 0.22) -> Image.Image:
    """Ставит логотип на готовое изображение: самый ровный угол, цветовой вариант по яркости фона."""
    base = img.convert("RGBA")
    ref = _logo_image(brand, *LOGO_KINDS)
    if ref is None:
        return base.convert("RGB")
    W, H = base.size
    lw = max(int(W * scale), MIN_LOGO_PX)
    lh = int(ref.height * lw / ref.width)
    margin = max(int(lh * 0.6), 12)  # охранное поле
    corners = {
        "bl": (margin, H - lh - margin), "br": (W - lw - margin, H - lh - margin),
        "tl": (margin, margin), "tr": (W - lw - margin, margin),
    }
    best, best_score, best_mean = "bl", 1e9, 0.0
    for name, (x, y) in corners.items():
        stat = ImageStat.Stat(base.crop((x, y, x + lw, y + lh)).convert("L"))
        score = stat.stddev[0] - (4 if name == "bl" else 0)  # меньше разброс яркости = нет контрастных границ
        if score < best_score:
            best, best_score, best_mean = name, score, stat.mean[0] / 255
    logo = _logo_image(brand, "logo_color", "logo_black") if best_mean > 0.55 else _logo_image(brand, "logo_white", "logo_color")
    x, y = corners[best]
    _paste_logo(base, logo or ref, x, y, lw)
    return base.convert("RGB")


def render_card(brand: Brand, headline: str, body: str = "", style: str = "dark", size: int = 1080) -> Image.Image:
    """Карточка в фирменном стиле: заголовок шрифтом заголовков, текст основным шрифтом, логотип, паттерн."""
    dark = style == "dark"
    bg = _rgb(brand.primary) if dark else _rgb(LIGHT_BG)
    head_color = (255, 255, 255) if dark else _rgb(brand.primary)
    body_color = (226, 238, 241) if dark else _rgb(DARK_TEXT)
    img = Image.new("RGBA", (size, size), bg + (255,))
    draw = ImageDraw.Draw(img)
    pad = int(size * 0.08)

    pattern_path = brand.first("pattern")
    text_w = size - 2 * pad
    if not dark and pattern_path:
        pat = Image.open(pattern_path).convert("RGBA")
        lum = pat.convert("L")
        pat.putalpha(lum.point(lambda v: 0 if v > 240 else 255))  # белый фон паттерна делаем прозрачным
        bbox = pat.getchannel("A").getbbox()
        if bbox:
            pat = pat.crop(bbox)
        ph = int(size * 0.46)
        pat = pat.resize((int(pat.width * ph / pat.height), ph), Image.LANCZOS)
        img.alpha_composite(pat, (size - pad - pat.width, size - pad - ph))
        text_w = int(size * 0.62)

    y = pad
    head_font, head_lines, head_lh = _fit(draw, brand, "heading", headline.upper(), text_w, int(size * 0.34), int(size * 0.085))
    for line in head_lines:
        draw.text((pad, y), line, font=head_font, fill=head_color)
        y += head_lh
    if body:
        y += int(size * 0.03)
        body_font, body_lines, body_lh = _fit(draw, brand, "body", body, text_w, int(size * 0.26), int(size * 0.038))
        for line in body_lines:
            draw.text((pad, y), line, font=body_font, fill=body_color)
            y += body_lh

    logo = _logo_image(brand, "logo_white", "logo_color") if dark else _logo_image(brand, "logo_color", "logo_black")
    if logo is not None:
        lw = int(size * 0.28)
        lh = int(logo.height * lw / logo.width)
        _paste_logo(img, logo, pad, size - pad - lh, lw)
    return img.convert("RGB")


def save_image(img: Image.Image, subdir: str = "cards") -> str:
    path, url = new_media_file(subdir, ".png")
    img.save(path, "PNG")
    return url
