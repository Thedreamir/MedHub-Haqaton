"""Telegram-бот: живой ассистент поверх анкеты пользователя.

Deep-link t.me/<bot>?start=<session_id> привязывает чат к сессии анкеты;
бот отвечает по СВОЕМУ пакету/маршруту/карте здоровья, шлёт напоминания
о повторных скринингах и ведёт «Зелёный навигатор»: жалоба -> срочность ->
ОСМС vs PRIME -> готовый текст заявки в клинику.
Красный флаг в любом сообщении -> мгновенный маршрут 103 (тот же keyword-floor,
что и в веб-чате). Токен живёт только в env TELEGRAM_BOT_TOKEN, никогда не в репо.
"""
import asyncio
import os
import re
import time
from datetime import date, timedelta
from urllib.parse import quote

import httpx

from .engine import build_response
from .llm import keyword_extract
from .schemas import CheckupPackageResponse, UserIntakeData
from .store import PersistedDict

_API = "https://api.telegram.org/bot"

# chat_id -> session_id: SQLite на диске — переживает рестарт процесса
CHATS: PersistedDict = PersistedDict("chats")

# Семейный режим: chat_id -> список session_id всех планов, привязанных к чату
# (я, супруг(а), родители). Активный план лежит в CHATS — все команды идут по нему.
FAMILY: PersistedDict = PersistedDict("family")


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def bot_username() -> str:
    return os.environ.get("TELEGRAM_BOT_USERNAME", "")


async def _send(chat_id: int, text: str, markup: dict | None = None) -> None:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not tok:
        return
    payload = {"chat_id": chat_id, "text": text}
    if markup:
        payload["reply_markup"] = markup
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{_API}{tok}/sendMessage", json=payload)


async def _answer_cb(cb_id: str) -> None:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not tok:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{_API}{tok}/answerCallbackQuery", json={"callback_query_id": cb_id})


# Кнопки-функции: агент под рукой, без командной строки.
MENU = {"inline_keyboard": [
    [{"text": "📋 Мой план", "callback_data": "cmd:plan"},
     {"text": "✅ Чек-лист", "callback_data": "cmd:prep"}],
    [{"text": "🩺 Граф здоровья", "callback_data": "cmd:graph"},
     {"text": "⏰ Скрининги", "callback_data": "cmd:recall"}],
    [{"text": "👨‍👩‍👧 Семья", "callback_data": "cmd:family"},
     {"text": "🗓 Записаться", "callback_data": "cmd:book"}],
    [{"text": "📝 Пройти анкету", "url": "https://checkup-intelligence.vercel.app"}],
]}


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₸"


def _plan_lines(intake: UserIntakeData, result: CheckupPackageResponse) -> list[str]:
    lines = []
    if result.is_emergency:
        return ["Обнаружены тревожные признаки — чекап не подбирается. "
                "Единый номер экстренных служб: 103."]
    pkg = result.prime_package
    if pkg:
        price = _fmt(pkg.price_kzt) if pkg.price_kzt is not None else "цена уточняется клиникой"
        lines.append(f"Ваш пакет: {pkg.name} — {price}.")
    if result.osms_free_tests:
        lines.append(f"Бесплатно по ОСМС: {len(result.osms_free_tests)} позиций (0 ₸).")
    if result.total_paid_kzt:
        lines.append(f"Итого платная часть: {_fmt(result.total_paid_kzt)}.")
    return lines


def _summary(intake: UserIntakeData, result: CheckupPackageResponse) -> str:
    return "\n".join(_plan_lines(intake, result))


