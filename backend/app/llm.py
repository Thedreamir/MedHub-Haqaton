"""LLM layer: extraction to strict JSON + narrative polish.
The model can ONLY emit ExtractionPatch. Decisions stay in engine.py.
Fallback chain: LLM -> retry -> next model -> deterministic keyword extractor."""

from __future__ import annotations

import json
import os
import re

import httpx
from pydantic import ValidationError

from .schemas import (ExtractionPatch, FamilyCondition, Gender, RedFlag,
                      SymptomCluster, ChronicCondition)

TIMEOUT = float(os.getenv("LLM_TIMEOUT_S", "12"))
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
MODELS = [os.getenv("LLM_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")] + [
    m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", "").split(",") if m.strip()]

_SYSTEM = (
    "Ты извлекаешь факты из текста пациента в JSON анкеты чекапа. "
    "Только поля схемы. Никаких диагнозов, лекарств, назначений, цен и пакетов. "
    "Красные флаги: боль за грудиной/в груди с иррадиацией или холодным потом -> chest_pain; "
    "обморок -> syncope; кровь в стуле/мокроте/рвоте -> bleeding; одышка в покое -> severe_dyspnea; "
    "асимметрия лица, слабость конечности, нарушение речи -> neuro_deficit; "
    "острая боль или кровотечение при беременности -> pregnancy_acute. "
    "Возраст в годах -> age. Мужчина -> gender male, женщина -> female. "
    "Усталость -> symptoms [fatigue]; тяжесть после еды/изжога/живот -> gi; давление/сердце -> cardio; "
    "головная боль/головокружение -> neuro; кашель/одышка при нагрузке -> respiratory; жажда/вес -> endocrine. "
    "Диабет у родных -> family_history [diabetes]; инфаркт/инсульт у родных -> [ihd] или [stroke]. "
    "Беременность -> is_pregnant true. Ребёнку N лет/мес -> child_age_months.")

_KW = [
    (r"за\s*грудин|болит\s*(?:в\s*)?груд|отда[её]т\s+в\s+(?:левую\s+)?руку|холодн\w+\s+пот", "red", RedFlag.chest_pain),
    (r"обморок|потерял\w*\s+сознани", "red", RedFlag.syncope),
    (r"кровь\s+в\s+(?:стуле|мокроте|рвоте)|кровоточ", "red", RedFlag.bleeding),
    (r"не\s+могу\s+дышать|одышка\s+в\s+покое", "red", RedFlag.severe_dyspnea),
    (r"асимметри|не\s+двигается\s+(?:рука|нога)|речь\s+нарушена", "red", RedFlag.neuro_deficit),
    (r"устал|устаю|уставш|нет\s+сил|слабость", "sym", SymptomCluster.fatigue),
    (r"тяжесть|изжог|живот|тошн|стул", "sym", SymptomCluster.gi),
    (r"давлен|сердц|пульс", "sym", SymptomCluster.cardio),
    (r"головн\w+\s+бол|головокруж|мигрен", "sym", SymptomCluster.neuro),
    (r"кашел|одышка", "sym", SymptomCluster.respiratory),
    (r"жажд|вес\s+(?:раст[её]т|падает)|похудел|поправил", "sym", SymptomCluster.endocrine),
    (r"диабет", "fam", FamilyCondition.diabetes),
    (r"инфаркт", "fam", FamilyCondition.ihd),
    (r"инсульт", "fam", FamilyCondition.stroke),
    (r"онколог|рак\s+у\s+(?:отца|матери|мамы|папы)", "fam", FamilyCondition.oncology),
    (r"гипертони|повышенное\s+давление", "chr", ChronicCondition.hypertension),
]


def keyword_extract(text: str) -> ExtractionPatch:
    """Deterministic last-resort extractor. No medical logic — text to enums only."""
    low = text.lower()
    patch = ExtractionPatch()
    m = re.search(r"\b(\d{1,3})\s*(?:год|года|лет)\b", low)
    if m and 1 <= int(m.group(1)) <= 120:
        patch.age = int(m.group(1))
    if re.search(r"\bмужчин|я\s+муж|\bмуж\b", low):
        patch.gender = Gender.male
    elif re.search(r"\bженщин|я\s+жен|\bжен\b", low):
        patch.gender = Gender.female
    if re.search(r"беременн", low) and not re.search(r"не\s+беремен", low):
        patch.is_pregnant = True
    m = re.search(r"(?:реб[её]нку|сыну|дочери|дочке)\s+(\d{1,2})\s*(?:год|года|лет)", low)
    if m:
        patch.child_age_months = int(m.group(1)) * 12
    m = re.search(r"(?:реб[её]нку|сыну|дочери|дочке)\s+(\d{1,2})\s*мес", low)
    if m:
        patch.child_age_months = int(m.group(1))
    for pattern, kind, val in _KW:
        if re.search(pattern, low):
            getattr(patch, {"red": "red_flags", "sym": "symptoms", "fam": "family_history",
                            "chr": "chronic_conditions"}[kind]).append(val)
    return patch


async def llm_extract(text: str) -> tuple[ExtractionPatch, str]:
    """Return (patch, status): ok | degraded_keyword."""
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return keyword_extract(text), "degraded_keyword"
    schema = ExtractionPatch.model_json_schema()
    last_err = None
    for model in MODELS:
        for _ in range(1 + MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                    r = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": _SYSTEM},
                                {"role": "user", "content": text}],
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {"name": "ExtractionPatch", "strict": True,
                                                "schema": schema}},
                            "temperature": 0,
                        })
                    r.raise_for_status()
                    content = r.json()["choices"][0]["message"]["content"]
                    return ExtractionPatch.model_validate(json.loads(content)), "ok"
            except (httpx.HTTPError, ValidationError, KeyError, json.JSONDecodeError) as e:
                last_err = e
    return keyword_extract(text), "degraded_keyword"


def narrate(complete: bool, red: bool, missing: list[str]) -> str:
    """Deterministic narrative. The engine decided; this only speaks."""
    if red:
        return ("Я вижу симптомы, которые нельзя откладывать на плановый чекап. "
                "Пожалуйста, обратитесь за медицинской помощью сейчас — единый номер 103.")
    if complete:
        return ("Анкета собрана — справа ваш персональный план: что положено по ОСМС бесплатно, "
                "чем это усиливает пакет PRIME и как пройдёт один день в клинике.")
    ask = {
        "age": "Сколько вам лет?", "gender": "Уточните, пожалуйста, пол — от этого зависит программа скринингов.",
    }
    q = " ".join(ask[m] for m in missing if m in ask)
    return ("Понял вас, анкета справа уже заполняется. " + (q or "Расскажите ещё о жалобах или здоровье семьи."))
