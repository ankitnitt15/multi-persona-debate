# Multi-Persona Debate

Give it a topic, pick 2-4 curated personas, and watch them argue it out over
two rounds plus an optional neutral moderator wrap-up. Entertainment only app no accounts, no persisted history.


## How it works

1. `GET /api/personas` returns the curated persona list (name, avatar, color,
   description) -- this is the *only* source of persona choices the frontend
   ever shows.
2. User enters their name, a topic, and picks 2-4 personas, `POST /api/debate`.
3. **Topic content check:** before anything else, `debate/topic_validator.py`
   makes one Gemini call to reject two kinds of bad topics: gibberish/
   non-topics, and topics that hinge on current/recent/future real-world
   facts (elections, "right now" prices, tomorrow's weather) that an AI
   persona has no reliable way to know and might confidently get wrong. This
   runs on every request -- there's no cache to skip it on (see below).
4. **Round 1 (opening stances):** every selected persona gets a call in
   parallel, each producing a 2-4 sentence opening stance on the topic in its
   own voice -- personalized with the user's name if given (e.g. "The
   Pragmatist Tom").
5. **Round 2 (rebuttals):** after round 1 finishes, every persona gets a
   second call in parallel -- but this time the prompt includes the *full
   set* of round-1 statements from every persona (including its own), so
   rebuttals actually engage with what was said rather than being generic.
6. **Optional moderator + winner:** if requested, one more call to a
   moderator persona, given the entire round 1 + round 2 transcript, writes a
   short neutral wrap-up *and* declares exactly one winner -- the persona who
   made the strongest case -- with a short reason. No ties, no declining to
   choose (see "Personas" below for the guardrail against a hallucinated
   winner key).
7. The frontend calls `POST /api/debate/stream`, which delivers the whole
   thing as Server-Sent Events instead of one blocking JSON response --
   `round_start`, then one `statement` event per persona the moment *that*
   persona's own call finishes (not the whole round at once), then
   `moderator_start`/`moderator` (carrying the winner), then a final `done`
   event carrying the complete transcript. A plain `POST /api/debate` also
   still exists and returns the same result as one JSON blob, for any caller
   that doesn't want SSE.
8. Each statement is revealed on-screen with a typewriter effect as its
   text arrives, so a persona's bubble visibly "speaks itself" onto the
   stage rather than popping in fully-formed.

**No debate cache.** Earlier versions cached identical (topic, personas,
moderator) requests for an hour, but that's not a real use case here: two
people essentially never type the exact same free-text topic, and a
personalized name baked into every statement would make a stale cache hit
actively *wrong* for anyone else re-running the same topic under a different
name. Every request runs the full pipeline live.

Everything is built with Pydantic models end-to-end (`debate/models.py`,
`api/schemas.py`) and Gemini structured output (`response_schema=...`) 

## Safety guardrail

There is **no freeform persona input anywhere in the API.** `POST /api/debate`
takes a list of persona *keys*; `api/routes.py::_validate` rejects the whole
request with `400` if any key isn't in the curated registry
(`personas/registry.py`). The frontend
never renders a free-text field for a persona name either -- its picker is
built entirely from `GET /api/personas`. This is covered by
`tests/test_routes.py::test_debate_rejects_unknown_persona_key`.

Every persona is a generic archetype, never a real, identifiable person, and
every prompt (`debate/prompts.py`) carries an explicit instruction to avoid
protected-class stereotypes and to treat the user-submitted topic as data,
never as instructions to the model

## Personas


| Key | Name | Voice |
|---|---|---|
| `pragmatist` | The Pragmatist | Cost/benefit realism, distrusts grand claims from anyone |
| `optimist` | The Optimist | Best-case framing, genuinely hopeful, not naive |
| `skeptic` | The Skeptic | Questions assumptions, demands evidence, pokes at logic gaps |
| `grandma` | Grandma | Warm, folksy, blunt lived-experience wisdom |
| `finance_bro` | Finance Bro | ROI/upside framing, high-energy startup jargon |
| `idealist` | The Idealist | Values- and principle-first, "what world does this point toward" |
| `comedian` | The Comedian | Wit and playful jabs that still land a real point |
| `scientist` | The Scientist | Wants data/evidence, precise about uncertainty |


**Number of rounds: 2 (opening + rebuttal), plus an optional 3rd "round"
that is the moderator's wrap-up + winner declaration (on by default).**
Rationale: round 2 rebuttals already require each persona to have seen
everyone else's opening statement, which is where the real "debate" value
comes from; a 3rd persona-vs-persona round (re-rebuttals) mostly repeats the
same dynamic at higher cost/latency for limited extra entertainment value,
so it was left out. The moderator step is a single extra call that gives a
satisfying sense of closure -- and, per user feedback, a genuine winner
instead of a deliberately-neutral non-verdict -- so it defaults to on but is
a per-request toggle (`include_moderator`, exposed as a checkbox in the UI).

**Declaring a winner.** The moderator prompt (`debate/prompts.py::build_moderator_prompt`)
is handed the exact persona roster (key + display name) and instructed to
pick exactly one winner and explain why in 1-2 sentences -- no ties, no
declining to choose. Since the model echoes a key back rather than us
parsing free text, `orchestrator.py::_generate_moderator_summary` validates
that key against the actual persona list and silently drops the winner
(falls back to no banner, keeps the neutral summary) if the model ever
returns something that doesn't match -- covered by
`tests/test_orchestrator.py::test_moderator_hallucinated_winner_key_falls_back_to_none`.

**Personalized names.** An optional `user_name` on the request suffixes
every persona's display name for that debate (e.g. "The Pragmatist Tom",
"The Comedian Tom") -- computed once in `personas/registry.py::display_name`
and used consistently in every prompt, every rendered statement, and the
moderator's roster/winner. Blank name is fine and just falls back to the
plain archetype name.

