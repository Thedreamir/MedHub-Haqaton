"""Deterministic rule engine. ALL medical routing lives here + rules.json.
The LLM never calls these functions; it only fills the intake schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .schemas import (
    CheckupPackageResponse, FamilyCondition, Gender, HealthMapEntry,
    ItineraryStep, PaymentSource, PrimePackage, RedFlag, ReminderPlan,
    SymptomCluster, TestItem, UserIntakeData, ChronicCondition,
)

DATA = Path(__file__).parent / "data"
RULES = json.loads((DATA / "rules.json").read_text(encoding="utf-8"))
PRICES = json.loads((DATA / "prices.json").read_text(encoding="utf-8"))

_CHRONIC_MAP = {
    ChronicCondition.hypertension: "hypertension",
    ChronicCondition.ihd: "ihd",
    ChronicCondition.diabetes: "diabetes",
    ChronicCondition.glaucoma: "glaucoma",
    ChronicCondition.hepatitis_b: "chronic_hepatitis",
    ChronicCondition.hepatitis_c: "chronic_hepatitis",
}
_FAMILY_MAP = {  # intake enum -> rules.json family_history keys
    FamilyCondition.diabetes: ["diabetes"],
    FamilyCondition.ihd: ["early_cvd"],
    FamilyCondition.stroke: ["early_cvd"],
}
_COMPLAINT_MAP = {SymptomCluster.fatigue: "fatigue"}


def _sex(intake: UserIntakeData) -> Optional[str]:
    return {"male": "M", "female": "F"}.get(intake.gender.value) if intake.gender else None


def _chronic_keys(intake: UserIntakeData) -> set[str]:
    return {_CHRONIC_MAP[c] for c in intake.chronic_conditions if c in _CHRONIC_MAP}


def _family_keys(intake: UserIntakeData) -> set[str]:
    out: set[str] = set()
    for f in intake.family_history:
        out.update(_FAMILY_MAP.get(f, []))
    return out


def _eval_screening(scr: dict, intake: UserIntakeData):
    """Return (status, note): status in due|future|excluded|risk_unknown."""
    w = scr.get("when", {})
    age = intake.age
    sex = _sex(intake)
    chronic = _chronic_keys(intake)
    if age is None or sex is None:
        return None, None
    if w.get("sex") and sex not in w["sex"]:
        return None, None
    if any(c in chronic for c in w.get("not_registered", [])):
        return "excluded", RULES.get("registered_exclusion_note", "")
    if w.get("not_pregnant") and intake.is_pregnant:
        return None, None
    if w.get("age_min") and age < w["age_min"]:
        return None, None
    if w.get("age_year"):
        if age in w["age_year"]:
            due = "due"
        else:
            later = [y for y in w["age_year"] if y > age]
            return ("future", min(later)) if later else (None, None)
    else:
        due = "due"
    if w.get("any_of"):
        return "risk_unknown", None  # группа риска (стаж курения) уточняется врачом
    return due, None


def _osms_layer(intake: UserIntakeData):
    tests, health, futures = [], [], []
    for scr in RULES["screening"]:
        status, note = _eval_screening(scr, intake)
        if status == "due":
            for name in scr.get("stage1", []):
                tests.append(TestItem(
                    name=name, why=scr["name"] + " — положен по приказу (0 ₸)",
                    payment=PaymentSource(scr["payment"]), source=scr.get("source", "DSM174")))
            health.append(HealthMapEntry(
                item=scr["name"], status="due", when=f"повтор каждые {scr.get('repeat_years','?')} года",
                why="периодичность по ДСМ-174/2020", source=scr.get("source", "DSM174")))
        elif status == "risk_unknown":
            tests.append(TestItem(
                name=scr["name"], why="входит в приказ № 75/2026; принадлежность к группе риска подтверждает врач",
                payment=PaymentSource(scr["payment"]), source=scr.get("source", "DSM75"),
                needs_doctor_validation=True))
        elif status == "future":
            health.append(HealthMapEntry(
                item=scr["name"], status="next_step", when=f"положен с {note} лет по приказу",
                why="возрастная сетка ДСМ-174/2020", source=scr.get("source", "DSM174")))
        elif status == "excluded":
            health.append(HealthMapEntry(
                item=scr["name"], status="next_step", when="у вашего врача по наблюдению",
                why=note or "состоите на динамическом наблюдении", source="DSM174"))
    return tests, health


def _select_package(intake: UserIntakeData):
    """Return (PrimePackage, addon_tests). Pure rules + price overlay."""
    age, sex = intake.age, _sex(intake)
    cardio = (SymptomCluster.cardio in intake.symptoms
              or bool(_family_keys(intake) & {"early_cvd"})
              or ChronicCondition.hypertension in intake.chronic_conditions)
    heart_note = (" При кардио-направлении доступен пакет «СЕРДЦЕ» — "
                  f"{PRICES['heart']['price_kzt']:,} ₸. {PRICES['heart']['composition_note']}").replace(",", " ")

    if intake.is_pregnant:
        p = PRICES["pregnancy"]
        return PrimePackage(package_id="prime_pregnancy", name=p["name"], price_kzt=p["price_kzt"]), []
    if (intake.child_age_months is not None) or (age is not None and age < 18):
        mini, ext = PRICES["child_mini"], PRICES["child_extended"]
        if intake.child_age_months is not None and intake.child_age_months <= 12:
            b = PRICES["baby"]
            return PrimePackage(package_id="prime_baby", name=b["name"], price_kzt=b["price_kzt"]), []
        pkg = RULES["packages"][0]
        return PrimePackage(
            package_id="prime_child", name=mini["name"], price_kzt=mini["price_kzt"],
            composition_note=f"Доступно усиление: {ext['name']} — {ext['price_kzt']:,} ₸".replace(",", " "),
            tests=[TestItem(name=e, why="входит в детский пакет", payment=PaymentSource.paid_prime,
                            source="PRIME") for e in pkg.get("exams", [])]), []
    if age is None or sex is None:
        p = PRICES["base"]
        return PrimePackage(package_id="prime_base", name=p["name"], price_kzt=p["price_kzt"]), []

    if age <= 39:
        pkg = RULES["packages"][1]
        key = "basic_m" if sex == "M" else "basic_f"
    else:
        pkg = RULES["packages"][2]
        key = "extended_m" if sex == "M" else "extended_f"
    price = PRICES[key]
    exams = pkg.get("male_exams" if sex == "M" else "female_exams") or pkg.get("exams", [])
    note = price.get("discrepancy_note")
    if cardio:
        note = (note + " " if note else "") + heart_note.strip()
    tests = [TestItem(name=e, why="входит в пакет PRIME", payment=PaymentSource.paid_prime,
                      source="PRIME") for e in exams]
    return PrimePackage(
        package_id=pkg["id"] + "_" + sex.lower(), name=price["name"],
        price_kzt=price["price_kzt"], composition_note=note,
        discrepancy_note=price.get("discrepancy_note"), tests=tests), []


def _overlap_tag(osms: list[TestItem], pkg: PrimePackage) -> None:
    """Exams covered by OSMS are tagged 0 ₸ inside the PRIME list (dedupe by substring)."""
    if not pkg.tests:
        return
    osms_names = " ".join(t.name.lower() for t in osms)
    overlap_hints = " ".join(
        h.lower() for scr in RULES["screening"] for h in scr.get("prime_overlap", []))
    for t in pkg.tests:
        low = t.name.lower()
        if low in osms_names or (overlap_hints and any(h[:12] in low for h in overlap_hints.split("  ") if h)):
            t.payment = PaymentSource.free_gobmp
            t.why = "пересекается со скринингом — по ОСМС 0 ₸"


def _complaint_addons(intake: UserIntakeData) -> list[TestItem]:
    out = []
    for cmp_ in RULES.get("complaints", []):
        w = cmp_.get("when", {})
        hit = False
        if w.get("complaint") and any(_COMPLAINT_MAP.get(s) == w["complaint"] for s in intake.symptoms):
            hit = True
        if w.get("family_history") and w["family_history"] in _family_keys(intake):
            hit = True
        if hit and cmp_.get("action") != "red_flag":
            for e in cmp_.get("exams", []):
                out.append(TestItem(
                    name=e, why=cmp_.get("note") or "по жалобам/анамнезу — правило клиники",
                    payment=PaymentSource.paid_prime, source=cmp_.get("source", "CLINIC_RULE"),
                    needs_doctor_validation=cmp_.get("needs_doctor_validation", True)))
    return out


def _anamnesis_addons(intake: UserIntakeData) -> list[TestItem]:
    out = []
    catalog = {c["id"]: c["name"] for c in RULES.get("prime_catalog", [])}
    chronic = _chronic_keys(intake)
    fam = _family_keys(intake)
    cond_map = {"diabetes": "diabetes", "glaucoma": "glaucoma"}
    for rule in RULES.get("anamnesis_rules", []):
        w = rule.get("when", {})
        hit = False
        if w.get("conditions") and (w["conditions"] in chronic or w["conditions"] in cond_map.values()):
            hit = True
        if w.get("family_history") and w["family_history"] in fam:
            hit = True
        if w.get("sex") and w["sex"] != _sex(intake):
            hit = False
        if not hit:
            continue
        for c in rule.get("add", []):
            if c in catalog:
                out.append(TestItem(
                    name=catalog[c], why=f"по анамнезу: {rule.get('why','')}",
                    payment=PaymentSource.paid_prime, source=rule.get("source", "ANAMNESIS_DRAFT"),
                    needs_doctor_validation=True))
    # dedupe
    seen, dedup = set(), []
    for t in out:
        if t.name not in seen:
            seen.add(t.name)
            dedup.append(t)
    return dedup


def _route(intake: UserIntakeData, pkg: PrimePackage | None, addons: list[TestItem]) -> list[ItineraryStep]:
    steps: list[ItineraryStep] = []
    order = 1
    all_exam_text = " ".join([*(t.name for t in (pkg.tests if pkg else [])), *(a.name for a in addons)]).lower()
    prep_titles = {"now": [], "eve": [], "morning": [], "after": []}
    for pr in RULES.get("prep_catalog", []):
        if any(m.lower() in all_exam_text for m in pr.get("match", [])):
            prep_titles.setdefault(pr.get("day", "morning"), []).append(pr["title"])
    prep_flat = prep_titles["now"] + prep_titles["eve"] + prep_titles["morning"]
    steps.append(ItineraryStep(order=order, block="День подготовки", title="Подготовка к чекапу",
                               details="; ".join(prep_flat) + ". Подготовку подтверждает клиника при записи."
                               if prep_flat else "Подготовку подтверждает клиника при записи."))
    order += 1
    steps.append(ItineraryStep(order=order, block="День визита", time_window="8:00–16:00",
                               title="Чекап за один день",
                               details=" → ".join(RULES.get("day_route_order", {}).get("steps", [])[:5])))
    order += 1
    after = "Результаты — на следующий день. " + ("; ".join(prep_titles["after"]) + ". " if prep_titles["after"] else "")
    steps.append(ItineraryStep(order=order, block="После визита", title="Результаты и заключение",
                               details=after + "Заключение врача-куратора через 2–3 дня."))
    return steps


def build_response(intake: UserIntakeData) -> CheckupPackageResponse:
    if intake.red_flags:
        return CheckupPackageResponse(is_emergency=True)
    osms, health = _osms_layer(intake)
    pkg, _ = _select_package(intake)
    _overlap_tag(osms, pkg)
    addons = _complaint_addons(intake) + _anamnesis_addons(intake)
    total = (pkg.price_kzt or 0)
    health.insert(0, HealthMapEntry(
        item="Чекап PRIME (демо, синтетические данные)", status="done", when="сегодня",
        why="демо-срез карты здоровья", source="DEMO"))
    health.insert(1, HealthMapEntry(
        item="Заключение врача-куратора", status="next_step", when="через 2–3 дня после визита",
        why="итог маршрута", source="PRIME"))
    return CheckupPackageResponse(
        is_emergency=False, osms_free_tests=osms, prime_package=pkg,
        prime_addon_tests=addons, total_paid_kzt=total,
        itinerary_timeline=_route(intake, pkg, addons), health_map=health,
        reminder=ReminderPlan(
            channel="ics", demo=True,
            message_preview="Завтра чекап PRIME: анализы строго натощак, вода можно. Начало в 8:00.",
            due_in="повторный скрининг — по срокам из карты здоровья"))
