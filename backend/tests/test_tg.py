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
    assert "467 100" in body and "привязал" in body


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
