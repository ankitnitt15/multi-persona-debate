from unittest.mock import MagicMock, patch

from debate import orchestrator
from debate.models import ModeratorResponse, PersonaResponse


def _fake_response(model):
    response = MagicMock()
    response.parsed = model
    return response


def _fake_moderator(summary="a neutral wrap-up", winner_persona_key="pragmatist", winner_reason="clearest logic"):
    return _fake_response(ModeratorResponse(summary=summary, winner_persona_key=winner_persona_key, winner_reason=winner_reason))


def test_round_1_calls_one_opening_per_persona():
    with patch.object(
        orchestrator, "generate_content", return_value=_fake_response(PersonaResponse(statement="an opening"))
    ) as mock_generate:
        transcript = orchestrator.run_debate(
            "d1", "should we get a dog", ["pragmatist", "optimist"], include_moderator=False
        )

    # 2 personas x 2 rounds (moderator off) = 4 calls
    assert mock_generate.call_count == 4
    assert len(transcript.rounds[0]) == 2
    assert {s.persona_key for s in transcript.rounds[0]} == {"pragmatist", "optimist"}
    assert all(s.round == 1 for s in transcript.rounds[0])


def test_round_2_prompt_includes_round_1_statements_as_context():
    responses = iter(
        [
            _fake_response(PersonaResponse(statement="pragmatist opening")),
            _fake_response(PersonaResponse(statement="optimist opening")),
            _fake_response(PersonaResponse(statement="pragmatist rebuttal")),
            _fake_response(PersonaResponse(statement="optimist rebuttal")),
        ]
    )
    captured_contents = []

    def _record_and_return(*args, **kwargs):
        captured_contents.append(kwargs["contents"][0])
        return next(responses)

    with patch.object(orchestrator, "generate_content", side_effect=_record_and_return):
        orchestrator.run_debate("d1", "should we get a dog", ["pragmatist", "optimist"], include_moderator=False)

    # The two round-2 (rebuttal) prompts are the last two captured -- each
    # must reference both personas' round-1 statements verbatim, proving the
    # rebuttal call actually received the full round-1 context (not just a
    # generic "rebut someone" prompt).
    rebuttal_prompts = captured_contents[2:]
    for prompt in rebuttal_prompts:
        assert "pragmatist opening" in prompt
        assert "optimist opening" in prompt


def test_moderator_summary_and_winner_included_only_when_requested():
    with patch.object(
        orchestrator, "generate_content", return_value=_fake_response(PersonaResponse(statement="stance"))
    ):
        transcript_without = orchestrator.run_debate(
            "d1", "topic", ["pragmatist", "optimist"], include_moderator=False
        )
    assert transcript_without.moderator_summary is None
    assert transcript_without.winner_persona_key is None

    def _dispatch(*args, **kwargs):
        schema = kwargs["config"]["response_schema"]
        if schema is ModeratorResponse:
            return _fake_moderator()
        return _fake_response(PersonaResponse(statement="stance"))

    with patch.object(orchestrator, "generate_content", side_effect=_dispatch):
        transcript_with = orchestrator.run_debate("d2", "topic", ["pragmatist", "optimist"], include_moderator=True)

    assert transcript_with.moderator_summary == "a neutral wrap-up"
    assert transcript_with.winner_persona_key == "pragmatist"
    assert transcript_with.winner_reason == "clearest logic"


def test_moderator_hallucinated_winner_key_falls_back_to_none():
    """The prompt hands the model the exact roster, but nothing stops it
    from returning a string that isn't actually one of the persona keys --
    that must not leak into the transcript as a winner the frontend can't
    resolve."""

    def _dispatch(*args, **kwargs):
        schema = kwargs["config"]["response_schema"]
        if schema is ModeratorResponse:
            return _fake_moderator(winner_persona_key="elon_musk", winner_reason="made up")
        return _fake_response(PersonaResponse(statement="stance"))

    with patch.object(orchestrator, "generate_content", side_effect=_dispatch):
        transcript = orchestrator.run_debate("d1", "topic", ["pragmatist", "optimist"], include_moderator=True)

    assert transcript.winner_persona_key is None
    assert transcript.winner_reason is None
    # The neutral summary should still survive even when the winner call is discarded.
    assert transcript.moderator_summary == "a neutral wrap-up"