def _answer(text: str, intake: UserIntakeData, result: CheckupPackageResponse) -> str:
    t = text.lower()
    if result.is_emergency:
        return ("По вашей анкете зафиксированы тревожные признаки: подбор чекапа "
                "заблокирован. Обратитесь за неотложной помощью: 103.")
    pkg = result.prime_package
    if "запис" in t:
        return booking_request(intake, result, text)
    if any(w in t for w in ("цен", "стоит", "сколько", "стоимост")):
        lines = _plan_lines(intake, result)
        lines.append("Финальную стоимость и состав подтверждает клиника PRIME при записи: "
                     "+7 747 094 26 21.")
        return "\n".join(lines)
    if any(w in t for w in ("входит", "состав", "что сда", "какие анализ", "что буду")):
        if pkg and pkg.tests:
            names = "\n".join(f"• {x.name}" for x in pkg.tests[:12])
            return (f"В пакет «{pkg.name}» входит:\n{names}"
                    "\n\nЭто не диагноз — состав подтверждает врач.")
        return "Точный состав программы подтверждает клиника при записи: +7 747 094 26 21."
    if any(w in t for w in ("маршрут", "как прой", "когда при", "как пройд", "расписан")):
        steps = "\n".join(f"• {s.block}: {s.details}" for s in result.itinerary_timeline)
        return ("Маршрут:\n" + steps) if steps else "Маршрут пока не собран — заполните анкету на сайте."
    if any(w in t for w in ("повтор", "когда снова", "следующ", "напомни")):
        due = [h for h in result.health_map if h.status in ("due", "next_step")]
        if due:
            items = "\n".join(f"• {h.item} — {h.when}" for h in due)
            return "Повторные скрининги по приказу ДСМ-174/2020:\n" + items
        return "Активных повторных скринингов сейчас нет — вы в плане."
    if any(w in t for w in ("подготов", "натощак", "можно ли есть", "диета",
                            "чек-лист", "чеклист")):
        return _prep_checklist_text(result)
    # Свободный текст без явной темы — это жалоба/контекст: Зелёный навигатор.
    return green_navigator(text, result)



# ---------- Зелёный навигатор: жалоба -> срочность -> ОСМС vs PRIME -> заявка ----------

_URGENT_WORDS = (
    "высокая температур", "температура 39", "температура 40", "сильная боль",
    "острая боль", "не проходит", "кровь в", "кровотеч", "рвота кров",
    "потерял сознание", "обморок", "удушье", "не могу дышать",
)

# жалоба -> (ключевые слова, позиция бесплатного скрининга ОСМС по ДСМ-174/2020)
_SCENARIOS = [
    # (ключевые слова, маршрут ОСМС или None, услуга PRIME для заявки)
    (("сердц", "давлен", "гипертон", "пульс"),
     "скрининг сердечно-сосудистых заболеваний (АД, ЭКГ, липидный профиль)", None),
    (("холестерин",),
     "скрининг сердечно-сосудистых заболеваний (липидный профиль)", None),
    (("сахар", "диабет", "жажда", "глюкоз"),
     "скрининг сахарного диабета (глюкоза / HbA1c)", None),
    (("груд", "молочн", "уплотнен"),
     "скрининг рака молочной железы (маммография, женщины 40–70)", None),
    (("шейк", "цервик", "пап-тест", "мазок"),
     "скрининг рака шейки матки (цитология, женщины 30–70)", None),
    (("впч", "папиллом"),
     None, "ВПЧ-тест и консультацию гинеколога"),
    (("кишеч", "стул", "колоноскоп", "запор", "геморро"),
     "скрининг колоректального рака (анализ кала на скрытую кровь, 50–70)", None),
    (("желудок", "гастрит", "изжог", "хеликобактер"),
     None, "гастроскопию и тест на хеликобактер"),
    (("печен", "гепатит"),
     "скрининг вирусных гепатитов B и C", None),
    (("лёгк", "легк", "кашель кур", "одышк"),
     "скрининг рака лёгкого (низкодозная КТ, курящие 50–70)", None),
    (("флюорограф", "туберкул"),
     "флюорографию (скрининг туберкулёза по ОСМС)", None),
    (("вич", "hiv", "спид"),
     "анализ на ВИЧ (бесплатно по ОСМС)", None),
    (("зрени", "глаз", "глауком"),
     "измерение внутриглазного давления (скрининг глаукомы)", None),
    (("щитовид", "гормон", "ттг"),
     None, "УЗИ щитовидной железы и панель гормонов"),
    (("спин", "поясниц", "шея бол", "грыж"),
     None, "консультацию невролога и МРТ"),
    (("сустав", "колен", "артроз"),
     None, "консультацию травматолога-ортопеда и рентген"),
    (("аллерг",),
     None, "аллергопанель и консультацию терапевта"),
    (("кож", "родинк", "пятно на коже"),
     None, "дерматоскопию родинок у дерматолога"),
    (("почк", "моча", "цистит"),
     "общий анализ мочи (входит в скрининг по ОСМС)", None),
    (("анеми", "слабост", "усталост", "гемоглобин"),
     "общий анализ крови (входит в скрининг по ОСМС)", None),
    (("витамин",),
     None, "анализ на витамин D и микроэлементы"),
    (("варикоз", "вены на ногах", "отёки ног", "отеки ног"),
     None, "УЗДГ вен нижних конечностей"),
    (("сон", "бессонниц", "апноэ", "храп"),
     None, "консультацию сомнолога"),
    (("стресс", "депресс", "тревожн", "выгор"),
     None, "консультацию психолога"),
    (("зуб", "стоматолог"),
     None, "осмотр стоматолога"),
    (("простат", "пса", "psa"),
     None, "анализ PSA и консультацию уролога (мужчины 45+)"),
    (("беремен", "планируем реб"),
     "ведение беременности и скрининги (по ОСМС)", None),
    (("ребёнок", "ребенок", "детск"),
     "профилактические осмотры ребёнка (по ОСМС)", None),
    (("слух", "лор", "нос", "горл"),
     None, "консультацию ЛОР-врача"),
    (("вес", "ожирен", "похуде"),
     "скрининг сахарного диабета и липидного профиля (по ОСМС)", "консультацию эндокринолога"),
]


