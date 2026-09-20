// Edit this before deploying -- there's no build step, so the backend URL is
// just a constant. Point it at your Render/Fly.io backend's public URL.
const API_BASE_URL = "http://localhost:8000";

const MAX_CHARS = 300;
const MIN_PERSONAS = 2;
const MAX_PERSONAS = 4;

const nameInput = document.getElementById("name-input");
const topicInput = document.getElementById("topic-input");
const charCount = document.getElementById("char-count");
const personaPicker = document.getElementById("persona-picker");
const moderatorCheckbox = document.getElementById("moderator-checkbox");
const selectionHint = document.getElementById("selection-hint");
const debateBtn = document.getElementById("debate-btn");
const clearBtn = document.getElementById("clear-btn");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const transcriptEl = document.getElementById("transcript");

let personasByKey = new Map(); // key -> persona info, fetched once from /api/personas
let selectedKeys = new Set();
let personaNameByKey = new Map(); // key -> this debate's (possibly personalized) display name

init();

async function init() {
  nameInput.addEventListener("input", hideTranscript);

  topicInput.addEventListener("input", () => {
    charCount.textContent = `${topicInput.value.length} / ${MAX_CHARS}`;
    hideTranscript();
  });

  moderatorCheckbox.addEventListener("change", hideTranscript);
  debateBtn.addEventListener("click", startDebate);
  clearBtn.addEventListener("click", clearForm);

  try {
    const response = await fetch(`${API_BASE_URL}/api/personas`);
    const personas = await response.json();
    renderPersonaPicker(personas);
  } catch {
    personaPicker.innerHTML = "<p class='persona-loading'>Couldn't load the cast -- check that the backend is running.</p>";
  }
}

// Deliberately built entirely from the curated list the backend returns --
// there is no free-text field anywhere for a persona name. This is the
// frontend half of the app's core safety guardrail (the backend enforces
// the same thing again, independently, in api/routes.py).
function renderPersonaPicker(personas) {
  personaPicker.innerHTML = "";
  for (const persona of personas) {
    personasByKey.set(persona.key, persona);

    const card = document.createElement("button");
    card.type = "button";
    card.className = "persona-card";
    card.style.setProperty("--persona-color", persona.color);
    card.dataset.key = persona.key;
    card.innerHTML = `
      <span class="persona-check" aria-hidden="true">✓</span>
      <span class="persona-avatar">${persona.avatar}</span>
      <span class="persona-name">${persona.name}</span>
      <span class="persona-desc">${persona.description}</span>
    `;
    card.addEventListener("click", () => togglePersona(persona.key, card));
    personaPicker.appendChild(card);
  }
}

function togglePersona(key, card) {
  if (selectedKeys.has(key)) {
    selectedKeys.delete(key);
    card.classList.remove("selected");
  } else {
    if (selectedKeys.size >= MAX_PERSONAS) {
      showStatus(`You can select at most ${MAX_PERSONAS} personas.`, true);
      return;
    }
    selectedKeys.add(key);
    card.classList.add("selected");
  }
  updateSelectionHint();
  hideTranscript();
}

function clearForm() {
  nameInput.value = "";
  topicInput.value = "";
  charCount.textContent = `0 / ${MAX_CHARS}`;
  moderatorCheckbox.checked = true;

  selectedKeys.clear();
  for (const card of personaPicker.querySelectorAll(".persona-card.selected")) {
    card.classList.remove("selected");
  }

  updateSelectionHint();
  hideTranscript();
  hideStatus();
}

function updateSelectionHint() {
  const count = selectedKeys.size;
  if (count < MIN_PERSONAS) {
    selectionHint.textContent = `Select ${MIN_PERSONAS}-${MAX_PERSONAS} personas (${count} selected).`;
    debateBtn.disabled = true;
  } else {
    selectionHint.textContent = `${count} of ${MAX_PERSONAS} selected.`;
    debateBtn.disabled = false;
  }
}

