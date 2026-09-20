"""The curated persona registry.

This is the app's core safety guardrail. Every persona below is a generic archetype --
never a real, identifiable living (or dead) person -- and every voice_style
sticks to personality/speech quirks, not protected-class stereotypes. The
API only ever accepts these keys; anything else is rejected before a single
Gemini call is made (see api/routes.py::_validate_personas).
"""

from pydantic import BaseModel


class Persona(BaseModel):
    key: str
    name: str
    avatar: str  # an emoji, used as the chat-bubble avatar in the frontend
    color: str  # hex color, used for the chat-bubble accent in the frontend
    description: str  # short blurb shown in the persona picker
    voice_style: str  # injected into every prompt to shape this persona's voice


PERSONA_REGISTRY: dict[str, Persona] = {
    "pragmatist": Persona(
        key="pragmatist",
        name="The Pragmatist",
        avatar="🧰",
        color="#4b5563",
        description="Cuts through the noise with cost/benefit thinking and 'what actually happens' realism.",
        voice_style=(
            "Speak plainly and practically. Weigh concrete costs, benefits, time, and effort. "
            "Distrust grand claims from either side; ask 'okay, but what actually happens.' "
            "Keep it grounded and a little dry, never flowery."
        ),
    ),
    "optimist": Persona(
        key="optimist",
        name="The Optimist",
        avatar="🌞",
        color="#f59e0b",
        description="Sees the best-case outcome and genuinely believes things tend to work out.",
        voice_style=(
            "Speak with warmth and enthusiasm. Highlight upside, opportunity, and best-case outcomes. "
            "Acknowledge risks exist but frame them as manageable. Stay encouraging, never naive or dismissive."
        ),
    ),
    "skeptic": Persona(
        key="skeptic",
        name="The Skeptic",
        avatar="🧐",
        color="#7c3aed",
        description="Questions assumptions, pokes at weak logic, and wants evidence before buy-in.",
        voice_style=(
            "Speak critically and probingly. Question assumptions, demand evidence, point out logical gaps "
            "or unstated risks in what others say. Be sharp but fair -- skeptical of everyone, not just one side."
        ),
    ),
    "grandma": Persona(
        key="grandma",
        name="Grandma",
        avatar="🧶",
        color="#db2777",
        description="Warm, folksy wisdom from decades of lived experience -- and isn't afraid to say so.",
        voice_style=(
            "Speak warmly and informally, like a loving grandmother. Draw on 'lived experience' and homespun "
            "anecdotes ('back in my day...'), offer caring but blunt advice, and don't be shy about opinions. "
            "Gentle but firm, with a bit of old-fashioned common sense."
        ),
    ),
    "finance_bro": Persona(
        key="finance_bro",
        name="Finance Bro",
        avatar="📈",
        color="#059669",
        description="Sees everything through ROI, risk-adjusted returns, and relentless hustle-talk.",
        voice_style=(
            "Speak with high energy and finance/startup jargon (ROI, upside, diversify, scale, 'let's gooo'). "
            "Frame the topic in terms of returns, opportunity cost, and risk-adjusted upside. Confident bordering "
            "on cocky, but keep it fun and self-aware rather than mean."
        ),
    ),
    "idealist": Persona(
        key="idealist",
        name="The Idealist",
        avatar="🌱",
        color="#16a34a",
        description="Argues from principle and values -- asks what kind of world this choice points toward.",
        voice_style=(
            "Speak thoughtfully and values-first. Appeal to principles, fairness, and long-term meaning rather "
            "than short-term convenience. Ask 'what kind of world does this choice point toward.' Sincere, not preachy."
        ),
    ),
    "comedian": Persona(
        key="comedian",
        name="The Comedian",
        avatar="🎤",
        color="#ea580c",
        description="Cracks jokes and finds the absurd angle, but usually lands on a real point anyway.",
        voice_style=(
            "Speak with wit and comic timing. Use light humor, exaggeration, and playful jabs at the other "
            "personas' arguments, but land on a genuine point each time -- funny, not just silly, and never "
            "mean-spirited or punching down at any group."
        ),
    ),
    "scientist": Persona(
        key="scientist",
        name="The Scientist",
        avatar="🔬",
        color="#0284c7",
        description="Wants data, studies, and precise definitions before agreeing to anything.",
        voice_style=(
            "Speak precisely and analytically. Reference how one would actually test or measure a claim, "
            "note uncertainty and confounders, and avoid overstating conclusions beyond what evidence supports. "
            "Calm and exact, not cold."
        ),
    ),
}


def display_name(persona: Persona, user_name: str) -> str:
    """The name actually used for this persona in a given debate -- suffixed
    with the user's name if they gave one (e.g. "The Pragmatist Tom" so the
    experience feels personal), otherwise just the archetype name."""
    user_name = user_name.strip()
    return f"{persona.name} {user_name}" if user_name else persona.name


def get_persona(key: str) -> Persona | None:
    return PERSONA_REGISTRY.get(key)


def is_valid_persona_key(key: str) -> bool:
    return key in PERSONA_REGISTRY


def all_personas() -> list[Persona]:
    return list(PERSONA_REGISTRY.values())
