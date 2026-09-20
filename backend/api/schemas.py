from pydantic import BaseModel


class DebateRequest(BaseModel):
    topic: str
    personas: list[str]  # curated registry keys only -- see personas/registry.py
    include_moderator: bool = True
    # Optional -- personalizes every persona's display name (e.g. "The
    # Pragmatist Tom"). Blank is fine and falls back to the plain archetype
    # name.
    user_name: str = ""


class PersonaOut(BaseModel):
    key: str
    name: str
    avatar: str
    color: str
    description: str


class PersonaStatementOut(BaseModel):
    persona_key: str
    persona_name: str
    round: int
    text: str


class DebateResponse(BaseModel):
    topic: str
    personas: list[PersonaOut]
    rounds: list[list[PersonaStatementOut]]
    moderator_summary: str | None
    winner_persona_key: str | None
    winner_reason: str | None
