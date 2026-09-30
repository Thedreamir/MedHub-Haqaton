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
    r = client.post("/api/intake/manual", json={
        "state_version": 3, "age": 42, "gender": "male",
        "symptoms": ["fatigue", "gi"], "family_history": ["diabetes"],
        "chronic_conditions": [], "red_flags": [],
        "is_pregnant": None, "child_age_months": None,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["llm_status"] == "manual_form"
    assert d["intake"]["state_version"] == 4  # server increments monotonic version
    assert d["intake"]["age"] == 42 and d["intake"]["gender"] == "male"
    assert d["result"] is not None and not d["result"]["is_emergency"]
    assert d["result"]["prime_package"]["price_kzt"] == 467100


def test_manual_incomplete_intake_asks_for_missing():
    r = client.post("/api/intake/manual", json={
        "state_version": 0, "age": None, "gender": None,
        "symptoms": ["fatigue"], "family_history": [], "chronic_conditions": [],
        "red_flags": [], "is_pregnant": None, "child_age_months": None,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["result"] is None
    assert "возраст" in d["assistant_message"].lower() or "пол" in d["assistant_message"].lower()


def test_manual_red_flag_emergency_no_commerce():
    r = client.post("/api/intake/manual", json={
        "state_version": 1, "age": 55, "gender": "male",
        "symptoms": [], "family_history": [], "chronic_conditions": [],
        "red_flags": ["chest_pain"], "is_pregnant": None, "child_age_months": None,
    })
    assert r.status_code == 200
    d = r.json()
    res = d["result"]
    assert res["is_emergency"] and "103" in res["emergency_banner"]
    assert res["prime_package"] is None and res["total_paid_kzt"] == 0
    assert not res["osms_free_tests"] and not res["prime_addon_tests"]


def test_manual_rejects_unknown_enum_value():
    r = client.post("/api/intake/manual", json={
        "state_version": 0, "age": 30, "gender": "male",
        "symptoms": ["headache_extra"], "family_history": [], "chronic_conditions": [],
        "red_flags": [], "is_pregnant": None, "child_age_months": None,
    })
    assert r.status_code == 422
