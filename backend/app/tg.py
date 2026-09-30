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
import time

import httpx

from .engine import build_response
from .llm import keyword_extract
from .schemas import CheckupPackageResponse, UserIntakeData

_API = "https://api.telegram.org/bot"

# chat_id -> session_id (демо: in-memory, как и сессии анкеты)
CHATS: dict[int, str] = {}


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def bot_username() -> str:
    return os.environ.get("TELEGRAM_BOT_USERNAME", "")


async def _send(chat_id: int, text: str) -> None:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not tok:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{_API}{tok}/sendMessage",
                     json={"chat_id": chat_id, "text": text})


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
    if any(w in t for w in ("цен", "стоит", "сколько", "стоимост")):
        lines = _plan_lines(intake, result)
        lines.append("Финальную стоимость и состав подтверждает клиника PRIME при записи: "
                     "+7 747 094 26 21.")
        return "\n".join(lines)
    if any(w in t for w in ("входит", "состав", "что сда", "какие анализ", "что буду")):
        if pkg and pkg.tests:
            names = "\n".join(f"• {x.name}" for x in pkg.tests[:12])
            return f"В пакет «{pkg.name}» входит:\n{names}"
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
    if any(w in t for w in ("подготов", "натощак", "можно ли есть", "диета")):
        prep = [s for s in result.itinerary_timeline if "подготов" in s.block.lower()]
        if prep:
            return "\n".join(f"{s.block}: {s.details}" for s in prep)
        return "Подготовку подтверждает клиника при записи: +7 747 094 26 21."
    # Свободный текст без явной темы — это жалоба/контекст: Зелёный навигатор.
    return green_navigator(text, result)



# ---------- Зелёный навигатор: жалоба -> срочность -> ОСМС vs PRIME -> заявка ----------

_URGENT_WORDS = (
    "высокая температур", "температура 39", "температура 40", "сильная боль",
    "острая боль", "не проходит", "кровь в", "кровотеч", "рвота кров",
    "потерял сознание", "обморок", "удушье", "не могу дышать",
)

# жалоба -> (ключевые слова, позиция бесплатного скрининга ОСМС по ДСМ-174/2020)
_OSMS_ROUTES = [
    (("сердц", "давлен", "гипертон", "пульс"),
     "скрининг сердечно-сосудистых заболеваний (АД, ЭКГ, липидный профиль)"),
    (("сахар", "диабет", "жажда", "глюкоз"),
     "скрининг сахарного диабета (глюкоза / HbA1c)"),
    (("груд", "молочн", "уплотнен"),
     "скрининг рака молочной железы (маммография, женщины 40–70)"),
    (("шейк", "цервик", "пап-тест", "мазок"),
     "скрининг рака шейки матки (цитология, женщины 30–70)"),
    (("кишеч", "стул", "колоноскоп"),
     "скрининг колоректального рака (анализ кала на скрытую кровь, 50–70)"),
    (("печен", "гепатит"),
     "скрининг вирусных гепатитов B и C"),
    (("лёгк", "легк", "кашель кур"),
     "скрининг рака лёгкого (низкодозная КТ, курящие 50–70)"),
    (("зрени", "глаз", "глауком"),
     "измерение внутриглазного давления (скрининг глаукомы)"),
]


def green_navigator(text: str, result: CheckupPackageResponse) -> str:
    """Свободная жалоба -> маршрут: срочность, ОСМС vs PRIME, готовый текст заявки."""
    urgent, osms_hit = _nav_facts(text)

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
        service = "консультацию врача" + (f" / пакет «{result.prime_package.name}»"
                                          if result.prime_package else "")

    request_text = (
        "Готовый текст заявки (отправьте на salem@primegc.kz или продиктуйте "
        "по +7 747 094 26 21):\n"
        f"«Здравствуйте! Хочу записаться: {service}. "
        f"Повод: {text.strip()[:200]}. Подскажите ближайшее время приёма.»")
    return f"Зелёный навигатор:\n\n{urgency}\n\n{route}\n\n{request_text}"


# ---------- Напоминания из карты здоровья ----------

