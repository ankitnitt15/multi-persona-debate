from pydantic import BaseModel


class PersonaStatement(BaseModel):
    persona_key: str
    persona_name: str
    round: int  # 1 = opening stance, 2 = rebuttal
    text: str


class DebateTranscript(BaseModel):
    debate_id: str
    topic: str
    persona_keys: list[str]
    rounds: list[list[PersonaStatement]]  # rounds[0] = round 1, rounds[1] = round 2
    moderator_summary: str | None = None
    # Only set when a moderator ran: the moderator's declared winner. Kept
    # separate from moderator_summary so the frontend can style the "who
    # won" call-out distinctly from the neutral recap.
    winner_persona_key: str | None = None
    winner_reason: str | None = None


# Structured-output wrappers for Gemini's response_schema -- keeps every
# persona/moderator call schema-based instead of hand-parsing JSON, per this
# repo's CLAUDE.md ("avoid manual JSON parsing if the SDK supports it").
class PersonaResponse(BaseModel):
    statement: str


class ModeratorResponse(BaseModel):
    summary: str
    # Free-text key -- the prompt hands the model the exact roster of valid
    # keys and instructs it to echo one back verbatim, but a model can
    # still misfire, so orchestrator.py validates this against the actual
    # persona_keys before trusting it (see _generate_moderator_summary).
    winner_persona_key: str
    winner_reason: str