def green_navigator(text: str, result: CheckupPackageResponse) -> str:
    """Свободная жалоба -> маршрут: срочность, ОСМС vs PRIME, готовый текст заявки."""
    urgent, osms_hit, prime_svc = _nav_facts(text)

    if urgent:
        urgency = ("Судя по описанию, откладывать не стоит: обратитесь к врачу "
                   "в ближайшие 1–2 дня, не дожидаясь планового чекапа.")
    else:
        urgency = ("Признаков неотложного состояния не вижу — это можно решать "
                   "в плановом порядке.")

    if osms_hit:
        route = (f"Маршрут ОСМС (0 ₸): {osms_hit} — делается бесплатно по приказу "
                 "ДСМ-174/2020. Направление даёт участковый врач в вашей поликлинике, "
                 "запись через eGov / damumed.kz.")
        service = osms_hit.split(" (")[0]
        if prime_svc:
            route += f"\nДополнительно в PRIME (платно): {prime_svc}."
    else:
        pkg = result.prime_package
        if pkg:
            price = _fmt(pkg.price_kzt) if pkg.price_kzt is not None else "цена уточняется"
            route = (f"Маршрут PRIME (платно): под бесплатный скрининг ОСМС это не "
                     f"попадает. В клинике PRIME можно пройти ваш пакет «{pkg.name}» "
                     f"({price}) или точечную консультацию врача.")
        else:
            route = ("Маршрут PRIME (платно): под бесплатный скрининг ОСМС это не "
                     "попадает. В клинике PRIME доступна консультация врача и "
                     "диагностика по прайсу.")
        service = prime_svc or ("консультацию врача" + (
            f" / пакет «{result.prime_package.name}»" if result.prime_package else ""))

    request_text = (
        "Готовый текст заявки (отправьте на salem@primegc.kz или продиктуйте "
        "по +7 747 094 26 21):\n"
        f"«Здравствуйте! Хочу записаться: {service}. "
        f"Повод: {text.strip()[:200]}. Подскажите ближайшее время приёма.»")
    return (f"Зелёный навигатор:\n\n{urgency}\n\n{route}\n\n{request_text}"
            "\n\nЭто не диагноз — маршрут и состав подтверждает врач.")


# ---------- Напоминания из карты здоровья ----------

_REMIND_INTERVAL_SEC = 6 * 3600          # как часто пересматривать карту
_REMIND_RESEND_SEC = 7 * 24 * 3600        # повторный пуш не чаще раза в 7 дней
_LAST_REMIND: PersistedDict = PersistedDict("reminds")  # chat_id -> ts последнего напоминания


def due_screenings(result: CheckupPackageResponse) -> list[str]:
    return [f"• {h.item} — {h.when}" for h in result.health_map
            if h.status in ("due", "next_step")]


