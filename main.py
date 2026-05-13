"""
Nistula Guest Message Handler
FastAPI webhook that receives guest messages, normalises them,
drafts a reply via Claude, and returns a confidence-scored response.
"""

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Nistula Message Handler", version="1.0.0")

# ─── Constants ────────────────────────────────────────────────────────────────

VALID_SOURCES = {"whatsapp", "booking_com", "airbnb", "instagram", "direct"}

QUERY_TYPES = {
    "pre_sales_availability",
    "pre_sales_pricing",
    "post_sales_checkin",
    "special_request",
    "complaint",
    "general_enquiry",
}

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# ─── Mock property database ───────────────────────────────────────────────────

PROPERTY_CONTEXT = {
    "villa-b1": """
Property: Villa B1, Assagao, North Goa
Bedrooms: 3 | Max guests: 6 | Private pool: Yes
Check-in: 2pm | Check-out: 11am
Base rate: INR 18,000 per night (up to 4 guests)
Extra guest: INR 2,000 per night per person
WiFi password: Nistula@2024
Caretaker: Available 8am to 10pm
Chef on call: Yes, pre-booking required
Availability April 20-24: Available
Cancellation: Free up to 7 days before check-in
""".strip()
}

DEFAULT_PROPERTY_CONTEXT = "Property details not found. Use general hospitality best practices."

# ─── Pydantic models ──────────────────────────────────────────────────────────

class InboundMessage(BaseModel):
    source: str
    guest_name: str
    message: str
    timestamp: str
    booking_ref: Optional[str] = None
    property_id: Optional[str] = None

    @validator("source")
    def source_must_be_valid(cls, v):
        if v not in VALID_SOURCES:
            raise ValueError(f"source must be one of {VALID_SOURCES}")
        return v


class NormalisedMessage(BaseModel):
    message_id: str
    source: str
    guest_name: str
    message_text: str
    timestamp: str
    booking_ref: Optional[str]
    property_id: Optional[str]
    query_type: str


class WebhookResponse(BaseModel):
    message_id: str
    query_type: str
    drafted_reply: str
    confidence_score: float
    action: str


# ─── Query classifier ─────────────────────────────────────────────────────────

QUERY_KEYWORDS = {
    "complaint": [
        "not working", "broken", "unacceptable", "terrible", "awful",
        "refund", "complaint", "no hot water", "no water", "no ac",
        "ac not", "dirty", "disgusting", "disappointed", "demand",
        "worst", "horrible", "unhappy", "not happy",
    ],
    "post_sales_checkin": [
        "check in", "check-in", "check out", "check-out", "wifi",
        "wi-fi", "password", "key", "access", "caretaker", "arrival",
        "directions", "address", "how do i", "where do i",
    ],
    "special_request": [
        "early check", "late check", "airport", "transfer", "taxi",
        "pickup", "chef", "cook", "food", "arrange", "request",
        "birthday", "anniversary", "decoration", "special",
    ],
    "pre_sales_availability": [
        "available", "availability", "dates", "open", "free",
        "book for", "stay from", "arrive on",
    ],
    "pre_sales_pricing": [
        "rate", "price", "cost", "how much", "pricing", "per night",
        "charge", "fee", "tariff", "inr", "rupee",
    ],
    "general_enquiry": [
        "pet", "dog", "cat", "parking", "pool", "amenities",
        "facilities", "near", "distance", "restaurant", "beach",
        "do you", "is there", "can we",
    ],
}


def classify_query(message: str) -> str:
    """
    Rule-based classifier: score each category by keyword hits.
    Complaint always wins ties (safety-first).
    Falls back to general_enquiry.
    """
    text = message.lower()
    scores: dict[str, int] = {qt: 0 for qt in QUERY_KEYWORDS}

    for query_type, keywords in QUERY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[query_type] += 1

    # Complaints get priority — any hit wins
    if scores["complaint"] > 0:
        return "complaint"

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "general_enquiry"


# ─── Normaliser ───────────────────────────────────────────────────────────────

def normalise_message(raw: InboundMessage) -> NormalisedMessage:
    """Convert raw webhook payload into the unified schema."""
    return NormalisedMessage(
        message_id=str(uuid.uuid4()),
        source=raw.source,
        guest_name=raw.guest_name,
        message_text=raw.message.strip(),
        timestamp=raw.timestamp,
        booking_ref=raw.booking_ref,
        property_id=raw.property_id,
        query_type=classify_query(raw.message),
    )


# ─── Confidence scorer ────────────────────────────────────────────────────────

