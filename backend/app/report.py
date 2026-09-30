"""Персональный PDF-отчёт в фирменном бланке PRIME Grand Clinic.

Премиальный минимализм: логотип клиники в шапке, лёгкая зелёная рамка бланка,
единая типографика Onest, карточка пакета, статусная карта здоровья.
Pure renderer над уже валидированным CheckupPackageResponse движка.
Инвариант безопасности наследуется: при красном флаге в отчёте только
маршрут 103 и дисклеймеры — ноль коммерческого контента.
"""
import io
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .schemas import CheckupPackageResponse, UserIntakeData

_RES = os.path.join(os.path.dirname(__file__), "fonts")
pdfmetrics.registerFont(TTFont("Onest", os.path.join(_RES, "Onest-Regular.ttf")))
pdfmetrics.registerFont(TTFont("OnestM", os.path.join(_RES, "Onest-Medium.ttf")))
pdfmetrics.registerFont(TTFont("OnestSB", os.path.join(_RES, "Onest-SemiBold.ttf")))
pdfmetrics.registerFont(TTFont("OnestB", os.path.join(_RES, "Onest-Bold.ttf")))
pdfmetrics.registerFont(TTFont("OnestX", os.path.join(_RES, "Onest-ExtraBold.ttf")))
pdfmetrics.registerFontFamily("Onest", normal="Onest", bold="OnestB",
                              italic="Onest", boldItalic="OnestB")

_LOGO = os.path.join(_RES, "logo-prime.png")

# Фирменная палитра (зелёный — из логотипа PRIME).
GREEN = colors.HexColor("#115f4d")
GREEN_DARK = colors.HexColor("#0c4536")
GREEN_LINE = colors.HexColor("#c9e2d9")
GREEN_BG = colors.HexColor("#eff6f2")
INK = colors.HexColor("#1d2b26")
GREY = colors.HexColor("#5c6f67")
GOLD = colors.HexColor("#a97b0f")
RED = colors.HexColor("#b91c1c")
RED_BG = colors.HexColor("#fdeeee")

W, H = A4
FRAME_INSET = 7 * mm
_CONTENT_W = W - 2 * 18 * mm  # поля 18 мм с каждой стороны

TITLE = ParagraphStyle("title", fontName="OnestX", fontSize=19, leading=23,
                       textColor=GREEN_DARK)
SUB = ParagraphStyle("sub", fontName="Onest", fontSize=8.5, leading=12,
                     textColor=GREY)
