
-- Nistula Unified Messaging Platform — PostgreSQL Schema
-- Design principles:
--   1. One guest, one record — deduplicated across all channels
--   2. All messages in a single table with source tracking
--   3. Conversations are the unit of context for AI prompting
--   4. Full AI audit trail: query type, confidence, who sent what
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- GUESTS
-- One row per unique guest, regardless of which channel they
-- first contacted us from. Deduplication is done at application
-- layer (e.g. phone number normalisation, email matching).
CREATE TABLE guests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name       TEXT NOT NULL,

    phone           TEXT UNIQUE,      
    email           TEXT UNIQUE,
   
    whatsapp_id     TEXT UNIQUE,
    booking_com_id  TEXT UNIQUE,
    airbnb_id       TEXT UNIQUE,
    instagram_id    TEXT UNIQUE,
    -- Metadata
    first_contact_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_contact_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    preferred_language  TEXT DEFAULT 'en',
    notes               TEXT,             -- Agent-added guest notes
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup by any identifier
CREATE INDEX idx_guests_phone        ON guests (phone)        WHERE phone IS NOT NULL;
CREATE INDEX idx_guests_email        ON guests (email)        WHERE email IS NOT NULL;
CREATE INDEX idx_guests_whatsapp_id  ON guests (whatsapp_id)  WHERE whatsapp_id IS NOT NULL;
-- PROPERTIES
-- Simple reference table for now; expandable
CREATE TABLE properties (
    id          TEXT PRIMARY KEY,         
    name        TEXT NOT NULL,
    location    TEXT,
    max_guests  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- RESERVATIONS
CREATE TABLE reservations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_ref     TEXT UNIQUE NOT NULL,   -- e.g. NIS-2024-0891
    guest_id        UUID NOT NULL REFERENCES guests (id) ON DELETE RESTRICT,
    property_id     TEXT NOT NULL REFERENCES properties (id) ON DELETE RESTRICT,
    check_in_date   DATE NOT NULL,
    check_out_date  DATE NOT NULL,
    num_adults      INTEGER NOT NULL DEFAULT 1,
    num_children    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'confirmed'
                        CHECK (status IN ('enquiry','confirmed','cancelled','completed')),
    total_amount    NUMERIC(12, 2),
    currency        TEXT DEFAULT 'INR',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_dates CHECK (check_out_date > check_in_date)
);

CREATE INDEX idx_reservations_guest      ON reservations (guest_id);
CREATE INDEX idx_reservations_property   ON reservations (property_id);
CREATE INDEX idx_reservations_booking_ref ON reservations (booking_ref);
-- CONVERSATIONS
CREATE TABLE conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guest_id        UUID NOT NULL REFERENCES guests (id) ON DELETE RESTRICT,
    reservation_id  UUID REFERENCES reservations (id) ON DELETE SET NULL,
    property_id     TEXT REFERENCES properties (id) ON DELETE SET NULL,
    source          TEXT NOT NULL
                        CHECK (source IN ('whatsapp','booking_com','airbnb','instagram','direct')),
    status          TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','resolved','escalated','snoozed')),
    subject         TEXT,                  -- Optional human label
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    assigned_agent  TEXT,                
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversations_guest         ON conversations (guest_id);
CREATE INDEX idx_conversations_reservation   ON conversations (reservation_id);
CREATE INDEX idx_conversations_status        ON conversations (status);

-- MESSAGES


CREATE TYPE message_direction AS ENUM ('inbound', 'outbound');

CREATE TYPE reply_disposition AS ENUM (
    'ai_auto_sent',    -- Confidence >= 0.85, sent without human review
    'ai_agent_edited', -- AI drafted, agent modified before sending
    'agent_written',   -- Human wrote the reply from scratch
    'ai_draft_only'    -- AI drafted but not yet actioned (pending review)
);

