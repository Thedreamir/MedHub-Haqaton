"""Долговечное хранилище состояния: SQLite на диске вместо in-memory dict.

Привязки Telegram-чатов (chat_id -> session_id), сессии анкеты и троттлинг
напоминаний переживают рестарт процесса: раньше каждый редеплой/падение
обнулял память, и бот «забывал» пользователей прямо во время защиты.
Каждая запись пишется на диск сразу (write-through), чтение идёт из того же
файла, так что отдельной загрузки при старте не нужно.

Путь: env CHECKUP_DB_PATH, по умолчанию checkup_state.db в рабочей папке.
На бесплатном Render файловая система эфемерна при редеплое — база начинается
заново после push, зато рестарты и падения внутри контейнера больше не страшны.
"""
import json
import os
import sqlite3
import threading

_lock = threading.Lock()
_conn = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = os.environ.get("CHECKUP_DB_PATH", "checkup_state.db")
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.execute("CREATE TABLE IF NOT EXISTS kv ("
                      "bucket TEXT NOT NULL, k TEXT NOT NULL, v TEXT NOT NULL, "
                      "PRIMARY KEY (bucket, k))")
        _conn.commit()
    return _conn


def _reset() -> None:
    """Закрыть соединение (тесты: симуляция рестарта процесса)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


class PersistedDict:
    """dict-интерфейс поверх SQLite: get / [] / in / pop / items / clear."""

    def __init__(self, bucket: str, dump=None, load=None):
        self.bucket = bucket
        self._dump = dump or (lambda v: json.dumps(v))
        self._load = load or json.loads

    def get(self, key, default=None):
        with _lock:
            row = _db().execute(
                "SELECT v FROM kv WHERE bucket=? AND k=?",
                (self.bucket, str(key))).fetchone()
        return self._load(row[0]) if row else default

    def __getitem__(self, key):
        sentinel = object()
        v = self.get(key, sentinel)
        if v is sentinel:
            raise KeyError(key)
        return v

    def __setitem__(self, key, value) -> None:
        with _lock:
            db = _db()
            db.execute("INSERT OR REPLACE INTO kv (bucket, k, v) VALUES (?,?,?)",
                       (self.bucket, str(key), self._dump(value)))
            db.commit()

    def __contains__(self, key) -> bool:
        with _lock:
            row = _db().execute(
                "SELECT 1 FROM kv WHERE bucket=? AND k=?",
                (self.bucket, str(key))).fetchone()
        return row is not None

    def pop(self, key, default=None):
        with _lock:
            db = _db()
            row = db.execute("SELECT v FROM kv WHERE bucket=? AND k=?",
                             (self.bucket, str(key))).fetchone()
            db.execute("DELETE FROM kv WHERE bucket=? AND k=?",
                       (self.bucket, str(key)))
            db.commit()
        return self._load(row[0]) if row else default

    def clear(self) -> None:
        with _lock:
            db = _db()
            db.execute("DELETE FROM kv WHERE bucket=?", (self.bucket,))
            db.commit()

    def items(self):
        with _lock:
            rows = _db().execute(
                "SELECT k, v FROM kv WHERE bucket=?", (self.bucket,)).fetchall()
        return [(k, self._load(v)) for k, v in rows]
