import os, sys, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("OPENROUTER_API_KEY", None)

from app import tg
from app.schemas import Gender, UserIntakeData


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeSend:
    def __init__(self, monkeypatch):
        self.sent = []
        async def _f(chat_id, text):
            self.sent.append((chat_id, text))
        monkeypatch.setattr(tg, "_send", _f)


def upd(chat_id, text):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def test_start_binds_session_and_summarizes(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    sessions = {"s1": UserIntakeData(state_version=1, age=42, gender=Gender.male)}
    run(tg.handle_update(upd(777, "/start s1"), sessions))
    assert tg.CHATS[777] == "s1"
    body = fake.sent[0][1]
    assert "привязал" in body and "Умею:" in body and "Уже знаю о вас:" in body \
        and "Действия:" in body and "42 лет" in body


def test_start_without_session_gives_bind_hint(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    run(tg.handle_update(upd(777, "/start"), {}))
    assert "привяз" in fake.sent[0][1].lower() or "анкет" in fake.sent[0][1].lower()
    assert 777 not in tg.CHATS


def test_red_flag_gets_103_even_unbound(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    run(tg.handle_update(upd(555, "давящая боль в груди отдаёт в руку"), {}))
    assert "103" in fake.sent[0][1]


def test_bound_chat_answers_price_question(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    sessions = {"s1": UserIntakeData(state_version=1, age=42, gender=Gender.male)}
    run(tg.handle_update(upd(777, "/start s1"), sessions))
    fake.sent.clear()
    run(tg.handle_update(upd(777, "сколько стоит мой чекап?"), sessions))
    assert "467 100" in fake.sent[0][1] and "+7 747 094 26 21" in fake.sent[0][1]


def test_unbound_plain_text_gives_hint(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    run(tg.handle_update(upd(999, "что входит в пакет?"), {}))
    assert "анкет" in fake.sent[0][1].lower()


def _result(age=42, gender=Gender.male):
    from app.engine import build_response
    return build_response(UserIntakeData(state_version=1, age=age, gender=gender))


def test_navigator_osms_route():
    out = tg.green_navigator("скачет давление, побаливает сердце", _result())
    assert "ОСМС" in out and "0 ₸" in out and "сердечно-сосудистых" in out
    assert "salem@primegc.kz" in out and "+7 747 094 26 21" in out
    assert "Здравствуйте! Хочу записаться" in out


def test_navigator_prime_route_for_non_osms_complaint():
    out = tg.green_navigator("хочу проверить щитовидку и гормоны", _result())
    assert "PRIME" in out and "467 100" in out and "ОСМС это не попадает" in out.replace("под бесплатный скрининг ОСМС это не попадает", "ОСМС это не попадает")
    assert "Здравствуйте! Хочу записаться" in out


def test_navigator_urgent_complaint():
    out = tg.green_navigator("сильная боль в боку уже три дня не проходит", _result())
    assert "ближайшие 1–2 дня" in out


def test_navigator_calm_for_routine():
    out = tg.green_navigator("иногда тянет спину после работы", _result())
    assert "плановом порядке" in out


def test_due_screenings_and_remind_once(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg._LAST_REMIND.clear()
    intake = UserIntakeData(state_version=1, age=42, gender=Gender.male)
    assert tg.due_screenings(_result())              # у мужчины 42 есть due-позиции
    assert run(tg.remind_once(777, intake)) is True
    assert "ДСМ-174/2020" in fake.sent[0][1]
    assert run(tg.remind_once(777, intake)) is False  # анти-спам: повторно не шлём


def test_llm_reply_none_without_key_falls_back(monkeypatch):
    # без ключа llm_reply обязан вернуть None -> сработает детерминированный ответ
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    sessions = {"s1": UserIntakeData(state_version=1, age=42, gender=Gender.male)}
    run(tg.handle_update(upd(777, "/start s1"), sessions))
    fake.sent.clear()
    run(tg.handle_update(upd(777, "сколько стоит мой чекап?"), sessions))
    assert "467 100" in fake.sent[0][1]


def test_llm_selftest_without_key():
    res = run(tg.llm_selftest())
    assert res["ok"] is False and res["reason"] == "no OPENROUTER_API_KEY"


def test_context_card_contains_facts():
    card = tg._context_card(UserIntakeData(state_version=1, age=42, gender=Gender.male),
                            _result(), "скачет давление")
    assert "467 100" in card and "ОСМС" in card and "+7 747 094 26 21" in card


def test_plan_command_renders_statuses(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    sessions = {"s1": UserIntakeData(state_version=1, age=42, gender=Gender.male)}
    run(tg.handle_update(upd(777, "/start s1"), sessions))
    fake.sent.clear()
    run(tg.handle_update(upd(777, "/plan"), sessions))
    body = fake.sent[0][1]
    assert "Ваш чекап-план (42 лет, мужчина)" in body
    assert ("🔴" in body or "➡️" in body or "✅" in body)
    assert "467 100" in body and "записаться" in body


def test_plan_unbound_gives_hint(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg.CHATS.clear()
    run(tg.handle_update(upd(31337, "/plan"), {}))
    assert "анкет" in fake.sent[0][1].lower()


def test_booking_request_with_time_window():
    out = tg.booking_request(UserIntakeData(state_version=1, age=42, gender=Gender.male),
                             _result(), "хочу записаться вечером после работы")
    assert "Удобное время: вечером" in out and "467 100" in out
    assert "подтвердит контакт-центр" in out          # никаких выдуманных слотов
    assert "salem@primegc.kz" in out


def test_booking_request_without_time_window():
    out = tg.booking_request(UserIntakeData(state_version=1, age=42, gender=Gender.male),
                             _result(), "записаться")
    assert "Удобное время" not in out


def test_scenario_matrix_size_and_prime_routes():
    assert len(tg._SCENARIOS) >= 20
    # жалоба вне ОСМС-скрининга получает PRIME-маршрут с услугой в заявке
    out = tg.green_navigator("болит поясница уже неделю", _result())
    assert "PRIME" in out and "МРТ" in out and "Здравствуйте! Хочу записаться" in out
    assert "Это не диагноз" in out


def test_reminder_has_prep_booking_and_disclaimer(monkeypatch):
    fake = FakeSend(monkeypatch)
    tg._LAST_REMIND.clear()
    intake = UserIntakeData(state_version=1, age=42, gender=Gender.male)
    assert run(tg.remind_once(777, intake)) is True
    body = fake.sent[0][1]
    assert "Срок подошёл" in body and "натощак" in body and "записаться" in body
    assert "Это не диагноз" in body
