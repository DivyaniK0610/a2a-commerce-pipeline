/**
 * app.js — A2A Commerce Pipeline Glass Box Frontend
 * Razorpay Buildathon Track 1
 */

const API_BASE = "http://127.0.0.1:5000/api";

// ── State ─────────────────────────────────────────────────────────────────────
let conversationHistory = [];
let isAgentThinking = false;
let sseEventSource = null;
let teleEventCount = 0;

// ── DOM References ────────────────────────────────────────────────────────────
const chatMessages       = document.getElementById("chat-messages");
const chatInput          = document.getElementById("chat-input");
const chatForm           = document.getElementById("chat-form");
const sendBtn            = document.getElementById("send-btn");
const typingIndicator    = document.getElementById("typing-indicator");
const agentStatus        = document.getElementById("agent-status");
const telemetryLog       = document.getElementById("telemetry-log");
const sseDot             = document.getElementById("sse-dot");
const sseStatusText      = document.getElementById("sse-status-text");
const healthDot          = document.getElementById("health-dot");
const btnClearTele       = document.getElementById("btn-clear-tele");
const btnAuditLog        = document.getElementById("btn-audit-log");
const auditModalOverlay  = document.getElementById("audit-modal-overlay");
const auditModalClose    = document.getElementById("audit-modal-close");
const auditTableBody     = document.getElementById("audit-table-body");
const auditCount         = document.getElementById("audit-count");

// ── Utilities ─────────────────────────────────────────────────────────────────

function now() {
  return new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function formatCurrency(val) {
  return "₹" + Number(val).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(String(str)));
  return div.innerHTML;
}

// JSON syntax highlighter
function syntaxHighlightJson(json) {
  if (typeof json !== "string") {
    json = JSON.stringify(json, null, 2);
  }
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = "json-number";
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? "json-key" : "json-string";
      } else if (/true|false/.test(match)) {
        cls = "json-bool";
      } else if (/null/.test(match)) {
        cls = "json-null";
      }
      return `<span class="${cls}">${escapeHtml(match)}</span>`;
    }
  );
}

// ── Health Check ──────────────────────────────────────────────────────────────

async function checkHealth() {
  try {
    const resp = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    if (resp.ok) {
      healthDot.classList.remove("offline");
      healthDot.title = "Backend online";
    } else {
      throw new Error("not ok");
    }
  } catch {
    healthDot.classList.add("offline");
    healthDot.title = "Backend offline";
  }
}

// ── SSE Telemetry ─────────────────────────────────────────────────────────────

function connectSSE() {
  if (sseEventSource) sseEventSource.close();

  sseEventSource = new EventSource(`${API_BASE}/stream`);

  sseEventSource.onopen = () => {
    sseDot.classList.remove("disconnected");
    sseStatusText.textContent = "LIVE";
  };

  sseEventSource.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      addTelemetryEvent(data);
    } catch { /* ignore malformed */ }
  };

  sseEventSource.onerror = () => {
    sseDot.classList.add("disconnected");
    sseStatusText.textContent = "DISCONNECTED";
    sseEventSource.close();
    // Reconnect after 3 seconds
    setTimeout(connectSSE, 3000);
  };
}

