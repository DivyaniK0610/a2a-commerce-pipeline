"""
app.py — Flask application: ONDC Merchant API + Buyer Agent endpoint + SSE Telemetry
A2A Commerce Pipeline | Razorpay Buildathon Track 1
"""

import os
import json
import hmac
import hashlib
import queue
import threading
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv

from database import (
    init_db, search_items, get_item_by_id,
    check_stock, decrement_stock,
    create_order_record, update_order_status, get_all_orders,
    log_action, get_all_logs
)
from razorpay_client import create_payment_link
from agent import run_agent

load_dotenv()

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret_key_change_me")
CORS(app, origins="*")

# ── SSE Event Queue (broadcast to all connected frontend clients) ──────────────
_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()

GST_RATE = 0.18  # 18% GST


# ─────────────────────────────────────────────────────────────────────────────
# SSE Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _broadcast_sse(event_type: str, data: dict):
    """Pushes a JSON event to ALL connected SSE clients."""
    event_data = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        **data
    }
    msg = f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


@app.route("/api/stream")
def sse_stream():
    """Server-Sent Events endpoint — the right-pane telemetry feed."""
    client_q: queue.Queue = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_queues.append(client_q)

    def generate():
        # Send a welcome ping immediately
        yield f"data: {json.dumps({'event_type': 'connected', 'message': 'Telemetry stream connected', 'timestamp': datetime.utcnow().isoformat() + 'Z'})}\n\n"
        try:
            while True:
                try:
                    msg = client_q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if client_q in _sse_queues:
                    _sse_queues.remove(client_q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# ONDC Merchant API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/search", methods=["POST"])
def ondc_search():
    """
    ONDC /search — intent-based catalog lookup.
    Request:  { "intent": { "item": { "descriptor": { "name": "keyboard" } } } }
    Response: { "catalog": [ { id, name, price, stock_count, ... } ] }
    """
    body = request.get_json(force=True, silent=True) or {}
    txn_id = str(uuid.uuid4())

    # Extract intent query
    try:
        query = body["intent"]["item"]["descriptor"]["name"]
    except (KeyError, TypeError):
        error_resp = {
            "error": {
                "type": "SCHEMA-ERROR",
                "code": "30001",
                "message": "Invalid ONDC /search payload. Expected intent.item.descriptor.name"
            }
        }
        log_action(txn_id, "beckn_search", body, "error")
        _broadcast_sse("ondc_search", {"endpoint": "/api/search", "request": body, "response": error_resp, "status": "error"})
        return jsonify(error_resp), 400

    # Search inventory
    items = search_items(query)

    response_body = {
        "context": {
            "action": "search",
            "transaction_id": txn_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        },
        "catalog": [
            {
                "id": item["item_id"],
                "name": item["name"],
                "description": item["description"],
                "price": item["price"],
                "stock_count": item["stock_count"],
                "category": item["category"]
            }
            for item in items
        ]
    }

    status = "success" if items else "empty"
    log_action(txn_id, "beckn_search", {"request": body, "response": response_body}, status)
    _broadcast_sse("ondc_search", {
        "endpoint": "/api/search",
        "query": query,
        "request": body,
        "response": response_body,
        "status": status,
        "results_count": len(items)
    })

    return jsonify(response_body), 200


@app.route("/api/select", methods=["POST"])
def ondc_select():
    """
    ONDC /select — stock validation + GST quote generation.
    Request:  { "order": { "items": [ { "id": "uuid", "quantity": 2 } ] } }
    Response: { "quote": { "price": { "base", "gst_18", "total" }, ... } }
             OR { "error": { "type": "DOMAIN-ERROR", "code": "40002", "message": "..." } }
    """
    body = request.get_json(force=True, silent=True) or {}
    txn_id = str(uuid.uuid4())

    # ── Authentication ────────────────────────────────────────────────────────
    agent_key = os.getenv("A2A_AGENT_KEY")
    if agent_key and request.headers.get("X-Agent-Auth") != agent_key:
        error_resp = {"error": {"type": "AUTH-ERROR", "code": "401", "message": "Unauthorized Agent"}}
        log_action(txn_id, "beckn_select", body, "unauthorized")
        return jsonify(error_resp), 401

    # Extract item and quantity
    try:
        order_item = body["order"]["items"][0]
        item_id = order_item["id"]
        quantity = int(order_item["quantity"])
        if quantity < 1:
            raise ValueError("Quantity must be >= 1")
    except (KeyError, TypeError, ValueError, IndexError) as e:
        error_resp = {
            "error": {
                "type": "SCHEMA-ERROR",
                "code": "30002",
                "message": f"Invalid /select payload: {str(e)}"
            }
        }
        log_action(txn_id, "beckn_select", body, "schema_error")
        _broadcast_sse("ondc_select", {"endpoint": "/api/select", "request": body, "response": error_resp, "status": "schema_error"})
        return jsonify(error_resp), 400

    # Item existence check
    item = get_item_by_id(item_id)
    if not item:
        error_resp = {
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "40001",
                "message": f"Item '{item_id}' not found in catalog"
            }
        }
        log_action(txn_id, "beckn_select", body, "not_found")
        _broadcast_sse("ondc_select", {"endpoint": "/api/select", "request": body, "response": error_resp, "status": "not_found"})
        return jsonify(error_resp), 404

    # Stock check
    is_available, current_stock = check_stock(item_id, quantity)
    if not is_available:
        error_resp = {
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "40002",
                "message": f"Requested quantity ({quantity}) exceeds available stock. Only {current_stock} unit(s) remaining.",
                "available_stock": current_stock
            }
        }
        log_action(txn_id, "beckn_select", {"request": body, "response": error_resp}, "out_of_stock")
        _broadcast_sse("ondc_select", {
            "endpoint": "/api/select",
            "request": body,
            "response": error_resp,
            "status": "out_of_stock",
            "requested": quantity,
            "available": current_stock
        })
        return jsonify(error_resp), 422

    # Calculate quote with 18% GST and optional bounded discount
    discount_requested = body.get("order", {}).get("discount_request", False)
    base_price = round(item["price"] * quantity, 2)
    gst_amount = round(base_price * GST_RATE, 2)
    discount_amount = 0.0

    # Bounded Negotiation Rule: 5% discount on base price if cart > ₹5000 and requested
    if discount_requested and base_price > 5000:
        discount_amount = round(base_price * 0.05, 2)

    total_price = round(base_price + gst_amount - discount_amount, 2)
    quote_id = str(uuid.uuid4())

    response_body = {
        "context": {
            "action": "select",
            "transaction_id": txn_id,
            "quote_id": quote_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        },
        "quote": {
            "item_id": item_id,
            "item_name": item["name"],
            "quantity": quantity,
            "price": {
                "unit": item["price"],
                "base": base_price,
                "gst_rate": "18%",
                "gst_18": gst_amount,
                "discount": discount_amount,
                "total": total_price,
                "currency": "INR"
            },
            "valid_for_seconds": 300
        }
    }

    log_action(txn_id, "beckn_select", {"request": body, "response": response_body}, "success")
    _broadcast_sse("ondc_select", {
        "endpoint": "/api/select",
        "request": body,
        "response": response_body,
        "status": "success",
        "quote_total": total_price
    })

    return jsonify(response_body), 200


