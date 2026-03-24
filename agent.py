"""
agent.py — WhatsApp CRM Agent
Receives webhook from whatsapp.js, uses Claude to classify CRM relevance,
posts to ETHOS CRM if confidence > 0.75, logs every decision to agent.log.
Never crashes — all errors are caught and logged.
"""

import os
import json
import logging
import traceback
from datetime import datetime, timezone

import anthropic
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify

# ── Config ─────────────────────────────────────────────────────────────────────
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ETHOS_API_URL     = os.getenv("ETHOS_API_URL", "")
ETHOS_API_KEY     = os.getenv("ETHOS_API_KEY", "")
CRM_THRESHOLD     = float(os.getenv("CRM_THRESHOLD", "0.75"))
PORT              = int(os.getenv("AGENT_PORT", "8000"))
SEND_URL          = "http://localhost:8001/send"

# ── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("agent.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── Claude client ───────────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Flask app ───────────────────────────────────────────────────────────────────
app = Flask(__name__)


# ── Claude classification ───────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are NUCLEUS CRM Agent, an AI assistant deployed by LinkBridge as part of the NUCLEUS Agent-as-a-Service platform for Engineer-to-Order (ETO) manufacturing companies.

YOUR IDENTITY
You are not a general-purpose assistant. You are not a chatbot.
You are a specialist cognitive agent with one focused mission: capture commercially relevant information from WhatsApp conversations and keep the ETHOS CRM system accurate and up to date.

YOUR SPECIALTY
You deeply understand Engineer-to-Order manufacturing. You know that:
- Every ETO project is unique, no two orders are the same
- Commercial conversations in ETO involve bespoke products, long lead times, complex specifications, and high contract values
- ETO clients discuss requirements in technical language — flood defence, blast doors, pressure vessels, structural steel, custom fabrication
- A single WhatsApp message can represent a £50,000–£500,000 opportunity if correctly captured

YOUR FOCUS
You extract and structure the following from every message:
  NEW_CONTACT    — a person or company mentioned for the first time
  NEW_OPPORTUNITY — a client expressing interest in a product or service
  QUOTE_UPDATE   — a discussion about pricing, value, or commercial terms
  MEETING_NOTE   — outcome of a call, site visit, or client meeting
  FOLLOW_UP      — a committed next action with a person, company, or deadline
  ORDER_UPDATE   — confirmation, delay, or change to an existing order

Everything outside these categories is not your concern. Ignore it.

YOUR RULES
1. Only act when confident. Confidence threshold: 0.75 or above. Below 0.75 — log for human review, do not post.
2. Never guess a company name, contact name, or monetary value. If not clearly stated, mark as null.
3. Never modify or delete existing ETHOS records. You only create. Humans correct.
4. Every decision — acted on or skipped — must be written to the audit log. No silent failures.
5. If asked something outside your CRM specialty, respond warmly but redirect. You are friendly, confident, and a little like a sharp sales professional — energetic, concise, and commercially minded. You can introduce yourself, explain what you do, and show enthusiasm for helping the team win deals. But always bring it back to your mission.