async def remind_once(chat_id: int, intake: UserIntakeData) -> bool:
    """Пуш «срок подошёл» + подготовка к визиту + действие «Записаться».

    True = отправлено. Без реальных дат записи не выдумываем: напоминаем по факту
    наступивших сроков из карты здоровья, повтор не чаще раза в 7 дней.
    """
    result = build_response(intake)
    due = due_screenings(result)
    if not due:
        return False
    last = _LAST_REMIND.get(chat_id, 0)
    if time.time() - last < _REMIND_RESEND_SEC:
        return False
    _LAST_REMIND[chat_id] = time.time()
    prep = next((s_.details for s_ in result.itinerary_timeline
                 if "подготов" in s_.block.lower()), None)
    prep_line = ("\n\nЕсли записались на ближайший день — подготовка: " + prep) if prep else ""
    await _send(chat_id,
                "⏰ Срок подошёл: по карте здоровья (ДСМ-174/2020) вам положено:\n"
                + "\n".join(due) + prep_line +
                "\n\nСкрининги из списка — 0 ₸ по ОСМС (направление в поликлинике), "
                "остальное закроем в PRIME.\n"
                "Записаться: +7 747 094 26 21 · salem@primegc.kz — или ответьте "
                "«записаться», подготовлю текст заявки.\n"
                "Это не диагноз; сроки и состав подтверждает врач.", markup=MENU)
    return True


async def reminder_loop(sessions: dict) -> None:
    """Best-effort цикл напоминаний: живёт, пока жив процесс (бесплатный Render
    засыпает в простое — напоминания доезжают, пока сервис активен)."""
    while True:
        await asyncio.sleep(_REMIND_INTERVAL_SEC)
        for chat_id, sid in list(CHATS.items()):
            intake = sessions.get(sid)
            if intake is not None:
                try:
                    await remind_once(chat_id, intake)
                except Exception:
                    continue  # одна неудачная отправка не останавливает цикл


# ---------- Живой диалог: бесплатная Qwen через OpenRouter (fallback = детерминированный) ----------

# Цепочка бесплатных моделей; первая ответившая побеждает. Веб-чат на Nemotron не трогаем.
_TG_MODELS = [m.strip() for m in os.environ.get(
    "TG_LLM_MODELS",
    "qwen/qwen3.8-27b:free,qwen/qwen3-32b:free,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
).split(",") if m.strip()]

_SYSTEM = (
    "Ты Primey — живой, тёплый и немного дерзкий health-напарник пользователя в Telegram "
    "от клиники PRIME. Общайся как заботливый друг, который разбирается в чекапах: коротко "
    "(2–8 строк), по-русски, живыми фразами, с лёгкими уместными эмодзи. Иногда задавай один "
    "человеческий уточняющий вопрос («как самочувствие сегодня?») — но не в каждом ответе. "
    "ЖЁСТКИЕ РАМКИ: факты — ТОЛЬКО из карточки плана ниже: цены, состав, даты и телефоны не "
    "выдумывай и не округляй. Не ставь диагнозы, не обещай результат лечения, не пугай. Если "
    "вопрос про цену/состав/маршрут/подготовку/повторные скрининги — отвечай точно по "
    "карточке, игривость только в подаче. Если это жалоба — мягко дай маршрут из карточки "
    "(ОСМС или PRIME) и приложи готовый текст заявки. Экстренные состояния уже перехвачены "
    "до тебя: про 103 пиши, только если пользователь сам описывает угрозу жизни."
)


def _nav_facts(text: str):
    t = text.lower()
    urgent = any(w in t for w in _URGENT_WORDS)
    osms_hit, prime_svc = None, None
    for keys, osms_route, prime_service in _SCENARIOS:
        if any(k in t for k in keys):
            osms_hit, prime_svc = osms_route, prime_service
            break
    return urgent, osms_hit, prime_svc


