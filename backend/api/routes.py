import datetime
import hashlib
import json
import logging
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

import config
from api.schemas import DebateRequest, DebateResponse, PersonaOut, PersonaStatementOut
from debate import orchestrator, topic_validator
from debate.models import DebateTranscript
from limits import identity, rate_limiter
from personas.registry import all_personas, get_persona, is_valid_persona_key

logger = logging.getLogger("multipersonadebate.api")

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/admin/stats")
def admin_stats(x_admin_token: str = Header(default="")):
    if not config.ADMIN_TOKEN or not secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(404)

    allowed, global_calls_today = rate_limiter.check_global_cap(config.GLOBAL_DAILY_CALL_CAP)
    return {
        "date": datetime.date.today().isoformat(),
        "global_calls_today": global_calls_today,
        "global_daily_call_cap": config.GLOBAL_DAILY_CALL_CAP,
        "cap_reached": not allowed,
    }


@router.get("/personas", response_model=list[PersonaOut])
def list_personas():
    """The full curated registry -- the frontend's persona picker is built
    entirely from this, so there is never a UI path that lets a user type in
    a freeform persona name."""
    return [
        PersonaOut(key=p.key, name=p.name, avatar=p.avatar, color=p.color, description=p.description)
        for p in all_personas()
    ]


@router.post("/debate", response_model=DebateResponse)
def debate(payload: DebateRequest, request: Request, response: Response):
    # Deliberately a sync def: orchestrator.run_debate below is a blocking
    # call (its own ThreadPoolExecutor plus synchronous Gemini calls).
    # FastAPI runs sync route handlers in its own threadpool automatically,
    # which keeps that blocking work off the event loop.
    topic, persona_keys, user_name = _validate(payload)
    debate_id = _debate_id(topic, persona_keys, payload.include_moderator, user_name)
    logger.info(
        "[%s] /debate request: topic_len=%d personas=%s moderator=%s",
        debate_id[:8], len(topic), persona_keys, payload.include_moderator,
    )

    anon_id = identity.resolve_identity(request, response)
    _check_rate_limits(debate_id, anon_id)
    _check_topic_content(debate_id, topic)

    transcript = orchestrator.run_debate(debate_id, topic, persona_keys, payload.include_moderator, user_name)

    rate_limiter.record_user_usage(anon_id)
    rate_limiter.record_global_usage(_gemini_call_count(len(persona_keys), payload.include_moderator))

    logger.info("[%s] response: personas=%d", debate_id[:8], len(persona_keys))
    return _to_response(transcript)


@router.post("/debate/stream")
def debate_stream(payload: DebateRequest, request: Request):
    # Same validation/rate-limit rules as /debate, just delivered as
    # Server-Sent Events so each persona's statement (and each round) can
    # render the moment it's ready instead of the whole debate appearing at
    # once after a long silent wait.
    topic, persona_keys, user_name = _validate(payload)
    debate_id = _debate_id(topic, persona_keys, payload.include_moderator, user_name)
    logger.info(
        "[%s] /debate/stream request: topic_len=%d personas=%s moderator=%s",
        debate_id[:8], len(topic), persona_keys, payload.include_moderator,
    )

    anon_id = identity.resolve_id(request)
    _check_rate_limits(debate_id, anon_id)
    _check_topic_content(debate_id, topic)

    resp = StreamingResponse(
        _stream_and_record(debate_id, topic, persona_keys, payload.include_moderator, user_name, anon_id),
        media_type="text/event-stream",
    )
    identity.set_cookie(resp, anon_id)
    return resp


def _stream_and_record(
    debate_id: str, topic: str, persona_keys: list[str], include_moderator: bool, user_name: str, anon_id: str
):
    """Forwards each orchestrator event to the client as SSE, and once the
    final "done" event has been seen, performs the same rate-limit
    bookkeeping /debate does synchronously -- just triggered from consuming
    the last event instead of a return value (same pattern as is-it-true's
    /check/stream)."""
    for event in orchestrator.stream_debate_events(debate_id, topic, persona_keys, include_moderator, user_name):
        yield _sse_line(event)

        if event["event"] == "done":
            rate_limiter.record_user_usage(anon_id)
            rate_limiter.record_global_usage(_gemini_call_count(len(persona_keys), include_moderator))


