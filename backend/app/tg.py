"""Telegram-бот: живой ассистент поверх анкеты пользователя.

Deep-link t.me/<bot>?start=<session_id> привязывает чат к сессии анкеты;
бот отвечает по СВОЕМУ пакету/маршруту/карте здоровья и шлёт напоминания.
Красный флаг в любом сообщении -> мгновенный маршрут 103 (тот же keyword-floor,
что и в веб-чате). Токен живёт только в env TELEGRAM_BOT_TOKEN, никогда не в репо.
"""
import os

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
    lines = _plan_lines(intake, result)
    lines.append("Спросите про цену, состав пакета, маршрут дня, подготовку "
                 "или повторные скрининги — отвечу по вашей анкете.")
    return "\n".join(lines)


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
        await _send(chat_id,
                    "Готово — привязал чат к вашему чекап-плану.\n"
                    + _summary(intake, result)
                    + "\n\nНапомню о повторных скринингах по срокам из карты здоровья. "
                      "Спросите про цену, состав, маршрут или подготовку.")
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
    await _send(chat_id, _answer(text, intake, build_response(intake)))