def _context_card(intake: UserIntakeData, result: CheckupPackageResponse, text: str) -> str:
    lines = ["КАРТОЧКА ПЛАНА ПОЛЬЗОВАТЕЛЯ:"]
    lines.append(f"Возраст/пол: {intake.age}, {intake.gender.value if intake.gender else '—'}.")
    if result.is_emergency:
        lines.append("По анкете есть тревожные признаки: чекап не подбирается, маршрут — 103.")
        return "\n".join(lines)
    pkg = result.prime_package
    if pkg:
        price = _fmt(pkg.price_kzt) if pkg.price_kzt is not None else "уточняется"
        lines.append(f"Пакет PRIME: «{pkg.name}», {price}.")
        if pkg.tests:
            lines.append("Состав пакета: " + "; ".join(x.name for x in pkg.tests[:15]) + ".")
    if result.osms_free_tests:
        lines.append("Бесплатно по ОСМС (0 ₸): "
                     + "; ".join(t.name for t in result.osms_free_tests[:12]) + ".")
    if result.total_paid_kzt:
        lines.append(f"Итого платная часть: {_fmt(result.total_paid_kzt)}.")
    if result.itinerary_timeline:
        lines.append("Маршрут: " + " → ".join(s.block for s in result.itinerary_timeline) + ".")
    due = due_screenings(result)
    if due:
        lines.append("Повторные скрининги по срокам (ДСМ-174/2020): " + "; ".join(due) + ".")
    urgent, osms_hit, _svc = _nav_facts(text)
    if urgent:
        lines.append("Оценка жалобы: срочно — к врачу в ближайшие 1–2 дня, не ждать чекапа.")
    if osms_hit:
        lines.append(f"Маршрут по жалобе: {osms_hit} — бесплатно по ОСМС, направление "
                     "у участкового врача, запись eGov/damumed.kz.")
    elif not urgent:
        lines.append("Маршрут по жалобе: под скрининг ОСМС не попадает — PRIME, платно.")
    lines.append("Запись в PRIME: +7 747 094 26 21, salem@primegc.kz.")
    lines.append("Формат готовой заявки: «Здравствуйте! Хочу записаться: <услуга>. "
                 "Повод: <жалоба>. Подскажите ближайшее время приёма.»")
    return "\n".join(lines)


async def llm_reply(text: str, intake: UserIntakeData,
                    result: CheckupPackageResponse) -> str | None:
    """Живой ответ бесплатной Qwen поверх карточки плана. None -> детерминированный fallback."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    card = _context_card(intake, result, text)
    async with httpx.AsyncClient(timeout=30) as c:
        for model in _TG_MODELS:
            try:
                r = await c.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "max_tokens": 500, "temperature": 0.4,
                          "messages": [{"role": "system", "content": _SYSTEM + "\n\n" + card},
                                       {"role": "user", "content": text}]})
                if r.status_code != 200:
                    continue
                out = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
                if out and out.strip():
                    return out.strip()
            except Exception:
                continue
    return None


async def llm_selftest() -> dict:
    """Проверка цепочки бесплатных моделей с реальным ключом (для прод-диагностики)."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return {"ok": False, "reason": "no OPENROUTER_API_KEY", "models": _TG_MODELS}
    errors = {}
    async with httpx.AsyncClient(timeout=30) as c:
        for model in _TG_MODELS:
            t0 = time.time()
            try:
                r = await c.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "max_tokens": 8,
                          "messages": [{"role": "user", "content": "Ответь одним словом: ок"}]})
                if r.status_code == 200:
                    return {"ok": True, "model": model,
                            "latency_ms": int((time.time() - t0) * 1000)}
                errors[model] = f"http {r.status_code}: {r.text[:120]}"
            except Exception as e:
                errors[model] = type(e).__name__
    return {"ok": False, "reason": "all models failed", "models": _TG_MODELS,
            "errors": errors}


_STATUS_ICON = {"done": "✅", "due": "🔴", "next_step": "➡️"}
_STATUS_WORD = {"done": "пройдено", "due": "срок подошёл", "next_step": "следующий шаг"}