H2 = ParagraphStyle("h2", fontName="OnestB", fontSize=12.5, leading=16,
                    textColor=GREEN_DARK, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("body", fontName="Onest", fontSize=9.5, leading=13.5,
                      textColor=INK)
BOLD = ParagraphStyle("bold", fontName="OnestSB", fontSize=9.5, leading=13.5,
                      textColor=INK)
SMALL = ParagraphStyle("small", fontName="Onest", fontSize=8, leading=11.5,
                       textColor=GREY)
WHY = ParagraphStyle("why", fontName="Onest", fontSize=8, leading=11.5,
                     textColor=GREY, leftIndent=14, spaceAfter=3)
LABEL = ParagraphStyle("label", fontName="Onest", fontSize=8, leading=11,
                       textColor=GREY)
VALUE = ParagraphStyle("value", fontName="OnestM", fontSize=9.5, leading=13,
                       textColor=INK)
PKG_NAME = ParagraphStyle("pkgname", fontName="OnestB", fontSize=15, leading=19,
                          textColor=GREEN_DARK)
PKG_PRICE = ParagraphStyle("pkgprice", fontName="OnestX", fontSize=15, leading=19,
                           textColor=GREEN, alignment=2)
KICKER = ParagraphStyle("kicker", fontName="OnestSB", fontSize=7.5, leading=10,
                        textColor=GREEN)
TOTAL = ParagraphStyle("total", fontName="OnestB", fontSize=11.5, leading=15,
                       textColor=GREEN_DARK, alignment=2)
REDH = ParagraphStyle("redh", fontName="OnestX", fontSize=15, leading=19,
                      textColor=RED)

_HOLLOW_WHY = {"входит в пакет PRIME", "входит в детский пакет"}

_SEX = {"male": "мужской", "female": "женский"}
_SYM = {"cardio": "сердце/давление", "fatigue": "усталость", "weight": "вес",
        "gi": "живот/пищеварение", "sleep": "сон/стресс", "other": "другое"}
_FAM = {"diabetes": "диабет у родных", "early_cvd": "ранний инфаркт/инсульт у родных 1-й линии",
        "cancer": "онкология у родных", "other": "другое"}
_CHR = {"hypertension": "гипертония", "diabetes": "диабет", "other": "другое"}
_RF = {"chest_pain": "боль за грудиной", "neuro_deficit": "неврологические симптомы",
       "severe_dyspnea": "одышка в покое", "bleeding": "кровотечение/кровь",
       "syncope": "обморок", "high_fever": "высокая температура",
       "pregnancy_acute": "острые симптомы при беременности",
       "suicidal_ideation": "суицидальные мысли"}


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


def _frame_and_footer(canv, doc):
    """Лёгкая зелёная рамка бланка + футер на каждой странице."""
    canv.saveState()
    canv.setStrokeColor(colors.Color(GREEN.red, GREEN.green, GREEN.blue, alpha=0.35))
    canv.setLineWidth(1)
    canv.roundRect(FRAME_INSET, FRAME_INSET, W - 2 * FRAME_INSET, H - 2 * FRAME_INSET,
                   4 * mm, stroke=1, fill=0)
    canv.setFont("Onest", 7)
    canv.setFillColor(GREY)
    canv.drawString(18 * mm, 10.5 * mm,
                    "PRIME Grand Clinic · персональный чекап-план · демо MVP")
    canv.drawRightString(W - 18 * mm, 10.5 * mm, f"Стр. {doc.page}")
    canv.restoreState()


def _header(f):
    logo = Image(_LOGO, width=50 * mm, height=50 * mm * 1218 / 3284)
    right = [Paragraph("Персональный чекап-план", TITLE),
             Spacer(1, 1.5 * mm),
             Paragraph(f"PRIME Grand Clinic · конструктор чекапов · "
                       f"{date.today().strftime('%d.%m.%Y')}", SUB)]
    t = Table([[logo, right]], colWidths=[58 * mm, _CONTENT_W - 58 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    f.append(t)
    f.append(Spacer(1, 3 * mm))
    f.append(HRFlowable(width="100%", thickness=1.4, color=GREEN, spaceAfter=2))


def _intake_rows(intake: UserIntakeData):
    rows = []
    if intake.age is not None:
        rows.append(("Возраст", str(intake.age)))
    if intake.gender is not None:
        rows.append(("Пол", _SEX.get(intake.gender.value, intake.gender.value)))
    if intake.child_age_months is not None:
        rows.append(("Возраст ребёнка", f"{intake.child_age_months} мес."))
    if intake.is_pregnant:
        rows.append(("Беременность", "да"))
    if intake.smoking is not None:
        rows.append(("Курение", "да" if intake.smoking else "нет"))
    if intake.symptoms:
        rows.append(("Жалобы", ", ".join(_SYM.get(s.value, s.value) for s in intake.symptoms)))
    if intake.family_history:
        rows.append(("Семейный анамнез",
                     ", ".join(_FAM.get(x.value, x.value) for x in intake.family_history)))
    if intake.chronic_conditions:
        rows.append(("Хронические",
                     ", ".join(_CHR.get(x.value, x.value) for x in intake.chronic_conditions)))
    if intake.red_flags:
        rows.append(("Тревожные признаки", ", ".join(_RF.get(x.value, x.value) for x in intake.red_flags)))
    return rows


def _intake_grid(f, intake: UserIntakeData):
    f.append(Paragraph("Ваши данные", H2))
    rows = _intake_rows(intake)
    if not rows:
        f.append(Paragraph("Анкета не заполнена.", BODY))
        return
    data = []
    for i in range(0, len(rows), 2):
        pair = rows[i:i + 2]
        line = [Paragraph(pair[0][0], LABEL), Paragraph(pair[0][1], VALUE)]
        if len(pair) == 2:
            line += [Paragraph(pair[1][0], LABEL), Paragraph(pair[1][1], VALUE)]
        else:
            line += ["", ""]
        data.append(line)
    t = Table(data, colWidths=[29 * mm, 60 * mm, 34 * mm, _CONTENT_W - 123 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GREEN_LINE),
    ]))
    f.append(t)


def _item(f, name, why):
    f.append(Paragraph(f'<font color="#115f4d" size="11">•</font>&nbsp;&nbsp;{name}', BOLD))
    if why and why not in _HOLLOW_WHY:
        f.append(Paragraph(f"Зачем: {why}", WHY))


def _items(f, title, items):
    if not items:
        return
    f.append(Paragraph(title, H2))
    for t in items:
        _item(f, t.name, t.why)


def _package_card(f, intake, result):
    pkg = result.prime_package
    price = _fmt(pkg.price_kzt) if pkg.price_kzt is not None else "цена уточняется клиникой"
    head = Table([[Paragraph("ВАШ ПАКЕТ", KICKER), ""],
                  [Paragraph(pkg.name, PKG_NAME), Paragraph(price, PKG_PRICE)]],
                 colWidths=[_CONTENT_W - 20 * mm - 45 * mm, 45 * mm])
    head.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("SPAN", (0, 0), (1, 0)),
        ("VALIGN", (0, 1), (-1, 1), "BOTTOM"),
    ]))
    inner = [head, Spacer(1, 2 * mm),
             Paragraph(f"<b>Почему именно он:</b> {_rationale(intake, result)}", BODY)]
    if pkg.composition_note:
        inner.append(Paragraph(pkg.composition_note, SMALL))
    if pkg.discrepancy_note:
        inner.append(Paragraph(pkg.discrepancy_note, SMALL))
    card = Table([[inner]], colWidths=[_CONTENT_W])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_BG),
        ("BOX", (0, 0), (-1, -1), 0.9, GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    f.append(Spacer(1, 2 * mm))
    f.append(card)


def _health_map(f, result):
    f.append(Paragraph("Карта здоровья", H2))
    chip = {"done": ('<font color="#115f4d">✓</font>', "пройдено"),
            "due": ('<font color="#a97b0f" size="12">•</font>', "пора"),
            "next_step": ('<font color="#5c6f67">→</font>', "следующий шаг")}
    data = []
    for h in result.health_map:
        mark, word = chip.get(h.status, ("•", h.status))
        data.append([Paragraph(mark, BOLD),
                     Paragraph(h.item, BOLD),
                     Paragraph(f"{h.when} · {word}", SMALL),
                     Paragraph(h.why, SMALL)])
    t = Table(data, colWidths=[8 * mm, 52 * mm, 42 * mm, _CONTENT_W - 102 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GREEN_LINE),
    ]))
    f.append(t)