CREATE TYPE query_type AS ENUM (
    'pre_sales_availability',
    'pre_sales_pricing',
    'post_sales_checkin',
    'special_request',
    'complaint',
    'general_enquiry'
);

CREATE TYPE action_taken AS ENUM (
    'auto_send',
    'agent_review',
    'escalate'
);

CREATE TABLE messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    direction           message_direction NOT NULL,

    -- Content
    body                TEXT NOT NULL,
    -- For outbound: the original AI draft (before any agent edits)
    ai_draft            TEXT,

    -- AI analysis — populated on inbound messages only
    query_type          query_type,
    ai_confidence_score NUMERIC(5, 4)
                            CHECK (ai_confidence_score BETWEEN 0 AND 1),
    ai_action_taken     action_taken,

    -- Disposition — how was the outbound reply handled?
    reply_disposition   reply_disposition,

    -- Sender metadata
    sent_by_agent       TEXT,              -- Agent username; NULL = AI or guest
    channel_message_id  TEXT,             -- ID from WhatsApp/Booking.com/etc for dedup
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevent duplicate inbound messages from the same channel
    UNIQUE (conversation_id, channel_message_id)
);

CREATE INDEX idx_messages_conversation   ON messages (conversation_id);
CREATE INDEX idx_messages_sent_at        ON messages (sent_at);
CREATE INDEX idx_messages_query_type     ON messages (query_type) WHERE query_type IS NOT NULL;
CREATE INDEX idx_messages_confidence     ON messages (ai_confidence_score) WHERE ai_confidence_score IS NOT NULL;
-- For pattern detection (e.g. repeated complaint types per property)
CREATE INDEX idx_messages_direction_type ON messages (direction, query_type);

-- ISSUE PATTERNS
CREATE MATERIALIZED VIEW property_complaint_patterns AS
SELECT
    c.property_id,
    m.query_type,
    -- Extract complaint keyword groups from message body
    COUNT(*)                        AS complaint_count,
    MAX(m.sent_at)                  AS last_seen,
    MIN(m.sent_at)                  AS first_seen,
    ARRAY_AGG(DISTINCT m.id)        AS message_ids
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE m.direction = 'inbound'
  AND m.query_type = 'complaint'
  AND m.sent_at >= NOW() - INTERVAL '90 days'
GROUP BY c.property_id, m.query_type
HAVING COUNT(*) >= 2;             -- Surface patterns, not one-offs

CREATE INDEX idx_complaint_patterns_property ON property_complaint_patterns (property_id);

-- DESIGN DECISIONS

/*
HARDEST DECISION: Guest identity across different platforms.

A guest may contact Nistula through WhatsApp before booking,
Booking.com during the stay, and Instagram later for another trip.

The challenge was deciding whether these should be stored as:
- one guest record
OR
- separate records for each platform.

I chose to keep one unified guest profile because:
- Guest history stays in one place
- Preferences and notes are easier to track
- The company can recognise repeat guests
- Reporting becomes more accurate

For example:
If Rahul books once through Booking.com and later contacts
through WhatsApp, the system should still recognise him as
the same guest.

The difficult part is matching guests correctly across
different platforms because contact details may change.

To solve this:
- Phone number is mainly used for WhatsApp
- Email is mainly used for Booking.com and Airbnb
- Instagram may require manual matching

In some unclear cases, human review may still be needed.

The other option was creating separate profiles for every
platform and linking them together later. That design is
more flexible technically, but harder to manage and explain.
For a hospitality platform like Nistula, keeping one clean
guest profile is more useful.

SECOND HARDEST DECISION: Where to store AI-related data.

I stored:
- confidence score
- query type
- reply action

directly inside the messages table.

I chose this because:
- Queries become simpler
- Fewer database joins are needed
- The schema is easier to understand
- Faster for analytics and reporting

If the AI system becomes more advanced later
(multiple models, prompt testing, AI experiments),
then a separate AI events table would make more sense.
*/