def test_user_name_personalizes_every_persona_display_name():
    captured_contents = []

    def _record_and_return(*args, **kwargs):
        captured_contents.append(kwargs["contents"][0])
        return _fake_response(PersonaResponse(statement="stance"))

    with patch.object(orchestrator, "generate_content", side_effect=_record_and_return):
        transcript = orchestrator.run_debate(
            "d1", "topic", ["pragmatist", "optimist"], include_moderator=False, user_name="Tom"
        )

    assert {s.persona_name for s in transcript.rounds[0]} == {"The Pragmatist Tom", "The Optimist Tom"}
    # The prompt itself should also address the persona by its personalized name.
    assert any('"The Pragmatist Tom"' in prompt for prompt in captured_contents)


def test_blank_user_name_keeps_plain_persona_names():
    with patch.object(
        orchestrator, "generate_content", return_value=_fake_response(PersonaResponse(statement="stance"))
    ):
        transcript = orchestrator.run_debate(
            "d1", "topic", ["pragmatist", "optimist"], include_moderator=False, user_name=""
        )

    assert {s.persona_name for s in transcript.rounds[0]} == {"The Pragmatist", "The Optimist"}


def test_stream_debate_events_emits_round_starts_statements_and_done():
    with patch.object(
        orchestrator, "generate_content", return_value=_fake_response(PersonaResponse(statement="stance"))
    ):
        events = list(
            orchestrator.stream_debate_events("d1", "topic", ["pragmatist", "optimist"], include_moderator=False)
        )

    kinds = [e["event"] for e in events]
    # round_start(1), 2x statement(round=1), round_start(2), 2x statement(round=2), done
    assert kinds == ["round_start", "statement", "statement", "round_start", "statement", "statement", "done"]
    assert kinds.count("statement") == 4
    round_1_events = [e for e in events if e["event"] == "statement" and e["round"] == 1]
    assert {e["persona_key"] for e in round_1_events} == {"pragmatist", "optimist"}

    done_event = events[-1]
    assert done_event["moderator_summary"] is None
    assert len(done_event["rounds"]) == 2
    assert [s["persona_key"] for s in done_event["rounds"][0]] == ["pragmatist", "optimist"]


def test_stream_debate_events_includes_moderator_and_winner_when_requested():
    def _dispatch(*args, **kwargs):
        schema = kwargs["config"]["response_schema"]
        if schema is ModeratorResponse:
            return _fake_moderator()
        return _fake_response(PersonaResponse(statement="stance"))

    with patch.object(orchestrator, "generate_content", side_effect=_dispatch):
        events = list(
            orchestrator.stream_debate_events("d1", "topic", ["pragmatist", "optimist"], include_moderator=True)
        )

    kinds = [e["event"] for e in events]
    assert "moderator_start" in kinds
    assert "moderator" in kinds
    moderator_event = next(e for e in events if e["event"] == "moderator")
    assert moderator_event["summary"] == "a neutral wrap-up"
    assert moderator_event["winner_persona_key"] == "pragmatist"
    assert moderator_event["winner_reason"] == "clearest logic"
    assert events[-1]["moderator_summary"] == "a neutral wrap-up"
    assert events[-1]["winner_persona_key"] == "pragmatist"


def test_statement_order_matches_requested_persona_order():
    with patch.object(
        orchestrator, "generate_content", return_value=_fake_response(PersonaResponse(statement="stance"))
    ):
        transcript = orchestrator.run_debate(
            "d1", "topic", ["skeptic", "grandma", "finance_bro"], include_moderator=False
        )

    assert [s.persona_key for s in transcript.rounds[0]] == ["skeptic", "grandma", "finance_bro"]
    assert [s.persona_key for s in transcript.rounds[1]] == ["skeptic", "grandma", "finance_bro"]
