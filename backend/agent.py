"""
agent.py — Groq-powered Buyer Agent with ONDC Tool Calling
A2A Commerce Pipeline | Razorpay Buildathon Track 1

The agent is STRICTLY restricted to calling ONDC endpoints via tools.
It cannot invent prices or bypass the /select → /init gating.
"""

import os
import json
import requests
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ── Groq client ───────────────────────────────────────────────────────────────
_groq = None

def get_groq_client() -> Groq:
    global _groq
    if _groq is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY must be set in .env")
        _groq = Groq(api_key=api_key)
    return _groq


# ── Base URL for local Flask endpoints ───────────────────────────────────────
MERCHANT_API_BASE = "http://127.0.0.1:5000/api"

# ── ONDC Tool Definitions (passed to Groq) ────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": (
                "Search the merchant catalog for products matching the user's intent. "
                "Use this FIRST before any other tool. Returns a list of available items with IDs and prices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The product name or keyword to search for (e.g. 'keyboard', 'webcam')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_item",
            "description": (
                "Lock in a quote for a specific item and quantity. "
                "Checks stock availability and returns an exact price breakdown including 18% GST. "
                "You MUST show the full quote breakdown to the user BEFORE calling init_order. "
                "If this returns an error, inform the user about the stock limitation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The exact item_id from the search_catalog result"
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "The number of units the user wants to purchase",
                        "minimum": 1
                    }
                },
                "required": ["item_id", "quantity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "init_order",
            "description": (
                "Creates a Razorpay payment order and returns a payment link. "
                "Call this when the user provides their name, email, and phone number — "
                "that is their confirmation to pay. "
                "You MUST call select_item first to confirm the item_id and stock, "
                "then call this tool immediately with the customer details. "
                "Do NOT ask for confirmation again if the user already provided their details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The item_id from the confirmed quote"
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "The confirmed quantity"
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Customer's full name"
                    },
                    "customer_email": {
                        "type": "string",
                        "description": "Customer's email address"
                    },
                    "customer_contact": {
                        "type": "string",
                        "description": "Customer's phone number with country code (e.g. +919876543210)"
                    }
                },
                "required": ["item_id", "quantity", "customer_name", "customer_email", "customer_contact"]
            }
        }
    }
]

# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an autonomous ONDC Buyer Agent helping users purchase products from the merchant catalog.

STRICT RULES — follow these exactly:
1. To find products, ALWAYS call search_catalog first. Never invent product IDs or prices.
2. To get a price quote, ALWAYS call select_item. Show the quote in this format:
   📦 Item: [name] × [quantity]
   💰 Base Price: ₹[base]
   📊 GST (18%): ₹[gst]
   ✅ Total: ₹[total]
   Then ask: "Shall I proceed? Please share your name, email, and phone number."
3. PAYMENT TRIGGER — When the user provides their name AND email AND phone number in any message:
   - This is EXPLICIT CONFIRMATION to pay. Do NOT ask again.
   - Call search_catalog to get the item_id, then call select_item to confirm stock.
   - Then IMMEDIATELY call init_order with their details. No more questions.
4. If select_item returns a stock error, tell the user the available stock and ask if they want that quantity.
5. After init_order succeeds, show: 🔗 Payment Link: [short_url]
6. Be concise and transparent about each step."""


# ── Tool Executor ─────────────────────────────────────────────────────────────

def _execute_tool(tool_name: str, tool_args: dict) -> str:
    """Executes the appropriate ONDC HTTP call and returns the JSON response as string."""
    try:
        if tool_name == "search_catalog":
            payload = {"intent": {"item": {"descriptor": {"name": tool_args["query"]}}}}
            resp = requests.post(f"{MERCHANT_API_BASE}/search", json=payload, timeout=10)
            return json.dumps(resp.json(), ensure_ascii=False)

        elif tool_name == "select_item":
            payload = {
                "order": {
                    "items": [{"id": tool_args["item_id"], "quantity": tool_args["quantity"]}]
                }
            }
            resp = requests.post(f"{MERCHANT_API_BASE}/select", json=payload, timeout=10)
            return json.dumps(resp.json(), ensure_ascii=False)

        elif tool_name == "init_order":
            payload = {
                "item_id": tool_args["item_id"],
                "quantity": tool_args["quantity"],
                "customer": {
                    "name": tool_args.get("customer_name", ""),
                    "email": tool_args.get("customer_email", ""),
                    "contact": tool_args.get("customer_contact", "")
                }
            }
            resp = requests.post(f"{MERCHANT_API_BASE}/init", json=payload, timeout=15)
            return json.dumps(resp.json(), ensure_ascii=False)

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Cannot connect to Merchant API. Is Flask running?"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Main Agent Runner ─────────────────────────────────────────────────────────

def run_agent(user_message: str, conversation_history: list[dict]) -> dict:
    """
    Runs the Groq buyer agent for one user turn.

    Args:
        user_message: The latest message from the user.
        conversation_history: Prior messages in [{"role": ..., "content": ...}] format.

    Returns:
        {
            "reply": str,            # Final text reply to show in chat
            "tool_calls": [          # List of tool calls made this turn
                {
                    "tool": str,
                    "args": dict,
                    "result": dict
                }
            ]
        }
    """
    client = get_groq_client()

    # Build messages for this turn
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    tool_calls_log = []

    # ── Agentic loop: keep calling Groq until no more tool calls ─────────────
    while True:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=2048
        )

        assistant_msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # ── Serialize assistant message back into messages list ───────────────
        # Use model_dump() for Groq SDK 1.7.0 compatibility
        assistant_dict = {
            "role": "assistant",
            "content": assistant_msg.content or "",
        }
        if assistant_msg.tool_calls:
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in assistant_msg.tool_calls
            ]
        messages.append(assistant_dict)

        # ── If no tool calls → final text response ────────────────────────────
        if not assistant_msg.tool_calls:
            reply_text = assistant_msg.content or ""
            # Fallback if model returned empty content
            if not reply_text.strip():
                reply_text = "I searched the catalog. Please ask me what you'd like to buy."
            return {
                "reply": reply_text,
                "tool_calls": tool_calls_log
            }

        # ── Execute each tool call ────────────────────────────────────────────
        for tc in assistant_msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            tool_result_str = _execute_tool(tool_name, tool_args)
            tool_result_dict = {}
            try:
                tool_result_dict = json.loads(tool_result_str)
            except Exception:
                tool_result_dict = {"raw": tool_result_str}

            # Log the tool call for telemetry
            tool_calls_log.append({
                "tool": tool_name,
                "args": tool_args,
                "result": tool_result_dict
            })

            # Feed result back into messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result_str
            })