def _sse_line(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


def _validate(payload: DebateRequest) -> tuple[str, list[str], str]:
    """Input validation, including the hard safety guardrail: only curated
    registry keys are accepted as personas -- any freeform/unknown key is
    rejected outright, before any Gemini call is made."""
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(400, "Please enter a topic to debate.")
    if len(topic) > config.MAX_TOPIC_CHARS:
        raise HTTPException(400, f"That's too long -- please keep the topic under {config.MAX_TOPIC_CHARS} characters.")

    persona_keys = payload.personas
    if len(persona_keys) != len(set(persona_keys)):
        raise HTTPException(400, "Please select each persona only once.")
    if not (config.MIN_PERSONAS <= len(persona_keys) <= config.MAX_PERSONAS):
        raise HTTPException(
            400, f"Please select between {config.MIN_PERSONAS} and {config.MAX_PERSONAS} personas."
        )
    unknown = [key for key in persona_keys if not is_valid_persona_key(key)]
    if unknown:
        # This is the hard requirement from REQUIREMENTS.md's Non-goals:
        # no freeform custom persona creation. Reject, don't silently drop.
        raise HTTPException(400, f"Unknown persona key(s): {', '.join(unknown)}. Choose from the curated list only.")

    user_name = payload.user_name.strip().replace("\n", " ")[: config.MAX_NAME_CHARS]

    return topic, persona_keys, user_name


def _check_rate_limits(debate_id: str, anon_id: str) -> None:
    allowed_user, user_count = rate_limiter.check_user_cap(anon_id, config.DAILY_USER_CAP)
    if not allowed_user:
        logger.warning("[%s] rejected: user cap hit (user=%s, count=%d)", debate_id[:8], anon_id[:8], user_count)
        raise HTTPException(429, "You've used your free debates for today -- come back tomorrow.")

    allowed_global, global_count = rate_limiter.check_global_cap(config.GLOBAL_DAILY_CALL_CAP)
    if not allowed_global:
        logger.warning("[%s] rejected: global cap hit (count=%d)", debate_id[:8], global_count)
        raise HTTPException(503, "This service hit today's usage limit -- please try again tomorrow.")


def _check_topic_content(debate_id: str, topic: str) -> None:
    """One extra Gemini call, made on every request (there's no cache to
    skip it on -- see below): rejects gibberish/non-topics and topics that
    depend on current/recent/future real-world facts an AI persona can't
    reliably know (see debate/topic_validator.py). Counted against the
    global cap regardless of outcome, since it's a real API call either way."""
    validation = topic_validator.validate_topic(topic)
    rate_limiter.record_global_usage(1)
    if not validation.is_valid:
        logger.info("[%s] rejected by topic validator: category=%s", debate_id[:8], validation.category)
        raise HTTPException(400, validation.message)


def _gemini_call_count(num_personas: int, include_moderator: bool) -> int:
    # 2 rounds (opening + rebuttal), one call per persona per round, plus
    # one optional moderator call.
    calls = num_personas * 2
    if include_moderator:
        calls += 1
    return calls


def _debate_id(topic: str, persona_keys: list[str], include_moderator: bool, user_name: str) -> str:
    # A per-request correlation id used only for log-line grouping now --
    # there is no debate cache (deliberately: two people rarely type the
    # exact same free-text topic, and a personalized name baked into every
    # statement would make a stale cache hit actively wrong for anyone
    # else). Sorted persona keys just keep the id stable regardless of
    # selection order.
    fingerprint = f"{topic}|{','.join(sorted(persona_keys))}|{include_moderator}|{user_name}"
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def _to_response(transcript: DebateTranscript) -> DebateResponse:
    personas_out = []
    for key in transcript.persona_keys:
        persona = get_persona(key)
        personas_out.append(PersonaOut(key=persona.key, name=persona.name, avatar=persona.avatar, color=persona.color, description=persona.description))

    return DebateResponse(
        topic=transcript.topic,
        personas=personas_out,
        rounds=[
            [PersonaStatementOut(**statement.model_dump()) for statement in round_statements]
            for round_statements in transcript.rounds
        ],
        moderator_summary=transcript.moderator_summary,
        winner_persona_key=transcript.winner_persona_key,
        winner_reason=transcript.winner_reason,
    )
