import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import config
from api.routes import _debate_id
from debate import orchestrator, topic_validator
from debate.models import DebateTranscript, PersonaStatement
from debate.topic_validator import TopicValidation
from limits import rate_limiter
from main import app

client = TestClient(app)

_VALID_TOPIC = TopicValidation(is_valid=True, category="ok", message="")


def _valid_topic_patch():
    return patch.object(topic_validator, "validate_topic", return_value=_VALID_TOPIC)


def _make_transcript(
    debate_id,
    topic="should we get a dog",
    personas=("pragmatist", "optimist"),
    moderator=True,
    winner_persona_key=None,
    winner_reason=None,
):
    persona_names = {"pragmatist": "The Pragmatist", "optimist": "The Optimist", "skeptic": "The Skeptic"}
    round_1 = [PersonaStatement(persona_key=k, persona_name=persona_names[k], round=1, text=f"{k} opening") for k in personas]
    round_2 = [PersonaStatement(persona_key=k, persona_name=persona_names[k], round=2, text=f"{k} rebuttal") for k in personas]
    return DebateTranscript(
        debate_id=debate_id,
        topic=topic,
        persona_keys=list(personas),
        rounds=[round_1, round_2],
        moderator_summary="a neutral wrap-up" if moderator else None,
        winner_persona_key=winner_persona_key,
        winner_reason=winner_reason,
    )


def test_health():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_personas_returns_curated_registry_only():
    response = client.get("/api/personas")

    assert response.status_code == 200
    keys = {p["key"] for p in response.json()}
    assert "pragmatist" in keys
    assert len(keys) >= 6


def test_debate_rejects_unknown_persona_key():
    """The hard safety requirement: a freeform/unknown persona name must be
    rejected, never silently accepted or passed through to Gemini."""
    with patch.object(orchestrator, "run_debate") as mock_run:
        response = client.post(
            "/api/debate",
            json={"topic": "should we get a dog", "personas": ["pragmatist", "elon_musk"]},
        )

    assert response.status_code == 400
    assert "Unknown persona" in response.json()["detail"]
    mock_run.assert_not_called()


def test_debate_rejects_fewer_than_two_personas():
    response = client.post("/api/debate", json={"topic": "should we get a dog", "personas": ["pragmatist"]})

    assert response.status_code == 400


def test_debate_rejects_more_than_four_personas():
    response = client.post(
        "/api/debate",
        json={
            "topic": "should we get a dog",
            "personas": ["pragmatist", "optimist", "skeptic", "grandma", "finance_bro"],
        },
    )

    assert response.status_code == 400


def test_debate_rejects_duplicate_personas():
    response = client.post(
        "/api/debate", json={"topic": "should we get a dog", "personas": ["pragmatist", "pragmatist"]}
    )

    assert response.status_code == 400


def test_debate_rejects_empty_topic():
    response = client.post("/api/debate", json={"topic": "  ", "personas": ["pragmatist", "optimist"]})

    assert response.status_code == 400


def test_debate_rejects_overlong_topic():
    response = client.post(
        "/api/debate",
        json={"topic": "x" * (config.MAX_TOPIC_CHARS + 1), "personas": ["pragmatist", "optimist"]},
    )

    assert response.status_code == 400