Total Gemini calls per debate: `1` (topic check) `+ personas * 2` (`+1` if
moderator is on) -- e.g. 3 personas with the moderator on = 8 calls.

**Safety guardrails on persona prompts.** Handled two ways: (1) structurally,
by only ever accepting curated registry keys (see above) -- there's no path
by which "argue as [any name]" reaches the model; (2) at the prompt level,
every persona/moderator prompt in `debate/prompts.py` includes a shared
safety note instructing the model to stay in the described archetype, never
claim to be a real named person, avoid protected-class stereotypes, and keep
disagreement civil/PG (no insults or slurs). This was also applied when
writing each persona's `voice_style` in `personas/registry.py` itself --
personality and speech-pattern quirks only, no caricature of any real group.


## Project structure

```
apps/multi-persona-debate/
├── backend/
│   ├── main.py                  # FastAPI app, CORS
│   ├── config.py                # env-driven caps/limits
│   ├── redis_client.py          # Redis client, or None (in-memory fallback)
│   ├── common/gemini_client.py  # the only place that talks to the Gemini SDK
│   ├── shared/retry.py          # exponential backoff for Gemini calls
│   ├── personas/registry.py     # the curated persona list -- the safety guardrail
│   ├── debate/
│   │   ├── models.py            # PersonaStatement, DebateTranscript (Pydantic)
│   │   ├── prompts.py           # opening/rebuttal/moderator prompt builders
│   │   ├── orchestrator.py      # round 1 -> round 2 -> optional moderator + winner
│   │   └── topic_validator.py   # rejects gibberish/non-topics and time-sensitive topics
│   ├── limits/                  # identity cookie + daily rate caps
│   ├── api/
│   │   ├── schemas.py           # request/response Pydantic models
│   │   └── routes.py            # /api/health, /api/personas, /api/debate(/stream), /api/admin/stats
│   ├── tests/                   # pytest, Gemini fully mocked
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── .env.example
└── frontend/
    ├── index.html
    ├── app.js
    └── style.css
```

## Setup & run

### Backend

```bash
cd apps/multi-persona-debate/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # or requirements.txt if you don't need tests
cp .env.example .env                  # then fill in GEMINI_API_KEY
uvicorn main:app --reload --port 8000
```

Check it's alive: `curl http://localhost:8000/api/health` -> `{"status":"ok"}`.

### Frontend

No build step -- serve the static files with anything:

```bash
cd apps/multi-persona-debate/frontend
python3 -m http.server 5500
```

Open `http://localhost:5500`. If your backend isn't on `http://localhost:8000`,
edit the `API_BASE_URL` constant at the top of `frontend/app.js`. Make sure
`CORS_ORIGINS` in the backend's `.env` includes whatever origin you're
serving the frontend from (defaults to `http://localhost:5500`).

### Tests

```bash
cd apps/multi-persona-debate/backend
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -v
```

All tests pass with the Gemini client fully mocked -- no `GEMINI_API_KEY`
required to run them. Verified locally on Python 3.14.6.

### Smoke test performed during development

- `pytest -v`: 40/40 passed.
- Booted `uvicorn main:app` for real and hit `/api/health` and
  `/api/personas` over HTTP.
- Hit `/api/debate` with an unknown persona key and with too few personas --
  both correctly rejected with `400` before any Gemini call.
- Served the static frontend on `:5500` alongside the backend on `:8123` and
  confirmed the CORS preflight/response headers (`access-control-allow-origin`)
  matched.
- Live-hit `/api/debate/stream` with a gibberish topic and a time-sensitive
  topic ("who will win the 2026 US election") against the real Gemini API --
  both correctly rejected with `400` before any persona ran.
- Live-hit `/api/debate/stream` with `user_name: "Tom"` and confirmed every
  persona statement used "The Pragmatist Tom" / "The Comedian Tom" etc., and
  that the moderator declared a real winner with a matching reason.


## Admin stats (optional)

`GET /api/admin/stats` mirrors `is-it-true`'s: returns today's global Gemini
call count vs. cap, gated behind an `X-Admin-Token` header matching
`ADMIN_TOKEN`. Returns `404` (not `401`) when `ADMIN_TOKEN` is unset, so the
endpoint's existence isn't revealed by default.