def compute_confidence(
    query_type: str,
    has_property_context: bool,
    message_length: int,
    has_booking_ref: bool,
) -> float:
    """
    Confidence is a weighted composite of four signals:

    1. Query type certainty (0.40 weight)
       Factual queries (availability, check-in info) score high because the
       answer is deterministic from the property data sheet.
       Complaints score low — they need human empathy and judgment.

    2. Property context available (0.25 weight)
       If we found a matching property record we can give a grounded reply.
       Unknown properties force the model to hedge, lowering confidence.

    3. Message clarity proxy (0.20 weight)
       Longer messages (up to ~120 chars) tend to be more specific and
       therefore easier to answer well. Very short messages are ambiguous.

    4. Booking reference present (0.15 weight)
       A booking ref means the guest is post-sales; we have their context.
    """
    # 1. Query type base score
    type_scores = {
        "post_sales_checkin": 0.95,
        "pre_sales_availability": 0.90,
        "pre_sales_pricing": 0.88,
        "general_enquiry": 0.80,
        "special_request": 0.70,
        "complaint": 0.45,
    }
    type_score = type_scores.get(query_type, 0.70)

    # 2. Property context
    context_score = 1.0 if has_property_context else 0.50

    # 3. Message clarity (normalised to [0, 1], capped at 120 chars)
    clarity_score = min(message_length / 120, 1.0)

    # 4. Booking reference
    ref_score = 1.0 if has_booking_ref else 0.60

    confidence = (
        0.40 * type_score
        + 0.25 * context_score
        + 0.20 * clarity_score
        + 0.15 * ref_score
    )

    # Complaints are escalated regardless — cap at 0.59 so action = escalate
    if query_type == "complaint":
        confidence = min(confidence, 0.59)

    return round(confidence, 4)


def resolve_action(confidence: float, query_type: str) -> str:
    if query_type == "complaint":
        return "escalate"
    if confidence >= 0.85:
        return "auto_send"
    if confidence >= 0.60:
        return "agent_review"
    return "escalate"


# ─── Claude API call ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a warm, professional guest relations assistant for Nistula, 
a luxury villa rental company in Goa, India. 

Your job is to draft short, friendly, helpful replies to guest messages. 

Guidelines:
- Address the guest by first name
- Be warm but concise (3-5 sentences is ideal)
- Use the property information provided to give accurate, specific answers
- For availability and pricing, give direct numbers from the context
- For complaints, express genuine empathy first, then practical next steps
- End with an invitation to ask more if needed
- Write in a conversational, human tone — not corporate-speak
- Do NOT fabricate information not present in the context
"""


async def draft_reply_with_claude(
    normalised: NormalisedMessage,
    property_context: str,
) -> str:
    """Call Claude API and return the drafted reply text."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    first_name = normalised.guest_name.split()[0]

    user_prompt = f"""
Property context:
{property_context}

Guest details:
- Name: {normalised.guest_name}
- Booking reference: {normalised.booking_ref or 'Not provided'}
- Source channel: {normalised.source}
- Query type: {normalised.query_type}

Guest message:
"{normalised.message_text}"

Draft a reply to {first_name} addressing their query using the property context above.
""".strip()

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(CLAUDE_API_URL, json=payload, headers=headers)

    if response.status_code != 200:
        print("CLAUDE ERROR RESPONSE:")
        print(response.text)

        raise HTTPException(
            status_code=502,
            detail=response.text,
        )

    data = response.json()
    return data["content"][0]["text"].strip()


# ─── Webhook endpoint ─────────────────────────────────────────────────────────

@app.post("/webhook/message", response_model=WebhookResponse)
async def handle_message(raw: InboundMessage):
    """
    Main webhook endpoint.
    1. Normalise inbound payload
    2. Classify query type
    3. Fetch property context
    4. Draft reply via Claude
    5. Score confidence and determine action
    6. Return structured response
    """
    logger.info("Received message from %s via %s", raw.guest_name, raw.source)

    # Normalise
    normalised = normalise_message(raw)
    logger.info("Classified as: %s | message_id: %s", normalised.query_type, normalised.message_id)

    # Property context
    property_context = PROPERTY_CONTEXT.get(
        normalised.property_id or "", DEFAULT_PROPERTY_CONTEXT
    )
    has_property_context = normalised.property_id in PROPERTY_CONTEXT

    # Draft reply
    try:
        drafted_reply = await draft_reply_with_claude(normalised, property_context)
    except Exception as exc:
        logger.error("Failed to draft reply: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Score
    confidence = compute_confidence(
        query_type=normalised.query_type,
        has_property_context=has_property_context,
        message_length=len(normalised.message_text),
        has_booking_ref=bool(normalised.booking_ref),
    )
    action = resolve_action(confidence, normalised.query_type)

    logger.info(
        "Reply drafted | confidence=%.4f | action=%s", confidence, action
    )

    return WebhookResponse(
        message_id=normalised.message_id,
        query_type=normalised.query_type,
        drafted_reply=drafted_reply,
        confidence_score=confidence,
        action=action,
    )


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ─── Error handlers ───────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