function addTelemetryEvent(data) {
  teleEventCount++;
  const eventType = data.event_type || "unknown";
  const timestamp = data.timestamp
    ? new Date(data.timestamp).toLocaleTimeString("en-IN", { hour12: false })
    : now();

  // Determine tag class and label
  const tagInfo = getTeleTagInfo(eventType, data);
  const statusBadge = getTeleStatusBadge(eventType, data);

  const card = document.createElement("div");
  card.className = "tele-event";
  card.id = `tele-${teleEventCount}`;

  // Build JSON body content
  const bodyContent = buildTeleBody(eventType, data);

  card.innerHTML = `
    <div class="tele-event-header" onclick="toggleTeleEvent('tele-${teleEventCount}')">
      <div class="tele-event-left">
        <span class="tele-endpoint-tag ${tagInfo.cls}">${tagInfo.label}</span>
        <span class="tele-event-name">${escapeHtml(tagInfo.name)}</span>
      </div>
      <div class="tele-event-right">
        ${statusBadge}
        <span class="tele-time">${timestamp}</span>
        <span class="tele-chevron">▶</span>
      </div>
    </div>
    <div class="tele-event-body">
      <div class="json-viewer">${bodyContent}</div>
    </div>
  `;

  telemetryLog.appendChild(card);
  telemetryLog.scrollTop = telemetryLog.scrollHeight;

  // Auto-expand the first event and important events
  if (teleEventCount === 1 || ["ondc_search", "ondc_select", "ondc_init", "webhook_payment_paid"].includes(eventType)) {
    card.classList.add("expanded");
  }
}

function getTeleTagInfo(eventType, data) {
  const map = {
    "connected":              { cls: "tag-system",   label: "SYS",     name: "Stream Connected" },
    "ondc_search":            { cls: "tag-search",   label: "SEARCH",  name: data.endpoint || "/api/search" },
    "ondc_select":            { cls: "tag-select",   label: "SELECT",  name: data.endpoint || "/api/select" },
    "ondc_init":              { cls: "tag-init",     label: "INIT",    name: data.endpoint || "/api/init" },
    "razorpay_create":        { cls: "tag-razorpay", label: "RZRPAY",  name: "Razorpay Payment Link" },
    "webhook_payment_paid":   { cls: "tag-webhook",  label: "WEBHOOK", name: "Payment Confirmed 🎉" },
    "agent_thinking":         { cls: "tag-agent",    label: "AGENT",   name: "Buyer Agent Processing" },
    "agent_response":         { cls: "tag-agent",    label: "AGENT",   name: "Buyer Agent Response" },
    "agent_error":            { cls: "tag-error",    label: "ERROR",   name: "Agent Error" },
  };
  return map[eventType] || { cls: "tag-system", label: "EVT", name: eventType };
}

function getTeleStatusBadge(eventType, data) {
  const status = data.status || "";
  if (status === "success" || eventType === "connected" || eventType === "agent_response") {
    return `<span class="tele-status-badge status-success">✓ OK</span>`;
  } else if (eventType === "webhook_payment_paid" || status === "payment_confirmed") {
    return `<span class="tele-status-badge status-success">💳 PAID</span>`;
  } else if (status === "error" || status === "out_of_stock" || status === "not_found" || eventType === "agent_error") {
    return `<span class="tele-status-badge status-error">✕ ERR</span>`;
  } else if (status === "calling_razorpay" || eventType === "agent_thinking") {
    return `<span class="tele-status-badge status-pending">⟳ WAIT</span>`;
  } else {
    return `<span class="tele-status-badge status-info">● INFO</span>`;
  }
}

function buildTeleBody(eventType, data) {
  // For agent events, show a simplified view
  if (eventType === "agent_thinking") {
    return syntaxHighlightJson({ processing: data.message });
  }
  if (eventType === "agent_response") {
    return syntaxHighlightJson({ tools_used: data.tools_used, reply_preview: data.reply_preview });
  }
  if (eventType === "connected") {
    return syntaxHighlightJson({ status: "SSE stream established", message: data.message });
  }

  // For ONDC events, show request/response
  const display = {};
  if (data.request)  display.request = data.request;
  if (data.response) display.response = data.response;
  if (data.query)    display.query = data.query;
  if (data.status)   display.status = data.status;

  return syntaxHighlightJson(Object.keys(display).length ? display : data);
}

function toggleTeleEvent(id) {
  const card = document.getElementById(id);
  if (card) card.classList.toggle("expanded");
}

// ── Chat Logic ────────────────────────────────────────────────────────────────

