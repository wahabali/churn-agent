CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    company TEXT NOT NULL,
    plan TEXT NOT NULL,          -- starter / growth / enterprise
    mrr REAL NOT NULL,           -- monthly recurring revenue in USD
    signup_date TEXT NOT NULL,   -- ISO date
    csm_name TEXT NOT NULL       -- customer success manager
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    event_type TEXT NOT NULL,    -- login / feature_use / api_call / support_ticket / payment_failed
    timestamp TEXT NOT NULL,     -- ISO datetime
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS health_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    score INTEGER NOT NULL,      -- 0-100
    risk_level TEXT NOT NULL,    -- HIGH / MEDIUM / LOW
    reason TEXT NOT NULL,
    checked_at TEXT NOT NULL,    -- ISO datetime
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS outreach_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    draft TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT,                -- NULL if not sent yet
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE INDEX IF NOT EXISTS idx_events_customer_ts ON events(customer_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_health_scores_customer ON health_scores(customer_id, checked_at);