@app.route("/api/init", methods=["POST"])
def ondc_init():
    """
    ONDC /init — creates Razorpay payment link (gated endpoint).
    Request:  { "item_id": "uuid", "quantity": 2, "customer": { name, email, contact } }
    Response: { "payment": { "razorpay_order_id": ..., "payment_link": ..., "amount": ... } }
    """
    body = request.get_json(force=True, silent=True) or {}
    txn_id = str(uuid.uuid4())

    # ── Authentication ────────────────────────────────────────────────────────
    agent_key = os.getenv("A2A_AGENT_KEY")
    if agent_key and request.headers.get("X-Agent-Auth") != agent_key:
        error_resp = {"error": {"type": "AUTH-ERROR", "code": "401", "message": "Unauthorized Agent"}}
        log_action(txn_id, "beckn_init", body, "unauthorized")
        return jsonify(error_resp), 401

    # Extract fields
    try:
        item_id = body["item_id"]
        quantity = int(body["quantity"])
        customer = body.get("customer", {})
        customer_name = customer.get("name", "")
        customer_email = customer.get("email", "")
        customer_contact = customer.get("contact", "")
    except (KeyError, TypeError, ValueError) as e:
        error_resp = {
            "error": {
                "type": "SCHEMA-ERROR",
                "code": "30003",
                "message": f"Invalid /init payload: {str(e)}"
            }
        }
        log_action(txn_id, "beckn_init", body, "schema_error")
        _broadcast_sse("ondc_init", {"endpoint": "/api/init", "request": body, "response": error_resp, "status": "schema_error"})
        return jsonify(error_resp), 400

    # Re-validate stock before creating order (race condition protection)
    item = get_item_by_id(item_id)
    if not item:
        error_resp = {
            "error": {"type": "DOMAIN-ERROR", "code": "40001", "message": "Item not found"}
        }
        log_action(txn_id, "beckn_init", body, "not_found")
        _broadcast_sse("ondc_init", {"endpoint": "/api/init", "request": body, "response": error_resp, "status": "not_found"})
        return jsonify(error_resp), 404

    is_available, current_stock = check_stock(item_id, quantity)
    if not is_available:
        error_resp = {
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "40002",
                "message": f"Stock changed. Only {current_stock} unit(s) available.",
                "available_stock": current_stock
            }
        }
        log_action(txn_id, "beckn_init", body, "out_of_stock")
        _broadcast_sse("ondc_init", {"endpoint": "/api/init", "request": body, "response": error_resp, "status": "out_of_stock"})
        return jsonify(error_resp), 422

    # Re-calculate final amount with GST and optional discount (mirroring /select)
    discount_requested = body.get("discount_request", False)
    base_price = round(item["price"] * quantity, 2)
    gst_amount = round(base_price * GST_RATE, 2)
    discount_amount = 0.0

    if discount_requested and base_price > 5000:
        discount_amount = round(base_price * 0.05, 2)

    total_price = round(base_price + gst_amount - discount_amount, 2)

    # ── Create Razorpay Payment Link ───────────────────────────────────────
    try:
        log_action(txn_id, "razorpay_create_attempt", body, "pending")
        _broadcast_sse("razorpay_create", {
            "endpoint": "/api/init",
            "status": "calling_razorpay",
            "amount": total_price,
            "description": f"{quantity}x {item['name']}"
        })

        rz_link = create_payment_link(
            amount_inr=total_price,
            description=f"A2A Order: {quantity}x {item['name']}",
            customer_name=customer_name,
            customer_email=customer_email,
            customer_contact=customer_contact
        )

        razorpay_order_id = rz_link.get("id", "")
        payment_url = rz_link.get("short_url", rz_link.get("payment_link_url", ""))

    except Exception as e:
        error_resp = {
            "error": {
                "type": "PAYMENT-ERROR",
                "code": "50001",
                "message": f"Razorpay payment link creation failed: {str(e)}"
            }
        }
        log_action(txn_id, "razorpay_create_failed", {"error": str(e)}, "error")
        _broadcast_sse("razorpay_create", {"endpoint": "/api/init", "response": error_resp, "status": "razorpay_error"})
        return jsonify(error_resp), 502

    # ── Decrement stock & save order ───────────────────────────────────────
    decrement_stock(item_id, quantity)
    db_txn_id = create_order_record(item_id, quantity, total_price, razorpay_order_id)

    response_body = {
        "context": {
            "action": "init",
            "transaction_id": txn_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        },
        "order": {
            "id": db_txn_id,
            "item_id": item_id,
            "item_name": item["name"],
            "quantity": quantity,
            "status": "created"
        },
        "payment": {
            "razorpay_order_id": razorpay_order_id,
            "payment_link": payment_url,
            "amount": total_price,
            "currency": "INR",
            "breakdown": {
                "base": base_price,
                "gst_18": gst_amount,
                "total": total_price
            }
        }
    }

    log_action(txn_id, "beckn_init", {"request": body, "response": response_body}, "success")
    _broadcast_sse("ondc_init", {
        "endpoint": "/api/init",
        "request": body,
        "response": response_body,
        "status": "success",
        "payment_link": payment_url,
        "total": total_price
    })

    return jsonify(response_body), 201