function setThinking(thinking) {
  isAgentThinking = thinking;
  sendBtn.disabled = thinking;
  chatInput.disabled = thinking;

  if (thinking) {
    typingIndicator.classList.add("visible");
    agentStatus.textContent = "Thinking…";
    agentStatus.classList.add("thinking");
    chatMessages.scrollTop = chatMessages.scrollHeight;
  } else {
    typingIndicator.classList.remove("visible");
    agentStatus.textContent = "Online";
    agentStatus.classList.remove("thinking");
  }
}

function appendMessage(role, content, extras = {}) {
  // Remove typing indicator from DOM position
  typingIndicator.remove();

  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;

  // Parse the message content for special rendering
  const { htmlContent, paymentLink, quoteData } = parseMessageContent(content);

  wrap.innerHTML = `
    <div class="message-bubble">${htmlContent}</div>
    <span class="message-time">${now()}</span>
  `;

  // Append quote card if data found
  if (quoteData) {
    const card = buildQuoteCard(quoteData);
    wrap.insertBefore(card, wrap.querySelector(".message-time"));
  }

  // Append payment button if link found
  if (paymentLink) {
    const btn = document.createElement("a");
    btn.href = paymentLink;
    btn.target = "_blank";
    btn.rel = "noopener noreferrer";
    btn.className = "payment-btn";
    btn.innerHTML = `<span>🔐</span> Pay with Razorpay`;
    wrap.insertBefore(btn, wrap.querySelector(".message-time"));
  }

  chatMessages.appendChild(wrap);
  // Re-append typing indicator at the end
  chatMessages.appendChild(typingIndicator);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function parseMessageContent(text) {
  // Extract payment link from text
  const rzpLinkMatch = text.match(/https?:\/\/rzp\.io\/[^\s)]+/);
  const paymentLink = rzpLinkMatch ? rzpLinkMatch[0] : null;

  // Extract quote data from structured text patterns
  let quoteData = null;
  const baseMatch   = text.match(/Base Price[:\s]+₹?([\d,]+(?:\.\d{2})?)/i);
  const gstMatch    = text.match(/GST[^:]*:[:\s]+₹?([\d,]+(?:\.\d{2})?)/i);
  const totalMatch  = text.match(/Total[:\s]+₹?([\d,]+(?:\.\d{2})?)/i);
  const itemMatch   = text.match(/Item[:\s]+([^\n]+)/i);

  if (baseMatch && gstMatch && totalMatch) {
    quoteData = {
      item: itemMatch ? itemMatch[1].trim() : "Item",
      base: parseFloat(baseMatch[1].replace(/,/g, "")),
      gst:  parseFloat(gstMatch[1].replace(/,/g, "")),
      total: parseFloat(totalMatch[1].replace(/,/g, ""))
    };
  }

  // Convert markdown-like text to HTML
  let html = escapeHtml(text)
    .replace(/\n/g, "<br>")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code style='background:rgba(0,0,0,0.1);padding:1px 4px;border-radius:3px;font-size:12px'>$1</code>")
    .replace(/(https?:\/\/rzp\.io\/[^\s<]+)/g, '<span style="color:#6366f1;text-decoration:underline">$1</span>');

  return { htmlContent: html, paymentLink, quoteData };
}

function buildQuoteCard(data) {
  const card = document.createElement("div");
  card.className = "quote-card";
  card.innerHTML = `
    <div class="quote-card-title">📋 Price Breakdown</div>
    <div class="quote-row"><span>${escapeHtml(data.item)}</span></div>
    <div class="quote-row">
      <span>Base Price</span>
      <span>${formatCurrency(data.base)}</span>
    </div>
    <div class="quote-row">
      <span>GST (18%)</span>
      <span>${formatCurrency(data.gst)}</span>
    </div>
    <div class="quote-row total">
      <span>Total Payable</span>
      <span>${formatCurrency(data.total)}</span>
    </div>
  `;
  return card;
}