def test_debate_rejects_gibberish_topic_before_calling_orchestrator():
    """The topic-content gate (debate/topic_validator.py) runs before the
    orchestrator on every request -- there's no cache to skip it. A
    not-a-topic verdict must block the debate entirely."""
    rejection = TopicValidation(is_valid=False, category="not_a_topic", message="That's not a debatable topic.")
    with patch.object(topic_validator, "validate_topic", return_value=rejection), patch.object(
        orchestrator, "run_debate"
    ) as mock_run:
        response = client.post(
            "/api/debate", json={"topic": "asdkjfhaskdjfh", "personas": ["pragmatist", "optimist"]}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "That's not a debatable topic."
    mock_run.assert_not_called()


def test_debate_returns_pipeline_result_with_winner():
    debate_id = _debate_id("should we get a dog", ["optimist", "pragmatist"], True, "")
    transcript = _make_transcript(debate_id, winner_persona_key="pragmatist", winner_reason="best logic")
    with _valid_topic_patch(), patch.object(orchestrator, "run_debate", return_value=transcript) as mock_run:
        response = client.post(
            "/api/debate",
            json={"topic": "should we get a dog", "personas": ["pragmatist", "optimist"]},
        )

    mock_run.assert_called_once()
    assert response.status_code == 200
    body = response.json()
    assert len(body["rounds"]) == 2
    assert body["moderator_summary"] == "a neutral wrap-up"
    assert body["winner_persona_key"] == "pragmatist"
    assert body["winner_reason"] == "best logic"
    assert {p["key"] for p in body["personas"]} == {"pragmatist", "optimist"}


def test_debate_passes_user_name_through_to_orchestrator():
    with _valid_topic_patch(), patch.object(
        orchestrator, "run_debate", return_value=_make_transcript("d1")
    ) as mock_run:
        client.post(
            "/api/debate",
            json={"topic": "should we get a dog", "personas": ["pragmatist", "optimist"], "user_name": "Tom"},
        )

    mock_run.assert_called_once()
    assert mock_run.call_args.args[-1] == "Tom"


def test_debate_rejected_by_user_cap_never_calls_orchestrator():
    with patch.object(rate_limiter, "check_user_cap", return_value=(False, 99)), patch.object(
        orchestrator, "run_debate"
    ) as mock_run:
        response = client.post(
            "/api/debate", json={"topic": "a distinct topic", "personas": ["pragmatist", "optimist"]}
        )

    mock_run.assert_not_called()
    assert response.status_code == 429


def test_debate_rejected_by_global_cap_never_calls_orchestrator():
    with patch.object(rate_limiter, "check_global_cap", return_value=(False, 99)), patch.object(
        orchestrator, "run_debate"
    ) as mock_run:
        response = client.post(
            "/api/debate", json={"topic": "another distinct topic", "personas": ["pragmatist", "optimist"]}
        )

    mock_run.assert_not_called()
    assert response.status_code == 503


def _parse_sse_events(raw_body: str) -> list[dict]:
    events = []
    for chunk in raw_body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        line = next((l for l in chunk.splitlines() if l.startswith("data:")), None)
        if line:
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def test_debate_stream_rejects_unknown_persona_key_before_streaming():
    with patch.object(orchestrator, "stream_debate_events") as mock_stream:
        response = client.post(
            "/api/debate/stream",
            json={"topic": "should we get a dog", "personas": ["pragmatist", "elon_musk"]},
        )

    assert response.status_code == 400
    mock_stream.assert_not_called()


def test_debate_stream_rejects_invalid_topic_content_before_streaming():
    rejection = TopicValidation(is_valid=False, category="not_a_topic", message="Not a real topic.")
    with patch.object(topic_validator, "validate_topic", return_value=rejection), patch.object(
        orchestrator, "stream_debate_events"
    ) as mock_stream:
        response = client.post(
            "/api/debate/stream", json={"topic": "asdkjfhaskdjfh", "personas": ["pragmatist", "optimist"]}
        )

    assert response.status_code == 400
    mock_stream.assert_not_called()


def test_debate_stream_emits_statement_and_done_events():
    def _fake_stream(debate_id, topic, persona_keys, include_moderator, user_name):
        yield {"event": "round_start", "round": 1, "label": "Opening Statements"}
        yield {"event": "statement", "round": 1, "persona_key": "pragmatist", "persona_name": "The Pragmatist", "text": "opening"}
        yield {"event": "statement", "round": 1, "persona_key": "optimist", "persona_name": "The Optimist", "text": "opening"}
        yield {"event": "round_start", "round": 2, "label": "Rebuttals"}
        yield {"event": "statement", "round": 2, "persona_key": "pragmatist", "persona_name": "The Pragmatist", "text": "rebuttal"}
        yield {"event": "statement", "round": 2, "persona_key": "optimist", "persona_name": "The Optimist", "text": "rebuttal"}
        yield {
            "event": "done",
            "topic": topic,
            "persona_keys": persona_keys,
            "rounds": [
                [{"persona_key": "pragmatist", "persona_name": "The Pragmatist", "round": 1, "text": "opening"},
                 {"persona_key": "optimist", "persona_name": "The Optimist", "round": 1, "text": "opening"}],
                [{"persona_key": "pragmatist", "persona_name": "The Pragmatist", "round": 2, "text": "rebuttal"},
                 {"persona_key": "optimist", "persona_name": "The Optimist", "round": 2, "text": "rebuttal"}],
            ],
            "moderator_summary": None,
            "winner_persona_key": None,
            "winner_reason": None,
        }

    with _valid_topic_patch(), patch.object(orchestrator, "stream_debate_events", side_effect=_fake_stream):
        response = client.post(
            "/api/debate/stream",
            json={"topic": "a fresh streaming topic", "personas": ["pragmatist", "optimist"], "include_moderator": False},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(response.text)
    assert [e["event"] for e in events] == [
        "round_start", "statement", "statement", "round_start", "statement", "statement", "done",
    ]


def test_admin_stats_is_404_when_no_token_configured():
    with patch.object(config, "ADMIN_TOKEN", ""):
        response = client.get("/api/admin/stats", headers={"x-admin-token": "anything"})

    assert response.status_code == 404


def test_admin_stats_rejects_wrong_token():
    with patch.object(config, "ADMIN_TOKEN", "correct-secret"):
        response = client.get("/api/admin/stats", headers={"x-admin-token": "wrong-secret"})

    assert response.status_code == 404


def test_admin_stats_returns_usage_with_correct_token():
    with patch.object(config, "ADMIN_TOKEN", "correct-secret"), patch.object(config, "GLOBAL_DAILY_CALL_CAP", 10):
        rate_limiter.record_global_usage(3)
        response = client.get("/api/admin/stats", headers={"x-admin-token": "correct-secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["global_calls_today"] == 3
    assert body["global_daily_call_cap"] == 10
    assert body["cap_reached"] is False
