"""
Strict data contracts — Check-up Intelligence Constructor (Track 033).

Layer rule (the safety boundary of the whole system):

    LLM  -> may ONLY produce `ExtractionPatch` payloads (strict JSON,
            extra fields forbidden, enum-locked). It never sees prices,
            never picks packages, never touches red-flag decisions.

    Rule engine (deterministic Python + rules.json, Приказ ДСМ-174/2020
    ред. № 71/2025, № 109/2025, № 75/2026) -> builds `CheckupPackageResponse`.
    The emergency invariant is enforced here, at the schema layer: a response
    with is_emergency=True and any commercial content cannot be constructed.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

DISCLAIMER = (
    "Опубликованный прайс. Финальную стоимость и состав подтверждает клиника PRIME."
)
NOT_DIAGNOSIS = "Не является медицинской диагностикой."
EMERGENCY_BANNER = (
    "Обнаружены признаки состояния, требующего немедленной медицинской помощи. "
    "Единый номер экстренных служб: 103. Подбор чекапа не выполняется."
)


class StrictModel(BaseModel):
    """Everything in this system is strict and closed by default."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Enums — the LLM can only ever emit these literals
# ---------------------------------------------------------------------------


class Gender(str, Enum):
    male = "male"
    female = "female"


class SymptomCluster(str, Enum):
    fatigue = "fatigue"
    gi = "gi"  # тяжесть после еды, изжога, стул
    cardio = "cardio"  # давление, сердцебиение, отёки
    neuro = "neuro"  # головная боль, головокружение, сон
    respiratory = "respiratory"  # кашель, одышка при нагрузке
    endocrine = "endocrine"  # жажда, изменения веса
    musculoskeletal = "musculoskeletal"
    womens_health = "womens_health"
    mens_health = "mens_health"
    vision = "vision"
    skin = "skin"
    other = "other"


class RedFlag(str, Enum):
    chest_pain = "chest_pain"  # боль за грудиной, иррадиация, холодный пот
    neuro_deficit = "neuro_deficit"  # асимметрия лица, слабость в конечности, нарушение речи
    severe_dyspnea = "severe_dyspnea"  # одышка в покое
    bleeding = "bleeding"  # кровь в стуле/мокроте/рвоте
    syncope = "syncope"  # обморок
    high_fever = "high_fever"
    pregnancy_acute = "pregnancy_acute"  # острая боль/кровотечение при беременности
    suicidal_ideation = "suicidal_ideation"


class FamilyCondition(str, Enum):
    diabetes = "diabetes"
    hypertension = "hypertension"
    ihd = "ihd"  # ишемическая болезнь сердца / инфаркт у родственников
    stroke = "stroke"
    oncology = "oncology"
    glaucoma = "glaucoma"


class ChronicCondition(str, Enum):
    hypertension = "hypertension"
    ihd = "ihd"
    diabetes = "diabetes"
    glaucoma = "glaucoma"
    hepatitis_b = "hepatitis_b"
    hepatitis_c = "hepatitis_c"
    other = "other"


# ---------------------------------------------------------------------------
# LLM-facing contract (extraction only)
# ---------------------------------------------------------------------------


class ExtractionPatch(StrictModel):
    """What the LLM is allowed to say. Partial by design: only facts it
    actually found in the patient's message. `extra=forbid` makes any
    hallucinated field (diagnosis, medication, package, price) a hard
    validation error that the backend discards."""

    age: Optional[int] = Field(default=None, ge=1, le=120)
    gender: Optional[Gender] = None
    symptoms: list[SymptomCluster] = Field(default_factory=list)
    family_history: list[FamilyCondition] = Field(default_factory=list)
    chronic_conditions: list[ChronicCondition] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    is_pregnant: Optional[bool] = None
    child_age_months: Optional[int] = Field(default=None, ge=0, le=17 * 12)
    smoking: Optional[bool] = None


class ManualIntakeRequest(StrictModel):
    """Manual анкета submit: the full form plus the chat session it belongs to,
    so chat and manual entry write into ONE shared server-side state."""

    session_id: str
    intake: "UserIntakeData"