async function sendMessage(text) {
  const msg = (text || chatInput.value).trim();
  if (!msg || isAgentThinking) return;

  chatInput.value = "";
  chatInput.style.height = "42px";

  // Show user message
  appendMessage("user", msg);
  setThinking(true);

  // Update conversation history
  conversationHistory.push({ role: "user", content: msg });

  try {
    const resp = await fetch(`${API_BASE}/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: msg,
        history: conversationHistory.slice(-10) // Keep last 10 turns
      })
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    const reply = data.reply || "I encountered an issue. Please try again.";

    // Show bot reply
    appendMessage("bot", reply);

    // Update history
    conversationHistory.push({ role: "assistant", content: reply });

  } catch (err) {
    appendMessage("bot", `⚠️ Error: ${err.message}\n\nMake sure the Flask backend is running on port 5000.`);
    conversationHistory.push({ role: "assistant", content: `Error: ${err.message}` });
  } finally {
    setThinking(false);
  }
}

// ── Audit Log Modal ───────────────────────────────────────────────────────────

async function openAuditLog() {
  auditTableBody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--tele-muted);padding:20px">Loading...</td></tr>`;
  auditModalOverlay.classList.add("open");

  try {
    const resp = await fetch(`${API_BASE}/logs`);
    const data = await resp.json();
    const logs = data.logs || [];

    auditCount.textContent = `${logs.length} entries`;

    if (logs.length === 0) {
      auditTableBody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--tele-muted);padding:20px">No logs yet. Start a conversation to generate logs.</td></tr>`;
      return;
    }

    auditTableBody.innerHTML = logs.map(log => {
      const ts = new Date(log.timestamp + "Z").toLocaleString("en-IN");
      const statusCls = ["success"].includes(log.status) ? "audit-status-ok" : "audit-status-err";
      const payload = typeof log.raw_payload === "object"
        ? JSON.stringify(log.raw_payload, null, 2)
        : String(log.raw_payload || "");
      const truncated = payload.length > 120 ? payload.slice(0, 120) + "…" : payload;

      return `
        <tr>
          <td style="color:var(--tele-muted);white-space:nowrap">${escapeHtml(ts)}</td>
          <td><span class="audit-action">${escapeHtml(log.action)}</span></td>
          <td class="${statusCls}">${escapeHtml(log.status || "-")}</td>
          <td style="color:var(--tele-muted);font-size:10px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml((log.transaction_id || "").slice(0, 8))}…</td>
          <td><pre style="font-size:10px;color:var(--tele-muted);white-space:pre-wrap;max-width:300px;margin:0">${escapeHtml(truncated)}</pre></td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    auditTableBody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--tele-red);padding:20px">Failed to load logs: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function closeAuditLog() {
  auditModalOverlay.classList.remove("open");
}

// ── Quick Prompts ─────────────────────────────────────────────────────────────

function useQuickPrompt(text) {
  chatInput.value = text;
  chatInput.focus();
}

// ── Event Listeners ───────────────────────────────────────────────────────────

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage();
});

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Auto-resize textarea
chatInput.addEventListener("input", () => {
  chatInput.style.height = "42px";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 100) + "px";
});

btnClearTele.addEventListener("click", () => {
  telemetryLog.innerHTML = "";
  teleEventCount = 0;
});

btnAuditLog.addEventListener("click", openAuditLog);
auditModalClose.addEventListener("click", closeAuditLog);
auditModalOverlay.addEventListener("click", (e) => {
  if (e.target === auditModalOverlay) closeAuditLog();
});

// Close modal on Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAuditLog();
});

// ── Init ──────────────────────────────────────────────────────────────────────

function init() {
  // Welcome message
  appendMessage("bot",
    "👋 Hello! I'm your **ONDC Buyer Agent**, powered by Groq AI.\n\n" +
    "I can help you browse and purchase products from the merchant catalog using real-time price quotes and Razorpay payments.\n\n" +
    "Try asking: *\"Show me available keyboards\"* or *\"I need a webcam\"*"
  );

  // Connect SSE telemetry
  connectSSE();

  // Check backend health
  checkHealth();
  setInterval(checkHealth, 15000);
}

init();
