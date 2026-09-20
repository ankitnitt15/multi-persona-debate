from unittest.mock import MagicMock, patch

from debate import topic_validator
from debate.topic_validator import TopicValidation


def _fake_response(model):
    response = MagicMock()
    response.parsed = model
    return response


def test_valid_topic_passes_through():
    with patch.object(
        topic_validator,
        "generate_content",
        return_value=_fake_response(TopicValidation(is_valid=True, category="ok", message="")),
    ):
        result = topic_validator.validate_topic("should we get a dog")

    assert result.is_valid is True
    assert result.category == "ok"


def test_gibberish_topic_is_rejected():
    with patch.object(
        topic_validator,
        "generate_content",
        return_value=_fake_response(
            TopicValidation(is_valid=False, category="not_a_topic", message="That doesn't look like a debatable topic.")
        ),
    ):
        result = topic_validator.validate_topic("asdkjfhaskdjfh")

    assert result.is_valid is False
    assert result.category == "not_a_topic"
    assert result.message


def test_opinion_topic_about_a_real_person_or_current_decision_passes_through():
    """Regression guard: an earlier version also rejected anything that
    looked time-sensitive, which blocked perfectly good opinion topics like
    "is [a real politician] a good leader" or "should I buy an iPhone on my
    current salary". That category was removed -- this app is for opinions,
    not fact-checking, so topics like these must be accepted."""
    with patch.object(
        topic_validator,
        "generate_content",
        return_value=_fake_response(TopicValidation(is_valid=True, category="ok", message="")),
    ):
        result = topic_validator.validate_topic("should I buy an iPhone on my current salary")

    assert result.is_valid is True
    assert result.category == "ok"