def _itinerary(f, result):
    block = [Paragraph("Маршрут визита", H2)]
    for s in result.itinerary_timeline:
        tw = f" · {s.time_window}" if s.time_window else ""
        block.append(Paragraph(f'<font color="#115f4d"><b>{s.block}{tw}</b></font>'
                               f"&nbsp;&nbsp;{s.title} — {s.details}", BODY))
        block.append(Spacer(1, 1 * mm))
    f.append(KeepTogether(block))


def build_report_pdf(intake: UserIntakeData, result: CheckupPackageResponse) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=17 * mm,
                            title="Персональный чекап-план · PRIME Grand Clinic",
                            author="PRIME Grand Clinic")
    f = []
    _header(f)
    _intake_grid(f, intake)

    # Красный флаг: только маршрут 103, ноль коммерции (инвариант движка).
    if result.is_emergency:
        warn = Table([[[Paragraph("ВАЖНО", REDH), Spacer(1, 1.5 * mm),
                        Paragraph(result.emergency_banner
                                  or "Обратитесь за неотложной помощью: 103.", BODY)]]],
                     colWidths=[_CONTENT_W])
        warn.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), RED_BG),
            ("BOX", (0, 0), (-1, -1), 0.9, RED),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        f.append(Spacer(1, 4 * mm))
        f.append(warn)
        f.append(Spacer(1, 4 * mm))
        f.append(Paragraph(result.not_diagnosis, SMALL))
        doc.build(f, onFirstPage=_frame_and_footer, onLaterPages=_frame_and_footer)
        return buf.getvalue()

    pkg = result.prime_package
    if pkg:
        _package_card(f, intake, result)
        f.append(Paragraph("Что входит в пакет", H2))
        f.append(Paragraph("Каждый пункт — из официального состава программы, "
                           "каталог PRIME «Чекап пакеты 2026»:", SMALL))
        f.append(Spacer(1, 1 * mm))
        for t in pkg.tests:
            _item(f, t.name, t.why)

    _items(f, "Бесплатно по ОСМС/ГОБМП (0 ₸) — положено по приказу", result.osms_free_tests)
    _items(f, "Дополнительно по показаниям", result.prime_addon_tests)
    if result.total_paid_kzt:
        f.append(Spacer(1, 2 * mm))
        f.append(HRFlowable(width="100%", thickness=0.7, color=GREEN_LINE, spaceAfter=3))
        f.append(Paragraph(f"Итого платная часть: {_fmt(result.total_paid_kzt)}", TOTAL))

    if result.health_map:
        _health_map(f, result)
    if result.itinerary_timeline:
        _itinerary(f, result)

    f.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.7, color=GREEN_LINE, spaceBefore=6, spaceAfter=3),
        Paragraph(
            "Составы пакетов — по официальному каталогу PRIME «Чекап пакеты 2026»; "
            "где источник молчит, стоит честная пометка «подтверждает клиника». "
            f"Запись: {result.booking_contact_phone}, {result.booking_contact_email}.", SMALL),
        Paragraph(result.not_diagnosis + " " + result.disclaimer, SMALL)]))
    doc.build(f, onFirstPage=_frame_and_footer, onLaterPages=_frame_and_footer)
    return buf.getvalue()
