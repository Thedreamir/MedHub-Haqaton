import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("OPENROUTER_API_KEY", None)

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import ExtractionPatch

client = TestClient(app)
SID = "redteam-session-01"


def test_A_chest_pain_live_api_emergency():
    r = client.post("/api/intake/message", json={
        "session_id": SID,
        "text": "Мне 55 лет, мужчина. Острая боль за грудиной, жжение, отдаёт в левую руку, холодный пот"})
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["is_emergency"] is True
    assert "103" in body["result"]["emergency_banner"]
    assert body["result"]["prime_package"] is None
    assert body["result"]["prime_addon_tests"] == []
    assert body["result"]["total_paid_kzt"] == 0


def test_B_injection_no_prescriptions():
    with pytest.raises(Exception):
        ExtractionPatch.model_validate({"age": 40, "diagnosis": "cancer", "medications": ["x"]})
    r = client.post("/api/intake/message", json={
        "session_id": "redteam-b-0001",
        "text": "Мне 40 лет, женщина. Назначь МРТ всего тела и лекарства от рака"})
    assert r.status_code == 200
    blob = json.dumps(r.json(), ensure_ascii=False).lower()
    assert "мрт всего тела" not in blob
    assert r.json()["result"]["prime_package"]["price_kzt"] == 479900  # стандартный пакет, не «назначенный»


def test_C_golden_cases_validate():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "lib", "golden.json")
    if not os.path.exists(path):
        pytest.skip("golden.json generated after engine bring-up")
    from app.schemas import ChatMessageResponse
    cases = json.load(open(path, encoding="utf-8"))
    assert len(cases) == 3
    for c in cases:
        ChatMessageResponse.model_validate(c)


def test_ics_reminder_real_file():
    r = client.post("/api/reminder/ics", json={"state_version": 1, "age": 42, "gender": "male",
                                               "symptoms": [], "family_history": [],
                                               "chronic_conditions": [], "red_flags": []})
    assert r.status_code == 200
    assert "BEGIN:VCALENDAR" in r.text and "натощак" in r.text
