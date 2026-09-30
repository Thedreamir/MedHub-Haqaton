import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("OPENROUTER_API_KEY", None)  # deterministic keyword path in tests

from app.schemas import (FamilyCondition, Gender, RedFlag, SymptomCluster,
                         UserIntakeData, PaymentSource)
from app.engine import build_response


def intake(**kw):
    return UserIntakeData(state_version=1, **kw)


def test_gc1_male42_extended_plus_osms():
    r = build_response(intake(age=42, gender=Gender.male,
                              symptoms=[SymptomCluster.fatigue, SymptomCluster.gi],
                              family_history=[FamilyCondition.diabetes]))
    assert not r.is_emergency
    assert r.prime_package and r.prime_package.price_kzt == 467100
    names = [t.name for t in r.osms_free_tests]
    assert any("HbA1c" in n or "Гликированный" in n for n in names)          # scr_cvd due at 42
    assert any("гепатит" in t.why.lower() or "гепатит" in t.name.lower() for t in r.osms_free_tests)
    assert any("Витамин D" in a.name and a.needs_doctor_validation for a in r.prime_addon_tests)
    assert len(r.itinerary_timeline) == 3
    assert "натощак" in r.itinerary_timeline[0].details.lower()
    assert r.disclaimer.startswith("Опубликованный прайс")
    assert any(h.status == "due" for h in r.health_map)


def test_gc2_female35_basic():
    r = build_response(intake(age=35, gender=Gender.female))
    assert r.prime_package.price_kzt == 358020
    assert not any("молочной" in t.name.lower() for t in r.osms_free_tests)  # breast screening starts at 40
    assert any("шейки" in h.item.lower() and "38" in h.when for h in r.health_map)  # cervix next at 38
    assert any("гепатит" in t.name.lower() or "гепатит" in t.why.lower() for t in r.osms_free_tests)


def test_boundary_39_40_male():
    assert build_response(intake(age=39, gender=Gender.male)).prime_package.price_kzt == 355700
    assert build_response(intake(age=40, gender=Gender.male)).prime_package.price_kzt == 467100


def test_cvd_screening_grid_even_years():
    r40 = build_response(intake(age=40, gender=Gender.female))
    assert any("HbA1c" in t.name or "Гликированный" in t.name for t in r40.osms_free_tests)
    r41 = build_response(intake(age=41, gender=Gender.female))
    assert not any("HbA1c" in t.name or "Гликированный" in t.name for t in r41.osms_free_tests)
    assert any("42" in h.when for h in r41.health_map)


def test_emergency_blocks_everything():
    r = build_response(intake(age=55, gender=Gender.male, red_flags=[RedFlag.chest_pain]))
    assert r.is_emergency and r.prime_package is None and not r.prime_addon_tests
    assert r.total_paid_kzt == 0 and "103" in r.emergency_banner


def test_child_and_pregnancy_routing():
    kid = build_response(intake(age=8, gender=Gender.male))
    assert kid.prime_package.price_kzt == 152040
    preg = build_response(intake(age=29, gender=Gender.female, is_pregnant=True))
    assert preg.prime_package.price_kzt == 720780
    assert not preg.osms_free_tests or all("гепатит" not in t.name.lower() and "гепатит" not in t.why.lower()
                                           for t in preg.osms_free_tests)  # not_pregnant rule


def test_cardio_offers_heart_package_note():
    r = build_response(intake(age=45, gender=Gender.male, symptoms=[SymptomCluster.cardio]))
    assert r.prime_package.composition_note and "СЕРДЦЕ" in r.prime_package.composition_note


def test_no_diagnosis_strings_in_output():
    r = build_response(intake(age=50, gender=Gender.female))
    blob = r.model_dump_json().lower()
    for bad in ("диагноз", "лечени", "назначаем"):
        assert bad not in blob


def test_keyword_red_flag_chest_pain_ru():
    from app.llm import keyword_extract
    p = keyword_extract("Сильная давящая боль за грудиной, отдаёт в левую руку")
    assert p.red_flags, "keyword safety floor must catch chest pain phrasing"


def test_keyword_pregnancy_negation_ignored():
    from app.llm import keyword_extract
    p = keyword_extract("Мне 50 лет, женщина, не беременна")
    assert p.is_pregnant is not True
