import concurrent.futures

from common.gemini_client import generate_content
from debate.models import DebateTranscript, ModeratorResponse, PersonaResponse, PersonaStatement
from debate.prompts import build_moderator_prompt, build_opening_prompt, build_rebuttal_prompt
from personas.registry import Persona, display_name, get_persona
from shared.retry import call_with_backoff


class ModeratorResult:
    def __init__(self, summary: str, winner_persona_key: str | None, winner_reason: str | None):
        self.summary = summary
        self.winner_persona_key = winner_persona_key
        self.winner_reason = winner_reason


def run_debate(
    debate_id: str, topic: str, persona_keys: list[str], include_moderator: bool, user_name: str = ""
) -> DebateTranscript:
    """Runs the full debate: round 1 (opening stances, parallel), round 2
    (rebuttals, parallel -- but only after round 1 finishes, since every
    round-2 call needs the full set of round-1 statements as context), then
    an optional moderator wrap-up that also declares a winner. Personas
    within a round always run in parallel; rounds themselves run
    sequentially. `user_name`, if given, personalizes every persona's
    display name (e.g. "The Pragmatist Tom").
    """
    personas = [get_persona(key) for key in persona_keys]

    round_1 = _run_round_in_parallel(personas, lambda p: _generate_opening(p, topic, user_name))
    round_2 = _run_round_in_parallel(personas, lambda p: _generate_rebuttal(p, topic, round_1, user_name))

    moderator_summary = winner_persona_key = winner_reason = None
    if include_moderator:
        moderator = _generate_moderator_summary(topic, round_1, round_2, personas, user_name)
        moderator_summary, winner_persona_key, winner_reason = moderator.summary, moderator.winner_persona_key, moderator.winner_reason

    return DebateTranscript(
        debate_id=debate_id,
        topic=topic,
        persona_keys=persona_keys,
        rounds=[round_1, round_2],
        moderator_summary=moderator_summary,
        winner_persona_key=winner_persona_key,
        winner_reason=winner_reason,
    )


def _run_round_in_parallel(personas: list[Persona], call) -> list[PersonaStatement]:
    """Runs `call(persona)` for every persona in the round concurrently, but
    returns results in the original persona order (not completion order) so
    the transcript is deterministic regardless of which Gemini call happens
    to finish first.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(personas)) as executor:
        futures = [executor.submit(call, persona) for persona in personas]
        return [future.result() for future in futures]


def stream_debate_events(
    debate_id: str, topic: str, persona_keys: list[str], include_moderator: bool, user_name: str = ""
):
    """Generator version of run_debate for the SSE endpoint: yields a dict
    per event as it happens (round starts, each persona's statement as soon
    as *that* persona's call completes, moderator start/result, then one
    final "done" event carrying the complete transcript). Round 2 still only
    starts once round 1 has fully finished -- it needs every round-1
    statement as context -- but within a round, statements are yielded in
    completion order so the UI can show whoever answers first, first,
    instead of waiting for the whole round to land at once.
    """
    personas = [get_persona(key) for key in persona_keys]

    round_1 = yield from _run_round_streaming(
        personas, 1, "Opening Statements", lambda p: _generate_opening(p, topic, user_name)
    )
    round_2 = yield from _run_round_streaming(
        personas, 2, "Rebuttals", lambda p: _generate_rebuttal(p, topic, round_1, user_name)
    )

    moderator_summary = winner_persona_key = winner_reason = None
    if include_moderator:
        yield {"event": "moderator_start"}
        moderator = _generate_moderator_summary(topic, round_1, round_2, personas, user_name)
        moderator_summary, winner_persona_key, winner_reason = moderator.summary, moderator.winner_persona_key, moderator.winner_reason
        yield {
            "event": "moderator",
            "summary": moderator_summary,
            "winner_persona_key": winner_persona_key,
            "winner_reason": winner_reason,
        }

    yield {
        "event": "done",
        "topic": topic,
        "persona_keys": persona_keys,
        "rounds": [[s.model_dump() for s in round_1], [s.model_dump() for s in round_2]],
        "moderator_summary": moderator_summary,
        "winner_persona_key": winner_persona_key,
        "winner_reason": winner_reason,
    }


def _run_round_streaming(personas: list[Persona], round_num: int, label: str, call):
    """Yields a "round_start" event, then one "statement" event per persona
    in whatever order their Gemini call actually completes, then returns
    (via `yield from`'s StopIteration value) the results back in the
    original persona order -- callers need that fixed order to build the
    next round's context and the final transcript deterministically."""
    yield {"event": "round_start", "round": round_num, "label": label}

    results_by_key: dict[str, PersonaStatement] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(personas)) as executor:
        future_to_persona = {executor.submit(call, persona): persona for persona in personas}
        for future in concurrent.futures.as_completed(future_to_persona):
            persona = future_to_persona[future]
            statement = future.result()
            results_by_key[persona.key] = statement
            yield {
                "event": "statement",
                "round": round_num,
                "persona_key": statement.persona_key,
                "persona_name": statement.persona_name,
                "text": statement.text,
            }

    return [results_by_key[persona.key] for persona in personas]


def _generate_opening(persona: Persona, topic: str, user_name: str) -> PersonaStatement:
    prompt = build_opening_prompt(persona, topic, user_name)
    response = call_with_backoff(
        generate_content,
        contents=[prompt],
        config={"response_mime_type": "application/json", "response_schema": PersonaResponse},
    )
    parsed: PersonaResponse = response.parsed
    return PersonaStatement(
        persona_key=persona.key, persona_name=display_name(persona, user_name), round=1, text=parsed.statement
    )


def _generate_rebuttal(
    persona: Persona, topic: str, round_1_statements: list[PersonaStatement], user_name: str
) -> PersonaStatement:
    prompt = build_rebuttal_prompt(persona, topic, round_1_statements, user_name)
    response = call_with_backoff(
        generate_content,
        contents=[prompt],
        config={"response_mime_type": "application/json", "response_schema": PersonaResponse},
    )
    parsed: PersonaResponse = response.parsed
    return PersonaStatement(
        persona_key=persona.key, persona_name=display_name(persona, user_name), round=2, text=parsed.statement
    )


def _generate_moderator_summary(
    topic: str,
    round_1_statements: list[PersonaStatement],
    round_2_statements: list[PersonaStatement],
    personas: list[Persona],
    user_name: str,
) -> ModeratorResult:
    prompt = build_moderator_prompt(topic, round_1_statements, round_2_statements, personas, user_name)
    response = call_with_backoff(
        generate_content,
        contents=[prompt],
        config={"response_mime_type": "application/json", "response_schema": ModeratorResponse},
    )
    parsed: ModeratorResponse = response.parsed

    # The prompt hands the model the exact roster and tells it to echo a
    # key back verbatim, but nothing stops it from hallucinating a
    # different string -- if that happens, drop the (unusable) winner
    # rather than surface a winner_persona_key the frontend can't resolve
    # to any persona it knows about.
    valid_keys = {p.key for p in personas}
    if parsed.winner_persona_key not in valid_keys:
        return ModeratorResult(parsed.summary, None, None)
    return ModeratorResult(parsed.summary, parsed.winner_persona_key, parsed.winner_reason)
