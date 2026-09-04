# ⚡ A2A Commerce Pipeline
### Razorpay Buildathon Track 1 — AI Growth & Agentic Commerce

An autonomous **Agent-to-Agent (A2A) commerce system** where a Groq-powered AI buyer agent navigates a full ONDC/Beckn-inspired purchase flow — from product discovery to Razorpay payment — with zero human intervention in the ordering process.

---

## 🎯 What It Does

```
User: "I want 2 mechanical keyboards"
         ↓
🤖 Agent → ONDC /search  →  finds product + item_id
🤖 Agent → ONDC /select  →  gets GST quote (18%)
🤖 Agent → ONDC /init    →  creates Razorpay Payment Link
         ↓
💳 User clicks Pay → enters OTP  (legally required)
         ↓
🔔 Razorpay Webhook → auto-confirms order in DB
```

**The agent handles search, pricing, GST calculation, and payment link generation autonomously.**

---

## 🏗️ Architecture

```
frontend/
  index.html      — Glass Box split-screen UI
  style.css       — Glassmorphism dark theme
  app.js          — SSE consumer + chat logic

backend/
  app.py          — Flask: ONDC endpoints + SSE telemetry + Razorpay webhook
  agent.py        — Groq LLM agent with tool-calling (search/select/init)
  database.py     — SQLite: inventory, orders, immutable audit log
  razorpay_client.py — Razorpay REST API (payment links, no SDK)
  seed_data.py    — Seeds 6 demo products
```

---

## 🚀 Tech Stack

| Layer | Technology |
|---|---|
| **LLM Orchestrator** | Groq (`openai/gpt-oss-120b`) with tool calling |
| **Commerce Protocol** | ONDC/Beckn-inspired (`/search` → `/select` → `/init`) |
| **Payments** | Razorpay Payment Links API + Webhook |
| **Backend** | Python Flask + SQLite |
| **Frontend** | HTML + Tailwind CSS + Vanilla JS + SSE |
| **Real-time** | Server-Sent Events (SSE) telemetry stream |

---

## 🛠️ Setup

### 1. Clone & create virtual environment
```bash
git clone <your-repo-url>
cd "A2A Agent/backend"
python -m venv venv
venv\scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure API keys
```bash
cp .env.example .env
```
Edit `.env`:
```env
GROQ_API_KEY=your_groq_api_key_here
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_secret_here
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret_here
```

**Get keys:**
- Groq: [console.groq.com](https://console.groq.com) → API Keys
- Razorpay: [dashboard.razorpay.com](https://dashboard.razorpay.com) → Settings → API Keys (Test Mode)

### 3. Seed the database & run
```bash
python seed_data.py    # Seeds 6 demo products
python app.py          # Starts Flask on http://127.0.0.1:5000
```

### 4. Open the frontend
Open `frontend/index.html` directly in your browser (double-click).

---

## 💬 Demo Flow

Try these in the chat:

| Message | What happens |
|---|---|
| `"I need a mechanical keyboard"` | Agent searches catalog, shows product |
| `"2 please"` | Agent gets price quote with 18% GST |
| `"My name is X, email x@x.com, phone +91XXXXXXXXXX"` | Agent creates Razorpay payment link |
| Click **🔐 Pay with Razorpay** | Complete test payment |

**Quick demo buttons:** Keyboard · All Products · Test Stock Error · Full Purchase

---

## 🔬 Developer Telemetry

The right pane streams all ONDC API payloads in real-time via SSE:
- `SEARCH` — catalog query + results
- `SELECT` — price quote with GST breakdown
- `INIT` — order creation + payment link
- `WEBHOOK` — payment confirmation (gold badge 💳 PAID)

---

## 🔔 Webhook Setup (for payment auto-confirmation)

```bash
# Expose Flask publicly
ssh -R 80:localhost:5000 nokey@localhost.run

# Add webhook in Razorpay Dashboard → Settings → Webhooks
# URL: https://your-tunnel.lhr.life/api/webhook/razorpay
# Events: payment_link.paid, payment.captured
```

---

## 📦 Products in Catalog

| Product | Price |
|---|---|
| Mechanical Keyboard | ₹3,499 |
| HD Webcam | ₹2,799 |
| USB-C Hub | ₹1,899 |
| Noise-Cancelling Headphones | ₹4,299 |
| Laptop Stand | ₹1,299 |
| Wireless Mouse | ₹899 |

---

## 🏆 Razorpay Buildathon Track 1

Built for **Track 1: AI Growth & Agentic Commerce** — demonstrating autonomous agent-driven commerce with ONDC-inspired protocols and Razorpay payment infrastructure.
