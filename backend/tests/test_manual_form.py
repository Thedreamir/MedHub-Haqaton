"""Interactive анкета (manual form) endpoint tests.

The right panel can be filled by hand; it posts the full анкета to
/api/intake/manual. The same safety invariants as the chat path must hold.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("OPENROUTER_API_KEY", None)

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_manual_complete_intake_returns_result():
    r = client.post("/api/intake/manual", json={"session_id": "t-manual-1", "intake": {
        "state_version": 3, "age": 42, "gender": "male",
        "symptoms": ["fatigue", "gi"], "family_history": ["diabetes"],
        "chronic_conditions": [], "red_flags": [],
        "is_pregnant": None, "child_age_months": None,
    }})
    assert r.status_code == 200
    d = r.json()
    assert d["llm_status"] == "manual_form"
    assert d["intake"]["state_version"] == 4  # server increments monotonic version
    assert d["intake"]["age"] == 42 and d["intake"]["gender"] == "male"
    assert d["result"] is not None and not d["result"]["is_emergency"]
    assert d["result"]["prime_package"]["price_kzt"] == 467100


def test_manual_partial_intake_gets_preliminary_package():
    """Symptoms only (no age/gender) must still assemble a concrete package:
    preliminary «Базовый» 111 020 ₸ with a note, not an empty panel."""
    r = client.post("/api/intake/manual", json={"session_id": "t-manual-2", "intake": {
        "state_version": 0, "age": None, "gender": None,
        "symptoms": ["fatigue"], "family_history": [], "chronic_conditions": [],
        "red_flags": [], "is_pregnant": None, "child_age_months": None,
    }})
    assert r.status_code == 200
    d = r.json()
    assert d["result"] is not None and not d["result"]["is_emergency"]
    pkg = d["result"]["prime_package"]
    assert pkg["package_id"] == "prime_base" and pkg["price_kzt"] == 111020
    assert "Предварительный" in (pkg["composition_note"] or "")
    msg = d["assistant_message"].lower()
    assert "предварительный" in msg and ("возраст" in msg or "пол" in msg)


def test_manual_empty_intake_no_result():
    r = client.post("/api/intake/manual", json={"session_id": "t-manual-5", "intake": {
        "state_version": 0, "age": None, "gender": None,
        "symptoms": [], "family_history": [], "chronic_conditions": [],
        "red_flags": [], "is_pregnant": None, "child_age_months": None,
    }})
    assert r.status_code == 200
    assert r.json()["result"] is None


def test_manual_red_flag_emergency_no_commerce():
    r = client.post("/api/intake/manual", json={"session_id": "t-manual-3", "intake": {
        "state_version": 1, "age": 55, "gender": "male",
        "symptoms": [], "family_history": [], "chronic_conditions": [],
        "red_flags": ["chest_pain"], "is_pregnant": None, "child_age_months": None,
    }})
    assert r.status_code == 200
    d = r.json()
    res = d["result"]
    assert res["is_emergency"] and "103" in res["emergency_banner"]
    assert res["prime_package"] is None and res["total_paid_kzt"] == 0
    assert not res["osms_free_tests"] and not res["prime_addon_tests"]


def test_manual_rejects_unknown_enum_value():
    r = client.post("/api/intake/manual", json={"session_id": "t-manual-4", "intake": {
        "state_version": 0, "age": 30, "gender": "male",
        "symptoms": ["headache_extra"], "family_history": [], "chronic_conditions": [],
        "red_flags": [], "is_pregnant": None, "child_age_months": None,
    }})
    assert r.status_code == 422


def test_manual_then_chat_share_one_session():
    """Manual submit stores the анкета under the client's session; the next
    chat message must MERGE into it, not start from a blank state."""
    r = client.post("/api/intake/manual", json={"session_id": "t-shared", "intake": {
        "state_version": 0, "age": 42, "gender": "male",
        "symptoms": ["fatigue"], "family_history": [], "chronic_conditions": [],
        "red_flags": [], "is_pregnant": None, "child_age_months": None,
    }})
    assert r.status_code == 200
    r2 = client.post("/api/intake/message", json={
        "session_id": "t-shared", "text": "у отца инсульт"})
    assert r2.status_code == 200
    i = r2.json()["intake"]
    assert i["age"] == 42 and i["gender"] == "male"       # manual data survived
    assert "stroke" in i["family_history"]                 # chat fact merged in
    assert "fatigue" in i["symptoms"]


def test_keyword_floor_unions_into_llm_extraction(monkeypatch):
    """Regression: with the LLM path active but returning an empty patch,
    deterministic keyword hits (family/symptom/red-flag) must still land."""
    from app import main as m
    from app.schemas import ExtractionPatch

    async def empty_llm(text):
        return ExtractionPatch(), "ok"

    monkeypatch.setattr(m, "llm_extract", empty_llm)
    r = client.post("/api/intake/message", json={
        "session_id": "t-floor-1", "text": "у отца инсульт, я устаю"})
    assert r.status_code == 200, r.text
    i = r.json()["intake"]
    assert i["family_history"] == ["stroke"]
    assert i["symptoms"] == ["fatigue"]


def _msg(payload: dict, session: str = "followup-t") -> str:
    r = client.post("/api/intake/manual",
                    json={"session_id": session, "intake": payload})
    assert r.status_code == 200
    return r.json()["assistant_message"]


def test_symptoms_only_asks_age_and_gender():
    """«Устаю» без данных: бот спрашивает возраст и пол, а не молчит."""
    m = _msg({"symptoms": ["fatigue"], "state_version": 0})
    assert "Сколько вам лет" in m and "пол" in m


def test_complete_male_no_needless_questions():
    """«42 муж устаю»: никаких лишних вопросов."""
    m = _msg({"age": 42, "gender": "male", "symptoms": ["fatigue"],
              "smoking": False, "state_version": 0})
    assert "Уточню" not in m and "Сколько вам лет" not in m


def test_fertile_age_female_asked_pregnancy():
    """Женщина 30 без отметки о беременности: вопрос обязателен — от него
    зависит исключение облучения и выбор пакета."""
    m = _msg({"age": 30, "gender": "female", "state_version": 0})
    assert "беремен" in m.lower()


def test_pregnant_answered_stops_the_question():
    m = _msg({"age": 30, "gender": "female", "is_pregnant": False, "state_version": 0})
    assert "беремен" not in m.lower()


def test_red_flag_never_waits_for_questions():
    m = _msg({"red_flags": ["chest_pain"], "state_version": 0})
    assert "103" in m and "Сколько вам лет" not in m
