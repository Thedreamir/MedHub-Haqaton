"""PDF-отчёт: конкретный пакет + обоснование, без коммерции при красном флаге."""
import io

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import app

client = TestClient(app)


def _text(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def _manual(session: str, payload: dict):
    return client.post("/api/intake/manual", json={"session_id": session, "intake": payload})


def test_report_contains_package_and_rationale():
    _manual("report-male-42", {"age": 42, "gender": "male", "symptoms": ["fatigue"],
                               "family_history": ["diabetes"], "state_version": 0})
    r = client.get("/api/report/report-male-42")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-" and len(r.content) > 5000
    t = _text(r.content)
    assert "Мужской 40+" in t and "467 100" in t
    assert "Почему именно он" in t and "Зачем:" in t
    assert "Ваши данные" in t and "усталость" in t


def test_report_emergency_has_zero_commerce():
    _manual("report-redflag", {"age": 50, "gender": "female",
                               "red_flags": ["chest_pain"], "state_version": 0})
    r = client.get("/api/report/report-redflag")
    assert r.status_code == 200
    t = _text(r.content)
    assert "103" in t
    assert "₸" not in t and "пакет" not in t.lower().replace("чекап пакеты", "")


def test_report_unknown_session_404():
    assert client.get("/api/report/no-such-session").status_code == 404
