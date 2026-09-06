CREATE TABLE IF NOT EXISTS user_access (
    auth_user_id TEXT PRIMARY KEY,
    signed_in_free_actions INTEGER NOT NULL DEFAULT 0
        CHECK (signed_in_free_actions >= 0),
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT UNIQUE,
    subscription_status TEXT,
    subscription_price_id TEXT,
    current_period_end TIMESTAMPTZ,
    last_stripe_event_created BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS user_access_customer_idx
    ON user_access (stripe_customer_id);

CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_created BIGINT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS anonymous_access (
    visitor_id UUID PRIMARY KEY,
    free_actions INTEGER NOT NULL DEFAULT 0 CHECK (free_actions >= 0),
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);