Respond ONLY with a JSON object — no markdown, no explanation:
{
  "is_crm": true | false,
  "confidence": 0.0 to 1.0,
  "category": "NEW_CONTACT" | "NEW_OPPORTUNITY" | "QUOTE_UPDATE" | "MEETING_NOTE" | "FOLLOW_UP" | "ORDER_UPDATE" | "none",
  "contact_name": "extracted name or null",
  "company_name": "extracted company or null",
  "value": "extracted monetary value or null",
  "summary": "one-sentence summary of the CRM action required, or null",
  "reply": "always reply in a warm, confident, sales-professional tone — 2-4 sentences max. If CRM-relevant, confirm what you captured and what action you took (e.g. logged to ETHOS). If someone asks who you are or what you do, give an energetic self-introduction: you are NUCLEUS, the CRM agent built by LinkBridge for ETO manufacturers, your job is making sure no lead, quote, or follow-up ever falls through the cracks. If asked something outside your scope, be friendly about it but redirect back to your mission."
}"""


def send_reply(chat_id: str, message: str):
    """Send a message back to the originating WhatsApp group via whatsapp.js."""
    try:
        requests.post(SEND_URL, json={"chatId": chat_id, "message": message}, timeout=5)
    except Exception as exc:
        log.warning(f"Could not send reply: {exc}")


def classify_message(sender: str, body: str) -> dict:
    """Ask Claude whether this message is CRM-relevant."""
    user_content = f"Sender: {sender}\nMessage: {body}"
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[-2] if raw.count("```") >= 2 else raw
        raw = raw.lstrip("json").strip()
    return json.loads(raw)


# ── ETHOS CRM post ──────────────────────────────────────────────────────────────
def post_to_ethos(payload: dict, classification: dict) -> bool:
    """POST a CRM record to ETHOS. Returns True on success.
    Strictly uses POST only — never GET/PUT/PATCH/DELETE regardless of config.
    """
    # Safety guard: only allow the configured base URL, never derived paths
    safe_url = ETHOS_API_URL.rstrip("/")
    if not safe_url.startswith("http"):
        raise ValueError(f"ETHOS_API_URL looks invalid: {safe_url!r}")

    crm_record = {
        "source":       "whatsapp",
        "platform":     "NUCLEUS",
        "sender":       payload.get("sender"),
        "group":        payload.get("group"),
        "message":      payload.get("body"),
        "timestamp":    payload.get("timestamp"),
        "category":     classification.get("category"),
        "confidence":   classification.get("confidence"),
        "contact_name": classification.get("contact_name"),
        "company_name": classification.get("company_name"),
        "value":        classification.get("value"),
        "summary":      classification.get("summary"),
        "received_at":  datetime.now(timezone.utc).isoformat(),
    }
    resp = requests.post(
        ETHOS_API_URL,
        json=crm_record,
        headers={
            "Authorization": f"Bearer {ETHOS_API_KEY}",
            "Content-Type":  "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return True


# ── Webhook endpoint ────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        sender  = payload.get("sender", "unknown")
        body    = payload.get("body", "")
        group   = payload.get("group", "")
        chat_id = payload.get("chatId", "")

        if not body:
            log.warning("Empty message body received — skipping.")
            return jsonify({"status": "skipped", "reason": "empty body"}), 200

        log.info(f"Received | group={group!r} sender={sender!r} body={body[:80]!r}")

        # ── Step 1: Classify with Claude ──────────────────────────────────────
        try:
            classification = classify_message(sender, body)
        except (json.JSONDecodeError, KeyError, anthropic.APIError) as exc:
            log.error(f"Claude classification failed: {exc}")
            return jsonify({"status": "error", "reason": "classification_failed"}), 200

        confidence = classification.get("confidence", 0.0)
        is_crm     = classification.get("is_crm", False)
        category   = classification.get("category", "none")
        summary    = classification.get("summary", "N/A")

        log.info(
            f"Classified | is_crm={is_crm} confidence={confidence:.2f} "
            f"category={category!r} summary={summary!r}"
        )

        # ── Step 2: Send reply back to the group ──────────────────────────────
        reply = classification.get("reply", "")
        if reply and reply.strip().upper() != "N/A" and chat_id:
            send_reply(chat_id, reply)
            log.info(f"Replied | {reply!r}")

        # ── Step 3: Post to ETHOS if above threshold ───────────────────────────
        if is_crm and confidence >= CRM_THRESHOLD:
            if not ETHOS_API_URL:
                log.warning("ETHOS_API_URL not set — skipping CRM post.")
            else:
                try:
                    post_to_ethos(payload, classification)
                    log.info(f"Posted to ETHOS CRM | category={category!r}")
                except requests.HTTPError as exc:
                    log.error(f"ETHOS HTTP error: {exc.response.status_code} — {exc.response.text[:200]}")
                except requests.RequestException as exc:
                    log.error(f"ETHOS request failed: {exc}")
        else:
            log.info(f"Skipped CRM post | confidence={confidence:.2f} < threshold={CRM_THRESHOLD}")

        return jsonify({
            "status":     "ok",
            "is_crm":     is_crm,
            "confidence": confidence,
            "category":   category,
        }), 200

    except Exception:
        log.error(f"Unhandled exception in /webhook:\n{traceback.format_exc()}")
        return jsonify({"status": "error", "reason": "internal_error"}), 200  # 200 so bridge doesn't retry


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ── Entry point ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info(f"Nucleus WhatsApp CRM Agent starting on port {PORT}")
    log.info(f"CRM confidence threshold: {CRM_THRESHOLD}")
    log.info(f"ETHOS CRM URL: {ETHOS_API_URL or '(not set)'}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