class UserIntakeData(StrictModel):
    """Server-canonical анкета. The only object the frontend ever renders.
    Built/updated by the backend after re-validating every ExtractionPatch."""

    age: Optional[int] = Field(default=None, ge=1, le=120)
    gender: Optional[Gender] = None
    symptoms: list[SymptomCluster] = Field(default_factory=list)
    family_history: list[FamilyCondition] = Field(default_factory=list)
    chronic_conditions: list[ChronicCondition] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    is_pregnant: Optional[bool] = None
    child_age_months: Optional[int] = Field(default=None, ge=0, le=17 * 12)
    smoking: Optional[bool] = None
    state_version: int = Field(ge=0, description="Monotonic; client drops older versions")


# ---------------------------------------------------------------------------
# Engine-facing contract (decisions — never touched by the LLM)
# ---------------------------------------------------------------------------


class PaymentSource(str, Enum):
    free_gobmp = "free_gobmp"  # ГОБМП
    free_osms = "free_osms"  # ОСМС
    paid_prime = "paid_prime"


class TestItem(StrictModel):
    name: str
    why: str  # человеческое обоснование, одна строка
    payment: PaymentSource
    source: str  # "DSM174 прил. 1 п.1" | "PRIME" | "CLINIC_RULE" | ...
    needs_doctor_validation: bool = False  # CLINIC_RULE / ANAMNESIS_DRAFT badge


class PrimePackage(StrictModel):
    package_id: str
    name: str
    price_kzt: Optional[int] = None  # None -> «цена уточняется клиникой»
    composition_note: Optional[str] = None  # напр. «состав не опубликован»
    discrepancy_note: Optional[str] = None  # напр. 5 vs 8 онкомаркеров
    tests: list[TestItem] = Field(default_factory=list)


class ItineraryStep(StrictModel):
    order: int = Field(ge=1)
    block: str  # «День подготовки» | «День визита» | «После визита»
    time_window: Optional[str] = None  # «8:00–16:00»
    title: str
    details: str = ""


class HealthMapEntry(StrictModel):
    item: str
    status: str  # done | next_step | due
    when: str
    why: str
    source: str


class ReminderPlan(StrictModel):
    channel: str  # telegram | ics
    message_preview: str
    due_in: str  # «через 3 года» | «завтра, натощак»
    demo: bool = True


class CheckupPackageResponse(StrictModel):
    """Final engine output. Invariant: emergency implies zero commercial
    content — enforced below, so an upsell-on-red-flag response is
    unconstructable, not merely unlikely."""

    is_emergency: bool
    emergency_banner: Optional[str] = None
    osms_free_tests: list[TestItem] = Field(default_factory=list)
    prime_package: Optional[PrimePackage] = None
    prime_addon_tests: list[TestItem] = Field(default_factory=list)
    total_paid_kzt: int = Field(default=0, ge=0)
    itinerary_timeline: list[ItineraryStep] = Field(default_factory=list)
    health_map: list[HealthMapEntry] = Field(default_factory=list)
    reminder: Optional[ReminderPlan] = None
    booking_contact_phone: str = "+7 747 094 26 21"
    booking_contact_email: str = "salem@primegc.kz"
    disclaimer: str = DISCLAIMER
    not_diagnosis: str = NOT_DIAGNOSIS

    @model_validator(mode="after")
    def emergency_blocks_commercial(self) -> "CheckupPackageResponse":
        if self.is_emergency:
            if self.prime_package is not None or self.prime_addon_tests:
                raise ValueError(
                    "invariant violated: is_emergency=True with commercial content"
                )
            object.__setattr__(self, "emergency_banner", EMERGENCY_BANNER)
            object.__setattr__(self, "total_paid_kzt", 0)
        return self


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class ChatMessageRequest(StrictModel):
    session_id: str = Field(min_length=8, max_length=64)
    text: str = Field(min_length=1, max_length=2000)


class ChatMessageResponse(StrictModel):
    intake: UserIntakeData
    assistant_message: str  # narrative explanation of engine state, not a decision
    llm_status: str  # ok | degraded_manual_form | cached_golden
    result: Optional[CheckupPackageResponse] = None  # present when анкета complete
