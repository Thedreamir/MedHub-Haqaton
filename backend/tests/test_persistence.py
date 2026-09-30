"""Привязки бота и сессии анкеты переживают рестарт процесса (SQLite write-through)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import store, tg
from app.main import SESSIONS
from app.schemas import UserIntakeData


def test_chat_binding_survives_restart():
    tg.CHATS.clear()
    tg.CHATS[555] = "sess-abc"
    store._reset()  # симуляция рестарта процесса: новое соединение с тем же файлом
    assert tg.CHATS.get(555) == "sess-abc"
    assert 555 in tg.CHATS
    tg.CHATS.clear()


def test_session_survives_restart():
    SESSIONS.clear()
    SESSIONS["s9"] = UserIntakeData(state_version=3, age=41, red_flags=[])
    store._reset()
    back = SESSIONS.get("s9")
    assert back is not None and back.age == 41 and back.state_version == 3
    SESSIONS.pop("s9", None)


def test_reminder_throttle_survives_restart():
    tg._LAST_REMIND.clear()
    tg._LAST_REMIND[777] = 123.5
    store._reset()
    assert tg._LAST_REMIND.get(777) == 123.5
    tg._LAST_REMIND.clear()
