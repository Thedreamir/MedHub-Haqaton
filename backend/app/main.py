import os
import uuid
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .engine import build_response
from .llm import llm_extract, narrate
from .schemas import (ChatMessageRequest, ChatMessageResponse, CheckupPackageResponse,
                      UserIntakeData)

app = FastAPI(title="Check-up Intelligence Constructor", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSIONS: dict[str, UserIntakeData] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


def _merge(intake: UserIntakeData, patch) -> UserIntakeData:
    data = intake.model_dump()
    for f in ("age", "gender", "is_pregnant", "child_age_months"):
        v = getattr(patch, f)
        if v is not None:
            data[f] = v
    for f in ("symptoms", "family_history", "chronic_conditions", "red_flags"):
        merged = list(dict.fromkeys([*data[f], *getattr(patch, f)]))
        data[f] = merged
    data["state_version"] = intake.state_version + 1
    return UserIntakeData.model_validate(data)


def _finalize(intake: UserIntakeData, status: str) -> ChatMessageResponse:
    red = bool(intake.red_flags)
    missing = [f for f in ("age", "gender") if getattr(intake, f) is None]
    complete = red or not missing
    result = build_response(intake) if complete else None
    return ChatMessageResponse(intake=intake, assistant_message=narrate(complete, red, missing),
                               llm_status=status, result=result)


@app.post("/api/intake/message", response_model=ChatMessageResponse)
async def intake_message(req: ChatMessageRequest):
    intake = SESSIONS.get(req.session_id, UserIntakeData(state_version=0))
    patch, status = await llm_extract(req.text)
    intake = _merge(intake, patch)
    SESSIONS[req.session_id] = intake
    return _finalize(intake, status)


@app.post("/api/intake/manual", response_model=ChatMessageResponse)
async def intake_manual(intake: UserIntakeData):
    intake.state_version += 1
    SESSIONS[str(uuid.uuid4())] = intake
    return _finalize(intake, "manual_form")


@app.post("/api/intake/reset/{session_id}")
def intake_reset(session_id: str):
    SESSIONS.pop(session_id, None)
    return {"reset": True}


@app.post("/api/reminder/ics", response_class=PlainTextResponse)
async def reminder_ics(intake: UserIntakeData):
    tomorrow = date.today() + timedelta(days=1)
    dt = tomorrow.strftime("%Y%m%d")
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Checkup Constructor//RU", "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@checkup-demo", f"DTSTART;VALUE=DATE:{dt}",
        "SUMMARY:Чекап PRIME — анализы строго натощак (вода можно), начало в 8:00",
        "DESCRIPTION:Демо-напоминание. Подготовку подтверждает клиника при записи: +7 747 094 26 21",
        "END:VEVENT", "END:VCALENDAR", ""])
    return PlainTextResponse(ics, media_type="text/calendar",
                             headers={"Content-Disposition": "attachment; filename=checkup-reminder.ics"})