def render_plan(intake: UserIntakeData, result: CheckupPackageResponse) -> str:
    """/plan: весь план со статусами по строкам — иконка, позиция, когда, зачем."""
    head = "Ваш чекап-план"
    if intake.age:
        head += f" ({intake.age} лет"
        head += ", мужчина)" if intake.gender and intake.gender.value == "male" else (
            ", женщина)" if intake.gender and intake.gender.value == "female" else ")")
    lines = [head + ":"]
    if result.is_emergency:
        lines.append("По анкете есть тревожные признаки — плановый чекап не подбирается, "
                     "маршрут один: 103.")
        return "\n".join(lines)
    for h in result.health_map:
        icon = _STATUS_ICON.get(h.status, "➡️")
        word = _STATUS_WORD.get(h.status, h.status)
        lines.append(f"{icon} {h.item} — {h.when} ({word})")
        if h.why:
            lines.append(f"    {h.why}")
    pkg = result.prime_package
    if pkg and pkg.price_kzt is not None:
        lines.append(f"💳 Пакет «{pkg.name}»: {_fmt(pkg.price_kzt)}"
                     + (f", платная часть итого {_fmt(result.total_paid_kzt)}"
                        if result.total_paid_kzt else ""))
    if result.osms_free_tests:
        lines.append(f"🆓 По ОСМС бесплатно: {len(result.osms_free_tests)} позиций.")
    lines.append("Записаться: +7 747 094 26 21 · или напишите «записаться» — "
                 "подготовлю текст заявки.")
    lines.append("Это не диагноз — сроки и состав подтверждает врач.")
    return "\n".join(lines)


_TIME_WINDOWS = [
    (("рано утром", "пораньше"), "рано утром"),
    (("утром", "утро"), "утром"),
    (("днём", "днем", "обед"), "днём"),
    (("вечером", "вечер", "после работы"), "вечером"),
    (("выходн", "суббот", "воскресен"), "в выходные"),
    (("будн",), "в будний день"),
]


def _time_window(text: str) -> str | None:
    t = text.lower()
    for keys, label in _TIME_WINDOWS:
        if any(k in t for k in keys):
            return label
    return None


def booking_request(intake: UserIntakeData, result: CheckupPackageResponse,
                    text: str = "") -> str:
    """«Записаться»: готовый текст заявки; время только пожеланием — слоты не выдумываем."""
    pkg = result.prime_package
    what = (f"пакет «{pkg.name}»" + (f" ({_fmt(pkg.price_kzt)})" if pkg.price_kzt else "")
            ) if pkg else "консультацию врача"
    window = _time_window(text)
    when = f" Удобное время: {window}." if window else ""
    return ("Готовая заявка в клинику PRIME:\n"
            f"«Здравствуйте! Хочу записаться: {what}.{when} "
            "Подскажите ближайшее время приёма.»\n\n"
            "Отправьте на salem@primegc.kz или продиктуйте по +7 747 094 26 21 — "
            "точное время подтвердит контакт-центр клиники.")

_BIND_HINT = ("Сначала пройдите анкету на сайте конструктора и нажмите "
              "«Напоминания в Telegram» на странице результата — бот привяжется "
              "к вашему плану.")


def _family_list(chat_id: int) -> list:
    return list(FAMILY.get(chat_id, []))


def _describe_member(intake: UserIntakeData) -> str:
    """Короткая подпись члена семьи: «мужчина, 41 — пакет «Мужской 40+»»."""
    who = []
    if intake.gender:
        who.append("мужчина" if intake.gender.value == "male" else "женщина")
    if intake.age:
        who.append(str(intake.age))
    label = ", ".join(who) if who else "анкета"
    pkg = build_response(intake).prime_package
    if pkg:
        label += f" — пакет «{pkg.name}»"
    return label


def _family_view(chat_id: int, sessions: dict) -> str:
    sids = _family_list(chat_id)
    alive = []
    lines = []
    active = CHATS.get(chat_id)
    for sid in sids:
        intake = sessions.get(sid)
        if intake is None:
            continue  # сессию сбросили на сайте — вычёркиваем из семьи
        alive.append(sid)
        mark = " (активный)" if sid == active else ""
        lines.append(f"{len(alive)}. {_describe_member(intake)}{mark}")
    if alive != sids:
        FAMILY[chat_id] = alive
    if not lines:
        return _BIND_HINT
    return ("Планы вашей семьи в этом чате:\n" + "\n".join(lines) +
            "\n\nПереключиться: «план 1», «план 2»… — все команды (/plan, запись, "
            "подготовка) пойдут по активному плану.")


