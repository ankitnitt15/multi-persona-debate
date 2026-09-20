from personas.registry import PERSONA_REGISTRY, all_personas, get_persona, is_valid_persona_key


def test_registry_has_between_six_and_eight_personas():
    assert 6 <= len(PERSONA_REGISTRY) <= 8


def test_every_persona_has_required_fields():
    for persona in all_personas():
        assert persona.key
        assert persona.name
        assert persona.avatar
        assert persona.color.startswith("#")
        assert persona.description
        assert persona.voice_style


def test_get_persona_returns_known_key():
    persona = get_persona("grandma")
    assert persona is not None
    assert persona.name == "Grandma"


def test_get_persona_returns_none_for_unknown_key():
    assert get_persona("elon_musk") is None
    assert get_persona("") is None


def test_is_valid_persona_key():
    assert is_valid_persona_key("pragmatist") is True
    assert is_valid_persona_key("some_freeform_name") is False
