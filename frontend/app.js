// IT Support Assistant - frontend logic.
// Uses relative API URLs so the frontend works when served by FastAPI.
// Dynamic content is inserted with textContent for safe rendering.

const form = document.getElementById("ticket-form");
const questionInput = document.getElementById("question");
const submitButton = document.getElementById("submit-btn");
const charCount = document.getElementById("char-count");
const loadingBar = document.getElementById("loading");
const errorBox = document.getElementById("error");
const resultSection = document.getElementById("result");
const ticketMeta = document.getElementById("ticket-meta");
const aiResponseBox = document.getElementById("ai-response");
const contextSummary = document.getElementById("context-summary");
const contextList = document.getElementById("context");
const llmBanner = document.getElementById("llm-banner");
const ticketList = document.getElementById("ticket-list");

function setLoading(isLoading) {
  loadingBar.classList.toggle("hidden", !isLoading);
  submitButton.disabled = isLoading;
  submitButton.innerHTML = isLoading
    ? "Processing..."
    : "<span>Get troubleshooting help</span><span aria-hidden=\"true\">→</span>";
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}

function clearError() {
  errorBox.classList.add("hidden");
  errorBox.textContent = "";
}

function updateCharCount() {
  charCount.textContent = `${questionInput.value.length} / 1000`;
}

function messageFrom(data, status) {
  if (data && typeof data.detail === "string") return data.detail;
  if (data && Array.isArray(data.detail) && data.detail.length > 0) {
    return data.detail[0].msg || `Request failed (${status}).`;
  }
  return `Request failed (HTTP ${status}).`;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (networkError) {
    throw new Error("Cannot reach the backend server. Is the FastAPI server running?");
  }

  let data = null;
  try {
    data = await response.json();
  } catch (parseError) {
    data = null;
  }

  if (!response.ok) {
    throw new Error(messageFrom(data, response.status));
  }
  return data;
}

function renderContext(items) {
  contextList.innerHTML = "";

  if (!items || items.length === 0) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = "No strong knowledge-base match was found for this question.";
    contextList.appendChild(note);
  } else {
    items.forEach((item) => {
      const block = document.createElement("div");
      block.className = "context-item";

      const title = document.createElement("h4");
      title.textContent = item.title;

      const solution = document.createElement("p");
      solution.textContent = item.solution;

      block.appendChild(title);
      block.appendChild(solution);
      contextList.appendChild(block);
    });
  }

  const count = items ? items.length : 0;
  contextSummary.textContent =
    `Knowledge-base context used (${count} article${count === 1 ? "" : "s"})`;
}

function renderTicket(ticket) {
  const created = ticket.created_at
    ? new Date(ticket.created_at).toLocaleString()
    : "";

  ticketMeta.textContent = `Ticket #${ticket.id}${created ? " · " + created : ""}`;
  aiResponseBox.textContent = ticket.ai_response;
  renderContext(ticket.retrieved_context);
  resultSection.classList.remove("hidden");
  resultSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function submitQuestion(event) {
  event.preventDefault();
  clearError();
  resultSection.classList.add("hidden");

  const question = questionInput.value.trim();
  if (question.length < 3) {
    showError("Please describe your problem (at least 3 characters).");
    return;
  }

  setLoading(true);

  try {
    const ticket = await api("/api/tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    renderTicket(ticket);
    questionInput.value = "";
    updateCharCount();
    await loadRecentTickets();
  } catch (error) {
    showError(error instanceof Error ? error.message : "Something went wrong.");
  } finally {
    setLoading(false);
  }
}

async function openTicket(id) {
  clearError();

  try {
    const ticket = await api(`/api/tickets/${id}`);
    renderTicket(ticket);
  } catch (error) {
    showError(error instanceof Error ? error.message : "Could not open that ticket.");
  }
}

async function loadRecentTickets() {
  try {
    const tickets = await api("/api/tickets?limit=10");
    ticketList.innerHTML = "";

    if (!tickets.length) {
      const empty = document.createElement("li");
      empty.className = "muted";
      empty.textContent = "No tickets yet.";
      ticketList.appendChild(empty);
      return;
    }

    tickets.forEach((ticket) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";

      const created = ticket.created_at
        ? new Date(ticket.created_at).toLocaleDateString()
        : "";
      const shortQuestion = ticket.question.length > 70
        ? ticket.question.slice(0, 70) + "..."
        : ticket.question;

      button.textContent = `#${ticket.id} · ${shortQuestion}${created ? ` (${created})` : ""}`;
      button.addEventListener("click", () => openTicket(ticket.id));

      item.appendChild(button);
      ticketList.appendChild(item);
    });
  } catch (error) {
    ticketList.innerHTML = "";
    const note = document.createElement("li");
    note.className = "muted";
    note.textContent = "Could not load recent tickets.";
    ticketList.appendChild(note);
  }
}

async function checkLLMStatus() {
  try {
    const health = await api("/api/health");

    if (!health.llm_configured) {
      llmBanner.textContent =
        "No LLM API key is configured. Copy .env.example to .env, add a " +
        "Cohere API key (COHERE_API_KEY_PRIMARY), and restart the backend to " +
        "enable AI answers.";
      llmBanner.classList.remove("hidden");
    }
  } catch (error) {
    // Informational only. The form reports actionable API errors.
  }
}

function setupHintButtons() {
  document.querySelectorAll(".hint").forEach((button) => {
    button.addEventListener("click", () => {
      questionInput.value = button.dataset.question || "";
      updateCharCount();
      questionInput.focus();
    });
  });
}

form.addEventListener("submit", submitQuestion);
questionInput.addEventListener("input", updateCharCount);
questionInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    form.requestSubmit();
  }
});

updateCharCount();
setupHintButtons();
checkLLMStatus();
loadRecentTickets();
