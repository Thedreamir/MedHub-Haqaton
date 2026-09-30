import asyncio
import os
import uuid
from datetime import date, timedelta

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from .engine import build_response, followup_questions
from .llm import keyword_extract, llm_extract, narrate
from .report import build_report_pdf
from . import tg
from .store import PersistedDict
from .schemas import (ChatMessageRequest, ChatMessageResponse, CheckupPackageResponse,
                      ManualIntakeRequest, UserIntakeData)

app = FastAPI(title="Check-up Intelligence Constructor", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSIONS: PersistedDict = PersistedDict(
    "sessions",
    dump=lambda intake: intake.model_dump_json(),
    load=UserIntakeData.model_validate_json)


@app.get("/health")
def health():
    return {"status": "ok"}


def _merge(intake: UserIntakeData, patch) -> UserIntakeData:
    data = intake.model_dump()
    for f in ("age", "gender", "is_pregnant", "child_age_months", "smoking"):
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
    # Any real data already assembles a concrete package: age+sex missing falls
    # back to the preliminary «Базовый» (111 020 ₸) instead of an empty panel.
    has_data = any([
        intake.age is not None, intake.gender is not None,
        intake.symptoms, intake.family_history, intake.chronic_conditions,
        intake.is_pregnant is not None, intake.child_age_months is not None,
        intake.smoking is not None,
    ])
    show_result = complete or bool(has_data)
    result = build_response(intake) if show_result else None
    questions = [] if red else followup_questions(intake)
    return ChatMessageResponse(intake=intake,
                               assistant_message=narrate(complete, red, missing,
                                                         preliminary=show_result and not complete,
                                                         questions=questions),
                               llm_status=status, result=result)


@app.post("/api/intake/message", response_model=ChatMessageResponse)
async def intake_message(req: ChatMessageRequest):
    intake = SESSIONS.get(req.session_id, UserIntakeData(state_version=0))
    patch, status = await llm_extract(req.text)
    # Safety floor: deterministic keyword scan unions into every extraction,
    # so an LLM miss can never silence an emergency or drop an explicit
    # medical term from a terse message.
    safety = keyword_extract(req.text)
    for field in ("red_flags", "symptoms", "family_history", "chronic_conditions"):
        extra = getattr(safety, field)
        if extra:
            setattr(patch, field, sorted(set(getattr(patch, field)) | set(extra)))
    intake = _merge(intake, patch)
    SESSIONS[req.session_id] = intake
    return _finalize(intake, status)


@app.post("/api/intake/manual", response_model=ChatMessageResponse)
async def intake_manual(req: ManualIntakeRequest):
    intake = req.intake
    intake.state_version += 1
    SESSIONS[req.session_id] = intake  # same session the chat writes to
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


@app.get("/api/report/{session_id}")
def report_pdf(session_id: str):
    """Скачиваемый персональный отчёт: анкета + пакет + обоснование каждого пункта."""
    intake = SESSIONS.get(session_id)
    if intake is None:
        raise HTTPException(404, "session not found — заполните анкету заново")
    pdf = build_report_pdf(intake, build_response(intake))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=checkup-plan.pdf"})

@app.get("/api/tg/health")
def tg_health():
    return {"configured": tg.configured(), "username": tg.bot_username()}


@app.get("/api/tg/start/{session_id}")
def tg_start(session_id: str):
    user = tg.bot_username()
    if not user:
        raise HTTPException(503, "Telegram-бот ещё не настроен")
    return RedirectResponse(f"https://t.me/{user}?start={session_id}")


@app.get("/api/tg/llm-selftest")
async def tg_llm_selftest():
    return await tg.llm_selftest()


@app.post("/api/tg/webhook")
async def tg_webhook(request: Request):
    # ACK сразу: LLM-цепочка может думать десятки секунд, а Telegram ждёт ответ
    # вебхука недолго. Обработка уходит в фон — ответ доедет следом.
    if not tg.configured():
        return {"ok": True, "configured": False}
    asyncio.create_task(tg.handle_update(await request.json(), SESSIONS))
    return {"ok": True}

@app.on_event("startup")
async def _start_tg_reminders():
    if tg.configured():
        asyncio.create_task(tg.reminder_loop(SESSIONS))