def health_graph(result: CheckupPackageResponse) -> str:
    """Красивый граф здоровья: статусы карты одним экраном. Данные — только
    из engine.health_map, ничего не выдумываем."""
    icon = {"due": "🔴", "next_step": "🟡", "done": "✅"}
    order = {"due": 0, "next_step": 1, "done": 2}
    rows = sorted(result.health_map, key=lambda h: order.get(h.status, 3))
    lines = [f"{icon.get(h.status, '⚪')} {h.item} — {h.when}" for h in rows]
    due = sum(1 for h in rows if h.status == "due")
    nxt = sum(1 for h in rows if h.status == "next_step")
    done = sum(1 for h in rows if h.status == "done")
    return ("🩺 Твой граф здоровья\n\n" + "\n".join(lines) +
            f"\n\n———\n✅ закрыто: {done} · 🟡 следующий шаг: {nxt} · 🔴 срок подошёл: {due}"
            "\nЭто не диагноз — сроки по ДСМ-174/2020, подтверждает врач.")


def _prep_checklist_text(result: CheckupPackageResponse) -> str:
    prep = [s for s in result.itinerary_timeline if "подготов" in s.block.lower()]
    if prep:
        items = []
        for s_ in prep:
            for part in s_.details.split("; "):
                part = part.strip().rstrip(".")
                if part and "подтверждает клиника" not in part:
                    items.append(part)
        if items:
            checklist = "\n".join(f"☐ {x}" for x in items)
            return ("Чек-лист подготовки к чекапу:\n" + checklist +
                    "\n\nВ день визита: паспорт, анализы натощак (вода можно), "
                    "начало в 8:00.\nЭто не диагноз — подготовку подтверждает клиника "
                    "при записи: +7 747 094 26 21.")
    return "Подготовку подтверждает клиника при записи: +7 747 094 26 21."


def _recall_text(result: CheckupPackageResponse) -> str:
    due = [h for h in result.health_map if h.status in ("due", "next_step")]
    if due:
        items = "\n".join(f"• {h.item} — {h.when}" for h in due)
        return "Повторные скрининги по приказу ДСМ-174/2020:\n" + items
    return "Активных повторных скринингов сейчас нет — вы в плане."


_WINDOW_HOURS = {"рано утром": ("08:00", "09:00"), "утром": ("08:00", "10:00"),
                 "днём": ("12:00", "14:00"), "вечером": ("16:00", "18:00"),
                 "в выходные": ("09:00", "12:00"), "в будний день": ("09:00", "12:00")}


def _gcal_markup(window: str | None) -> dict | None:
    """Кнопка «добавить в Google Календарь»: личное напоминание о визите на
    желаемое окно. Это НЕ бронь слота — время подтверждает клиника."""
    if not window or window not in _WINDOW_HOURS:
        return None
    day = date.today() + timedelta(days=1)
    if window == "в выходные":
        day += timedelta(days=(5 - day.weekday()) % 7)  # ближайшая суббота
    start, end = _WINDOW_HOURS[window]
    d = day.strftime("%Y%m%d")
    dates = f"{d}T{start.replace(':', '')}00/{d}T{end.replace(':', '')}00"
    details = ("Пожелание по времени: " + window + ". Слот подтверждает клиника PRIME: "
               "+7 747 094 26 21, salem@primegc.kz. Подготовка: анализы натощак, вода можно.")
    url = ("https://calendar.google.com/calendar/render?action=TEMPLATE"
           "&text=" + quote("Чекап PRIME (подготовка натощак)") +
           f"&dates={dates}&ctz=Asia/Almaty&details=" + quote(details))
    return {"inline_keyboard": [[{"text": "🗓 Добавить в Google Календарь", "url": url}]]}


async def _run_feature(chat_id: int, cmd: str, sessions: dict, text: str = "") -> None:
    """Единая точка для кнопок и текстовых команд."""
    if cmd == "family":
        await _send(chat_id, _family_view(chat_id, sessions), markup=MENU)
        return
    sid = CHATS.get(chat_id)
    intake = sessions.get(sid) if sid else None
    if intake is None:
        await _send(chat_id, _BIND_HINT)
        return
    result = build_response(intake)
    if cmd == "plan":
        await _send(chat_id, render_plan(intake, result), markup=MENU)
    elif cmd == "prep":
        await _send(chat_id, _prep_checklist_text(result), markup=MENU)
    elif cmd == "graph":
        await _send(chat_id, health_graph(result), markup=MENU)
    elif cmd == "recall":
        await _send(chat_id, _recall_text(result), markup=MENU)
    elif cmd == "book":
        await _send(chat_id, booking_request(intake, result, text),
                    markup=_gcal_markup(_time_window(text)) or MENU)


