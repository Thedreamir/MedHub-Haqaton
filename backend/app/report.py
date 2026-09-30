"""Персональный PDF-отчёт: анкета + конкретный пакет + обоснование каждого пункта.

Pure renderer over the engine's already-validated CheckupPackageResponse.
Emergency invariant is inherited: an emergency response carries no commercial
content, so the report for it contains only the 103 guidance + disclaimers.
"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .schemas import CheckupPackageResponse, UserIntakeData

pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

EMERALD = colors.HexColor("#0e7a5f")
GOLD = colors.HexColor("#b8860b")
RED = colors.HexColor("#b91c1c")
GREY = colors.HexColor("#555555")

H1 = ParagraphStyle("h1", fontName="DVB", fontSize=17, leading=21, textColor=EMERALD)
H2 = ParagraphStyle("h2", fontName="DVB", fontSize=12.5, leading=16, textColor=EMERALD,
                    spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("body", fontName="DV", fontSize=9.5, leading=13)
SMALL = ParagraphStyle("small", fontName="DV", fontSize=8.5, leading=12, textColor=GREY)
BOLD = ParagraphStyle("bold", fontName="DVB", fontSize=10, leading=13.5)
WHY = ParagraphStyle("why", fontName="DV", fontSize=8.5, leading=11.5, textColor=GREY,
                     leftIndent=12, spaceAfter=3)
REDH = ParagraphStyle("redh", fontName="DVB", fontSize=13, leading=17, textColor=RED,
                      spaceBefore=8, spaceAfter=6)

_HOLLOW_WHY = {"входит в пакет PRIME", "входит в детский пакет"}

_SEX = {"male": "мужской", "female": "женский"}
_SYM = {"cardio": "сердце/давление", "fatigue": "усталость", "weight": "вес",
        "gi": "живот/пищеварение", "sleep": "сон/стресс", "other": "другое"}
_FAM = {"diabetes": "диабет у родных", "early_cvd": "ранний инфаркт/инсульт у родных 1-й линии",
        "cancer": "онкология у родных", "other": "другое"}
_CHR = {"hypertension": "гипертония", "diabetes": "диабет", "other": "другое"}


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₸"


def _rationale(intake: UserIntakeData, result: CheckupPackageResponse) -> str:
    """Почему выбран именно этот пакет — из той же логики, что и движок."""
    if intake.is_pregnant:
        return ("Вы отметили беременность: движок исключил все исследования с облучением "
                "(КТ, рентген, маммография) и подобрал программу наблюдения беременных "
                "«Комфорт» — безопасный маршрут без лучевой нагрузки.")
    if intake.child_age_months is not None or (intake.age is not None and intake.age < 18):
        m = intake.child_age_months
        if m is not None and m <= 12:
            return ("Возраст ребёнка до года: программа первого года жизни «Счастливый малыш» "
                    "по календарю наблюдений младенцев.")
        return ("Возраст ребёнка 1–17 лет: профилактический «Детский Базовый» — осмотры "
                "профильных специалистов и базовая лаборатория по возрасту. Доступно усиление "
                "до расширенной программы (8 специалистов, 46 анализов).")
    if intake.age is None or intake.gender is None:
        return ("В анкете пока нет возраста и пола: собран предварительный «Базовый» — "
                "стартовый скелет обследования из официального каталога PRIME. Добавьте "
                "возраст и пол — пакет пересчитается персонально.")
    band = "до 40 лет" if intake.age <= 39 else "40+"
    sex = _SEX.get(intake.gender.value, "")
    why = [f"Возраст {intake.age} и пол ({sex}) определяют возрастную программу «{band}»: "
           f"состав и онкомаркеры в ней привязаны к рискам именно этой группы."]
    cardio = ("cardio" in [s.value for s in intake.symptoms]
              or "early_cvd" in [f.value for f in intake.family_history]
              or "hypertension" in [c.value for c in intake.chronic_conditions])
    if cardio:
        why.append("Кардио-направление (симптомы/наследственность/гипертония): "
                   "рекомендовано усиление пакетом «Сердце».")
    if intake.smoking:
        why.append("Курение: добавлен скрининг лёгких (низкодозная КТ) по группе риска.")
    return " ".join(why)


def _items(flow, title, items, title_style=H2):
    if not items:
        return
    flow.append(Paragraph(title, title_style))
    for t in items:
        flow.append(Paragraph(f"• {t.name}", BODY))
        if t.why not in _HOLLOW_WHY:
            flow.append(Paragraph(f"Зачем: {t.why}", WHY))


def build_report_pdf(intake: UserIntakeData, result: CheckupPackageResponse) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Персональный чекап-план")
    f = [Paragraph("Персональный чекап-план", H1),
         Paragraph(f"PRIME Grand Clinic · конструктор чекапов (демо MVP) · "
                   f"{date.today().strftime('%d.%m.%Y')}", SMALL),
         Spacer(1, 6)]

    # 1. Анкета
    f.append(Paragraph("1. Ваши данные", H2))
    rows = []
    if intake.age is not None:
        rows.append(f"Возраст: {intake.age}")
    if intake.gender is not None:
        rows.append(f"Пол: {_SEX.get(intake.gender.value, intake.gender.value)}")
    if intake.child_age_months is not None:
        rows.append(f"Возраст ребёнка: {intake.child_age_months} мес.")
    if intake.is_pregnant:
        rows.append("Беременность: да")
    if intake.smoking is not None:
        rows.append(f"Курение: {'да' if intake.smoking else 'нет'}")
    if intake.symptoms:
        rows.append("Жалобы: " + ", ".join(_SYM.get(s.value, s.value) for s in intake.symptoms))
    if intake.family_history:
        rows.append("Семейный анамнез: " + ", ".join(_FAM.get(x.value, x.value) for x in intake.family_history))
    if intake.chronic_conditions:
        rows.append("Хронические: " + ", ".join(_CHR.get(x.value, x.value) for x in intake.chronic_conditions))
    if intake.red_flags:
        rows.append("Тревожные признаки: " + ", ".join(x.value for x in intake.red_flags))
    f.append(Paragraph("<br/>".join(rows) if rows else "Анкета не заполнена.", BODY))

    # Emergency: только маршрут 103, ноль коммерции (инвариант движка).
    if result.is_emergency:
        f.append(Paragraph("ВАЖНО", REDH))
        f.append(Paragraph(result.emergency_banner or "Обратитесь за неотложной помощью: 103.", BODY))
        f.append(Paragraph(result.not_diagnosis, SMALL))
        doc.build(f)
        return buf.getvalue()

    # 2. Пакет
    pkg = result.prime_package
    if pkg:
        price = _fmt(pkg.price_kzt) if pkg.price_kzt is not None else "цена уточняется клиникой"
        f.append(Paragraph(f"2. Ваш пакет: {pkg.name} — {price}", H2))
        f.append(Paragraph(f"<b>Почему именно он:</b> {_rationale(intake, result)}", BODY))
        if pkg.composition_note:
            f.append(Paragraph(pkg.composition_note, SMALL))
        if pkg.discrepancy_note:
            f.append(Paragraph(pkg.discrepancy_note, SMALL))
        f.append(Spacer(1, 3))
        f.append(Paragraph("Что входит (каждый пункт — из официального состава программы, каталог PRIME «Чекап пакеты 2026»):", BOLD))
        for t in pkg.tests:
            f.append(Paragraph(f"• {t.name}", BODY))
            if t.why not in _HOLLOW_WHY:
                f.append(Paragraph(f"Зачем: {t.why}", WHY))

    _items(f, "3. Бесплатно по ОСМС/ГОБМП (0 ₸) — положено по приказу", result.osms_free_tests)
    _items(f, "4. Дополнительно по показаниям", result.prime_addon_tests)
    if result.total_paid_kzt:
        f.append(Paragraph(f"Итого платная часть: {_fmt(result.total_paid_kzt)}", BOLD))

    if result.health_map:
        f.append(Paragraph("5. Карта здоровья", H2))
        for h in result.health_map:
            mark = {"done": "✔", "due": "•", "next_step": "→"}.get(h.status, "•")
            f.append(Paragraph(f"{mark} {h.item} — {h.when}", BODY))
            f.append(Paragraph(h.why, WHY))

    if result.itinerary_timeline:
        f.append(Paragraph("6. Маршрут", H2))
        for s in result.itinerary_timeline:
            tw = f" ({s.time_window})" if s.time_window else ""
            f.append(Paragraph(f"<b>{s.block}{tw}:</b> {s.title} — {s.details}", BODY))

    f.append(Spacer(1, 10))
    f.append(Paragraph(
        "Составы пакетов — по официальному каталогу PRIME «Чекап пакеты 2026»; "
        "где источник молчит, стоит честная пометка «подтверждает клиника». "
        f"Запись: {result.booking_contact_phone}, {result.booking_contact_email}.", SMALL))
    f.append(Paragraph(result.not_diagnosis + " " + result.disclaimer, SMALL))
    doc.build(f)
    return buf.getvalue()