async function startDebate() {
  const userName = nameInput.value.trim();
  if (!userName) {
    showStatus("Please enter your name -- the personas will address you by it.", true);
    return;
  }
  const topic = topicInput.value.trim();
  if (!topic) {
    showStatus("Please enter a topic to debate.", true);
    return;
  }
  if (selectedKeys.size < MIN_PERSONAS || selectedKeys.size > MAX_PERSONAS) {
    showStatus(`Please select ${MIN_PERSONAS}-${MAX_PERSONAS} personas.`, true);
    return;
  }

  setLoading(true);
  hideTranscript();
  transcriptEl.innerHTML = "";
  transcriptEl.hidden = false;
  personaNameByKey.clear();

  const state = { receivedDone: false };

  try {
    const response = await fetch(`${API_BASE_URL}/api/debate/stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic,
        personas: Array.from(selectedKeys),
        include_moderator: moderatorCheckbox.checked,
        user_name: userName,
      }),
    });

    if (response.status === 429) {
      showStatus("You've used your free debates for today -- come back tomorrow.", true);
      return;
    }
    if (response.status === 503) {
      showStatus("This service hit today's usage limit -- please try again tomorrow.", true);
      return;
    }
    if (!response.ok) {
      const body = await safeJson(response);
      showStatus(body?.detail || "Something went wrong. Please try again.", true);
      return;
    }

    await readEventStream(response, state);

    if (!state.receivedDone) {
      showStatus("The stream ended early -- please try again.", true);
    } else {
      hideStatus();
    }
  } catch {
    showStatus("Couldn't reach the debate service. Check your connection and try again.", true);
  } finally {
    setLoading(false);
  }
}

// The backend streams each persona's statement as its own SSE event the
// moment that persona's Gemini call finishes, instead of one blocking JSON
// response after the whole debate is done -- so bubbles fill in live,
// round by round, persona by persona.
async function readEventStream(response, state) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      handleStreamEvent(rawEvent, state);
    }
  }
}

function handleStreamEvent(rawEvent, state) {
  const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data:"));
  if (!dataLine) return;

  let event;
  try {
    event = JSON.parse(dataLine.slice(5).trim());
  } catch {
    return;
  }

  if (event.event === "round_start") {
    ensureRoundHeading(event.round, event.label);
    setStatusForRound(event.round);
  } else if (event.event === "statement") {
    appendStatementBubble(event, { animateTyping: true });
  } else if (event.event === "moderator_start") {
    ensureModeratorHeading();
    statusTextEl.textContent = "The moderator is weighing in...";
  } else if (event.event === "moderator") {
    appendModeratorBubble(event.summary, { animateTyping: true });
    appendWinnerBanner(event.winner_persona_key, event.winner_reason);
  } else if (event.event === "done") {
    state.receivedDone = true;
  }
}

function ensureRoundHeading(roundNumber, label) {
  const id = `round-heading-${roundNumber}`;
  if (document.getElementById(id)) return;
  const heading = document.createElement("h2");
  heading.id = id;
  heading.className = "round-heading";
  heading.textContent = label;
  transcriptEl.appendChild(heading);
}

function ensureModeratorHeading() {
  if (document.getElementById("round-heading-moderator")) return;
  const heading = document.createElement("h2");
  heading.id = "round-heading-moderator";
  heading.className = "round-heading";
  heading.textContent = "Moderator's Wrap-Up";
  transcriptEl.appendChild(heading);
}

function setStatusForRound(roundNumber) {
  statusTextEl.textContent =
    roundNumber === 1
      ? "Opening statements are coming in..."
      : `Round ${roundNumber} is underway...`;
}

function appendStatementBubble(statement, { animateTyping }) {
  personaNameByKey.set(statement.persona_key, statement.persona_name);
  const persona = personasByKey.get(statement.persona_key);
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.style.setProperty("--persona-color", persona?.color || "#f2b134");
  bubble.innerHTML = `
    <span class="bubble-avatar">${persona?.avatar || "🗨️"}</span>
    <div class="bubble-body">
      <span class="bubble-name">${statement.persona_name}</span>
      <p class="bubble-text"><span class="type-target"></span><span class="type-cursor"></span></p>
    </div>
  `;
  transcriptEl.appendChild(bubble);

  const target = bubble.querySelector(".type-target");
  const cursor = bubble.querySelector(".type-cursor");
  if (animateTyping) {
    typeText(target, cursor, statement.text);
  } else {
    target.textContent = statement.text;
    cursor.remove();
  }
}

function appendModeratorBubble(summary, { animateTyping }) {
  const bubble = document.createElement("div");
  bubble.className = "bubble moderator-bubble";
  bubble.innerHTML = `
    <span class="bubble-avatar">⚖️</span>
    <div class="bubble-body">
      <span class="bubble-name">Moderator</span>
      <p class="bubble-text"><span class="type-target"></span><span class="type-cursor"></span></p>
    </div>
  `;
  transcriptEl.appendChild(bubble);

  const target = bubble.querySelector(".type-target");
  const cursor = bubble.querySelector(".type-cursor");
  if (animateTyping) {
    typeText(target, cursor, summary);
  } else {
    target.textContent = summary;
    cursor.remove();
  }
}

function appendWinnerBanner(winnerPersonaKey, winnerReason) {
  if (!winnerPersonaKey) return; // moderator's pick didn't match a known persona -- skip the banner entirely

  const persona = personasByKey.get(winnerPersonaKey);
  const displayName = personaNameByKey.get(winnerPersonaKey) || persona?.name || "The winner";

  const banner = document.createElement("div");
  banner.className = "winner-banner";
  banner.innerHTML = `
    <span class="winner-trophy" aria-hidden="true">🏆</span>
    <div class="winner-body">
      <span class="winner-title">${persona?.avatar || ""} ${displayName} wins the debate!</span>
      <p class="winner-reason"><span class="type-target"></span><span class="type-cursor"></span></p>
    </div>
  `;
  transcriptEl.appendChild(banner);

  const target = banner.querySelector(".type-target");
  const cursor = banner.querySelector(".type-cursor");
  typeText(target, cursor, winnerReason || "");
}

// Reveals `text` into `targetEl` a character at a time, with a blinking
// cursor after the revealed portion, so each statement visibly "speaks
// itself" onto the stage rather than appearing all at once. Total duration
// is capped so long statements don't drag the debate out.
function typeText(targetEl, cursorEl, text) {
  const totalDurationMs = Math.min(1400, Math.max(300, text.length * 16));
  const stepMs = Math.max(8, totalDurationMs / Math.max(text.length, 1));
  let i = 0;

  const interval = setInterval(() => {
    i += 1;
    targetEl.textContent = text.slice(0, i);
    if (i >= text.length) {
      clearInterval(interval);
      cursorEl.remove();
    }
  }, stepMs);
}

function setLoading(isLoading) {
  debateBtn.disabled = isLoading || selectedKeys.size < MIN_PERSONAS;
  debateBtn.textContent = isLoading ? "The debate is live..." : "Raise the curtain";
  if (isLoading) {
    showStatus("Taking the stage...", false);
  }
}

function showStatus(message, isError) {
  statusTextEl.textContent = message;
  statusEl.hidden = false;
  statusEl.classList.toggle("error", isError);
}

function hideStatus() {
  statusEl.hidden = true;
}

function hideTranscript() {
  transcriptEl.hidden = true;
  transcriptEl.innerHTML = "";
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