async def handle_update(update: dict, sessions: dict) -> None:
    cb = update.get("callback_query") or {}
    if cb:
        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
        data = cb.get("data") or ""
        if cb.get("id"):
            await _answer_cb(cb["id"])
        if chat_id is not None and data.startswith("cmd:"):
            await _run_feature(chat_id, data[4:], sessions)
        return

    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if chat_id is None or not text:
        return

    if text.strip().lower().startswith("/plan"):
        await _run_feature(chat_id, "plan", sessions)
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        sid = parts[1].strip() if len(parts) > 1 else ""
        intake = sessions.get(sid) if sid else None
        if intake is None:
            await _send(chat_id, "Здравствуйте! Это ассистент конструктора чекапов PRIME. "
                                 + _BIND_HINT)
            return
        CHATS[chat_id] = sid
        fam = _family_list(chat_id)
        if sid not in fam:
            fam.append(sid)
            FAMILY[chat_id] = fam
        family_hint = ("\nСемейный режим: в чате теперь "
                       f"{len(fam)} плана. /family — список, «план N» — переключиться.") if len(fam) > 1 else ""
        result = build_response(intake)
        due = due_screenings(result)
        extra = ("\n🔴 По срокам уже положено: " + "; ".join(due) + "\n") if due else ""
        who = []
        if intake.age:
            who.append(f"{intake.age} лет")
        if intake.gender:
            who.append("мужчина" if intake.gender.value == "male" else "женщина")
        pkg = result.prime_package
        knows = ", ".join(who)
        if pkg:
            knows += f", пакет «{pkg.name}»"
        if result.osms_free_tests:
            knows += f", {len(result.osms_free_tests)} позиций по ОСМС (0 ₸)"
        await _send(chat_id,
                    "Готово — привязал чат к вашему чекап-плану.\n" + extra +
                    "\nУмею: отвечать по вашему пакету и маршруту дня, напоминать "
                    "о повторных скринингах и подсказывать, что бесплатно по ОСМС, "
                    "а что закрыть в PRIME.\n"
                    f"Уже знаю о вас: {knows}.\n"
                    "Действия: /plan — весь план со статусами · «записаться» — готовая "
                    "заявка в клинику · или просто опишите жалобу — подскажу маршрут. "
                    "А ещё у меня есть кнопки 👇"
                    + family_hint, markup=MENU)
        return

    # Красный флаг не ждёт привязки: тот же keyword-floor, что и на сайте.
    if keyword_extract(text).red_flags:
        await _send(chat_id,
                    "По описанному похоже на состояние, которое нельзя откладывать на "
                    "плановый чекап. Пожалуйста, обратитесь за медицинской помощью "
                    "сейчас — единый номер 103.")
        return

    low = text.lower()
    if low.startswith("/family") or low.strip() == "семья":
        await _run_feature(chat_id, "family", sessions)
        return
    if any(w in low for w in ("граф здоровья", "карта здоровья", "график здоровья")):
        await _run_feature(chat_id, "graph", sessions)
        return
    if "запис" in low:
        # Заявка детерминированная (слоты не выдумываем) + кнопка Google Календаря.
        await _run_feature(chat_id, "book", sessions, text=text)
        return

    m_switch = re.match(r"^(?:/use|план)\s*(\d+)\s*$", low.strip())
    if m_switch:
        fam = [sid for sid in _family_list(chat_id) if sessions.get(sid) is not None]
        n = int(m_switch.group(1))
        if 1 <= n <= len(fam):
            CHATS[chat_id] = fam[n - 1]
            await _send(chat_id, "Активный план: " + _describe_member(sessions[fam[n - 1]])
                        + ". /plan — открыть его, /family — весь список.")
        else:
            await _send(chat_id, f"В семье {len(fam)} план(а) — выберите номер из /family.")
        return

    sid = CHATS.get(chat_id)
    intake = sessions.get(sid) if sid else None
    if intake is None:
        await _send(chat_id, _BIND_HINT)
        return
    result = build_response(intake)
    reply = await llm_reply(text, intake, result)
    await _send(chat_id, reply if reply is not None else _answer(text, intake, result))