_REMIND_INTERVAL_SEC = 6 * 3600          # как часто пересматривать карту
_REMIND_RESEND_SEC = 72 * 3600           # не чаще, чем раз в 3 суток по тем же позициям
_LAST_REMIND: dict[int, float] = {}      # chat_id -> ts последнего напоминания


def due_screenings(result: CheckupPackageResponse) -> list[str]:
    return [f"• {h.item} — {h.when}" for h in result.health_map
            if h.status in ("due", "next_step")]


async def remind_once(chat_id: int, intake: UserIntakeData) -> bool:
    """Шлёт напоминание о повторных скринингах, если оно по срокам. True = отправлено."""
    due = due_screenings(build_response(intake))
    if not due:
        return False
    last = _LAST_REMIND.get(chat_id, 0)
    if time.time() - last < _REMIND_RESEND_SEC:
        return False
    _LAST_REMIND[chat_id] = time.time()
    await _send(chat_id,
                "Напоминание из карты здоровья — по приказу ДСМ-174/2020 вам по срокам "
                "положено:\n" + "\n".join(due) +
                "\n\nСкрининги из списка бесплатны по ОСМС (направление — в поликлинике), "
                "остальное можно закрыть в PRIME: +7 747 094 26 21.")
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
    "qwen/qwen3-32b:free,qwen/qwen-2.5-72b-instruct:free,qwen/qwen3-235b-a22b:free"
).split(",") if m.strip()]

_SYSTEM = (
    "Ты Primey — живой ассистент клиники PRIME в Telegram. Отвечай тепло и по-человечески, "
    "коротко (2–8 строк), по-русски. Факты — ТОЛЬКО из карточки плана ниже: цены, состав, "
    "даты и телефоны не выдумывай и не округляй. Не ставь диагнозы и не обещай результат "
    "лечения. Если вопрос про цену/состав/маршрут/подготовку/повторные скрининги — отвечай "
    "точно по карточке. Если это жалоба — мягко дай маршрут из карточки (ОСМС или PRIME) "
    "и приложи готовый текст заявки. Экстренные состояния уже перехвачены до тебя: про 103 "
    "пиши, только если пользователь сам описывает угрозу жизни."
)


def _nav_facts(text: str):
    t = text.lower()
    urgent = any(w in t for w in _URGENT_WORDS)
    osms_hit = next((route for keys, route in _OSMS_ROUTES
                     if any(k in t for k in keys)), None)
    return urgent, osms_hit


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
    urgent, osms_hit = _nav_facts(text)
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
            except Exception:
                continue
    return {"ok": False, "reason": "all models failed", "models": _TG_MODELS}

_BIND_HINT = ("Сначала пройдите анкету на сайте конструктора и нажмите "
              "«Напоминания в Telegram» на странице результата — бот привяжется "
              "к вашему плану.")


async def handle_update(update: dict, sessions: dict) -> None:
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if chat_id is None or not text:
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
        result = build_response(intake)
        due = due_screenings(result)
        extra = ("\n\nПо срокам из карты здоровья уже положено:\n" + "\n".join(due)
                 ) if due else ""
        await _send(chat_id,
                    "Готово — привязал чат к вашему чекап-плану.\n"
                    + _summary(intake, result) + extra
                    + "\n\nНапомню о повторных скринингах по срокам из карты здоровья. "
                      "Спросите про цену, состав, маршрут или подготовку — или просто "
                      "опишите жалобу: Зелёный навигатор подскажет маршрут (ОСМС или PRIME).")
        return

    # Красный флаг не ждёт привязки: тот же keyword-floor, что и на сайте.
    if keyword_extract(text).red_flags:
        await _send(chat_id,
                    "По описанному похоже на состояние, которое нельзя откладывать на "
                    "плановый чекап. Пожалуйста, обратитесь за медицинской помощью "
                    "сейчас — единый номер 103.")
        return

    sid = CHATS.get(chat_id)
    intake = sessions.get(sid) if sid else None
    if intake is None:
        await _send(chat_id, _BIND_HINT)
        return
    result = build_response(intake)
    reply = await llm_reply(text, intake, result)
    await _send(chat_id, reply if reply is not None else _answer(text, intake, result))