# ─────────────────────────────────────────────────────────────────────────────
# Buyer Agent Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    """
    Runs the Groq buyer agent for one user turn.
    Request:  { "message": "I need a mechanical keyboard", "history": [...] }
    Response: { "reply": "...", "tool_calls": [...] }
    """
    body = request.get_json(force=True, silent=True) or {}
    user_message = body.get("message", "").strip()
    history = body.get("history", [])

    if not user_message:
        return jsonify({"error": "message field is required"}), 400

    _broadcast_sse("agent_thinking", {
        "message": f"Processing: \"{user_message[:60]}...\"" if len(user_message) > 60 else f"Processing: \"{user_message}\""
    })

    try:
        result = run_agent(user_message, history)

        # Broadcast agent reply summary to telemetry
        _broadcast_sse("agent_response", {
            "reply_preview": result["reply"][:120] + "..." if len(result["reply"]) > 120 else result["reply"],
            "tools_used": [tc["tool"] for tc in result.get("tool_calls", [])]
        })

        return jsonify(result), 200

    except Exception as e:
        error_msg = f"Agent error: {str(e)}"
        _broadcast_sse("agent_error", {"error": error_msg})
        return jsonify({"error": error_msg}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Utility Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Returns all audit logs for the audit trail demo."""
    logs = get_all_logs()
    # Parse raw_payload JSON strings back to objects for cleaner frontend rendering
    for log in logs:
        try:
            log["raw_payload"] = json.loads(log["raw_payload"])
        except (json.JSONDecodeError, TypeError):
            pass
    return jsonify({"logs": logs, "count": len(logs)}), 200


