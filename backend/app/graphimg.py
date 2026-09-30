"""Граф здоровья картинкой: премиум PNG-карта пациента из engine-данных.

Ничего не выдумываем: те же health_map / ОСМС / пакет, что в текстовой версии.
"""
import io
import os

from PIL import Image, ImageDraw, ImageFont

from .schemas import CheckupPackageResponse, UserIntakeData

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

INK = (12, 26, 20)          # глубокий изумрудно-чёрный фон
CARD = (20, 40, 32)         # карточка
EMERALD = (52, 211, 153)    # закрыто / акцент
AMBER = (245, 180, 83)      # следующий шаг
RED = (248, 113, 113)       # срок подошёл
TEXT = (237, 245, 240)
MUTED = (148, 170, 158)

_STATUS = {"done": ("ЗАКРЫТО", EMERALD), "next_step": ("ДАЛЕЕ", AMBER),
           "due": ("СРОК ПОДОШЁЛ", RED)}
_ORDER = {"due": 0, "next_step": 1, "done": 2}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₸"


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_graph_png(result: CheckupPackageResponse,
                     intake: UserIntakeData | None = None) -> bytes:
    W, M = 1080, 64
    rows = sorted(result.health_map, key=lambda h: _ORDER.get(h.status, 3))
    done = sum(1 for h in rows if h.status == "done")
    nxt = sum(1 for h in rows if h.status == "next_step")
    due = sum(1 for h in rows if h.status == "due")

    f_title = _font("Onest-ExtraBold.ttf", 56)
    f_sub = _font("Onest-Medium.ttf", 30)
    f_chip = _font("Onest-Bold.ttf", 30)
    f_item = _font("Onest-SemiBold.ttf", 32)
    f_when = _font("Onest-Regular.ttf", 27)
    f_tag = _font("Onest-Bold.ttf", 20)
    f_foot = _font("Onest-Regular.ttf", 24)

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    item_lines = [_wrap(probe, h.item, f_item, W - 2 * M - 380) for h in rows]
    row_h = [max(len(ls), 1) * 40 + 46 for ls in item_lines]
    H = M + 150 + 96 + 40 + sum(row_h) + 40 + 150 + M

    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    y = M
    # header
    d.text((M, y), "ГРАФ ЗДОРОВЬЯ", font=f_title, fill=TEXT)
    sub_bits = []
    if intake and intake.age:
        sub_bits.append(f"{intake.age} лет")
    if intake and intake.gender:
        sub_bits.append("мужчина" if intake.gender.value == "male" else "женщина")
    if result.prime_package:
        sub_bits.append(result.prime_package.name.replace("Check-up ", "").strip("«»"))
    d.text((M, y + 78), " · ".join(sub_bits) if sub_bits else "персональная карта",
           font=f_sub, fill=MUTED)
    logo_path = os.path.join(_FONT_DIR, "logo-prime.png")
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        lh = 96
        logo = logo.resize((int(logo.width * lh / logo.height), lh))
        img.paste(logo, (W - M - logo.width, y), logo)
    y += 150

    # chips
    chips = [("✓", f"закрыто: {done}", EMERALD), ("→", f"следующий шаг: {nxt}", AMBER),
             ("!", f"срок подошёл: {due}", RED)]
    cx = M
    for mark, label, color in chips:
        text = f"{mark}  {label}"
        tw = d.textlength(text, font=f_chip)
        d.rounded_rectangle([cx, y, cx + tw + 48, y + 68], radius=34, fill=CARD,
                            outline=color, width=3)
        d.text((cx + 24, y + 15), text, font=f_chip, fill=color)
        cx += tw + 48 + 24
    y += 96 + 40

    # rows
    for h, ls, rh in zip(rows, item_lines, row_h):
        label, color = _STATUS.get(h.status, ("", MUTED))
        d.rounded_rectangle([M, y, W - M, y + rh - 14], radius=22, fill=CARD)
        d.ellipse([M + 28, y + 26, M + 52, y + 50], fill=color)
        for i, line in enumerate(ls):
            d.text((M + 84, y + 18 + i * 40), line, font=f_item, fill=TEXT)
        d.text((M + 84, y + 18 + len(ls) * 40), h.when, font=f_when, fill=MUTED)
        tw = d.textlength(label, font=f_tag)
        d.rounded_rectangle([W - M - tw - 36, y + 20, W - M - 8, y + 56], radius=18,
                            outline=color, width=2)
        d.text((W - M - tw - 22, y + 27), label, font=f_tag, fill=color)
        y += rh
    y += 40

    # footer
    foot = []
    if result.osms_free_tests:
        foot.append(f"ОСМС: {len(result.osms_free_tests)} позиций · 0 ₸")
    if result.prime_package and result.prime_package.price_kzt is not None:
        foot.append(f"PRIME: {_fmt(result.prime_package.price_kzt)}")
    if foot:
        d.text((M, y), "   ·   ".join(foot), font=f_sub, fill=EMERALD)
        y += 56
    d.text((M, y), "Не диагноз. Сроки — приказ ДСМ-174/2020, подтверждает врач.",
           font=f_foot, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
