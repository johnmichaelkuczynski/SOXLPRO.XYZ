ALTER TABLE user_access
    ADD COLUMN IF NOT EXISTS last_stripe_event_created BIGINT;

ALTER TABLE stripe_webhook_events
    ADD COLUMN IF NOT EXISTS event_created BIGINT;

UPDATE stripe_webhook_events
SET event_created = EXTRACT(EPOCH FROM processed_at)::BIGINT
WHERE event_created IS NULL;

ALTER TABLE stripe_webhook_events
    ALTER COLUMN event_created SET NOT NULL;

CREATE TABLE IF NOT EXISTS anonymous_access (
    visitor_id UUID PRIMARY KEY,
    free_actions INTEGER NOT NULL DEFAULT 0 CHECK (free_actions >= 0),
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);