@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    """Returns current inventory state (useful for the demo)."""
    from database import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory ORDER BY category, name")
    items = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify({"inventory": items, "count": len(items)}), 200


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "A2A Commerce Pipeline",
        "version": "1.0.0",
        "sse_clients": len(_sse_queues)
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Razorpay Webhook
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/webhook/razorpay", methods=["POST"])
def razorpay_webhook():
    """
    Razorpay Webhook endpoint.
    Razorpay POSTs signed events here when payment status changes.
    Verifies HMAC-SHA256 signature before processing.

    Setup:
      1. Run ngrok: ngrok http 5000
      2. Copy the public URL (e.g. https://abc123.ngrok.io)
      3. In Razorpay Dashboard → Settings → Webhooks → Add Webhook
         URL: https://abc123.ngrok.io/api/webhook/razorpay
         Secret: (set RAZORPAY_WEBHOOK_SECRET in .env)
         Events: payment_link.paid, payment.captured
    """
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    raw_body = request.get_data()  # Raw bytes for signature verification

    # ── Signature Verification ─────────────────────────────────────────────────
    if webhook_secret:
        received_sig = request.headers.get("X-Razorpay-Signature", "")
        expected_sig = hmac.new(
            webhook_secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, received_sig):
            print("[WEBHOOK] Signature verification FAILED")
            log_action("webhook", "webhook_signature_failed",
                       {"received": received_sig[:20] + "..."}, "error")
            return jsonify({"error": "Invalid signature"}), 400

    # ── Parse Event ────────────────────────────────────────────────────────────
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    event_type = event.get("event", "unknown")
    payload    = event.get("payload", {})

    print(f"[WEBHOOK] Received event: {event_type}")

    # ── Handle payment_link.paid ───────────────────────────────────────────────
    if event_type == "payment_link.paid":
        payment_link_entity = payload.get("payment_link", {}).get("entity", {})
        payment_entity      = payload.get("payment",      {}).get("entity", {})

        razorpay_link_id = payment_link_entity.get("id", "")
        payment_id       = payment_entity.get("id", "")
        amount_paise     = payment_link_entity.get("amount", 0)
        amount_inr       = amount_paise / 100
        status           = payment_link_entity.get("status", "")

        # Find matching order in DB by razorpay_order_id (stored as plink_xxx)
        from database import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE orders SET status = 'paid' WHERE razorpay_order_id = ?",
            (razorpay_link_id,)
        )
        updated = cur.rowcount
        conn.commit()
        conn.close()

        webhook_data = {
            "event": event_type,
            "razorpay_link_id": razorpay_link_id,
            "payment_id": payment_id,
            "amount_inr": amount_inr,
            "status": status,
            "orders_updated": updated
        }

        log_action("webhook", "payment_link_paid", webhook_data, "success")
        _broadcast_sse("webhook_payment_paid", {
            "event": event_type,
            "payment_id": payment_id,
            "amount_inr": amount_inr,
            "razorpay_link_id": razorpay_link_id,
            "status": "payment_confirmed",
            "message": f"Payment of Rs.{amount_inr:.2f} confirmed! Payment ID: {payment_id}"
        })

        print(f"[WEBHOOK] Payment confirmed: {payment_id} | Rs.{amount_inr:.2f} | Orders updated: {updated}")
        return jsonify({"status": "ok", "payment_id": payment_id}), 200

    # ── Handle payment.captured ────────────────────────────────────────────────
    elif event_type in ("payment.captured", "payment.authorized"):
        payment_entity = payload.get("payment", {}).get("entity", {})
        payment_id     = payment_entity.get("id", "")
        amount_paise   = payment_entity.get("amount", 0)
        amount_inr     = amount_paise / 100
        order_id       = payment_entity.get("order_id", "")

        webhook_data = {
            "event": event_type,
            "payment_id": payment_id,
            "order_id": order_id,
            "amount_inr": amount_inr
        }

        log_action("webhook", "payment_captured", webhook_data, "success")
        _broadcast_sse("webhook_payment_paid", {
            "event": event_type,
            "payment_id": payment_id,
            "amount_inr": amount_inr,
            "status": "payment_confirmed",
            "message": f"Payment captured: Rs.{amount_inr:.2f} | ID: {payment_id}"
        })

        print(f"[WEBHOOK] Payment captured: {payment_id} | Rs.{amount_inr:.2f}")
        return jsonify({"status": "ok", "payment_id": payment_id}), 200

    # ── Acknowledge other events without processing ─────────────────────────────
    else:
        print(f"[WEBHOOK] Unhandled event type: {event_type}")
        return jsonify({"status": "received", "event": event_type}), 200



if __name__ == "__main__":
    print("=" * 60)
    print("  A2A Commerce Pipeline — Razorpay Buildathon Track 1")
    print("=" * 60)
    init_db()
    print("[Flask] Starting server on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True, use_reloader=False)
