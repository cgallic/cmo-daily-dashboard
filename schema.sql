-- cmo-daily-dashboard — command-center store schema
-- One store for Suggestions + Tasks ("items") across every loop/track/channel,
-- plus per-channel health state and one row per orchestrator run.
-- SQLite (Python stdlib). Mirrored to inbox.jsonl + STATE.json for git/static-build.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Every suggestion or task the orchestrator emits.
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,           -- e.g. "2026-01-01-leads-001"
    created_at    TEXT NOT NULL,              -- ISO8601
    run_id        TEXT,                       -- which run emitted it
    type          TEXT NOT NULL CHECK (type IN ('suggestion','task')),
    track         TEXT NOT NULL,              -- generic grouping: product_a | product_b | experimental
    channel       TEXT,                       -- youtube | linkedin | ads | blog | ...
    loop          TEXT NOT NULL,              -- which loop emitted (revenue_leads, traffic_seo, ...)
    title         TEXT NOT NULL,
    body          TEXT,                       -- the human-readable detail / "why"
    evidence      TEXT,                       -- JSON: the demo numbers/links that justify it
    score         INTEGER NOT NULL DEFAULT 50, -- priority 0-100
    owner         TEXT NOT NULL DEFAULT 'AGENT-auto'
                  CHECK (owner IN ('AGENT-auto','OPERATOR-approve','OPERATOR-do')),
    gate          TEXT NOT NULL DEFAULT 'safe'
                  CHECK (gate IN ('safe','irreversible')),
    state         TEXT NOT NULL DEFAULT 'new'
                  CHECK (state IN ('new','approved','executing','staged','done','dismissed','failed')),
    action        TEXT,                       -- JSON: what an executor *would* do (display-only here)
    result        TEXT,                       -- JSON: outcome after acting
    acted_at      TEXT,
    dedup_key     TEXT                         -- stable key to avoid re-emitting the same item
);

CREATE INDEX IF NOT EXISTS idx_items_state ON items(state);
CREATE INDEX IF NOT EXISTS idx_items_track ON items(track);
CREATE INDEX IF NOT EXISTS idx_items_owner ON items(owner);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_dedup ON items(dedup_key) WHERE dedup_key IS NOT NULL;

-- One row per orchestrator run.
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,           -- e.g. "2026-01-01T09:30:00"
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    mode          TEXT NOT NULL DEFAULT 'dry-run' CHECK (mode IN ('dry-run','live')),
    loops_run     TEXT,                       -- JSON array
    counts        TEXT,                       -- JSON: {suggestions, tasks, by_loop, ...}
    digest_path   TEXT,                       -- runs/<date>/report.md
    notes         TEXT
);

-- Current per-channel health snapshot (also dumped to STATE.json).
CREATE TABLE IF NOT EXISTS state (
    channel       TEXT PRIMARY KEY,
    track         TEXT,
    status        TEXT NOT NULL,              -- consistent | intermittent | stalled | no_driver | deprioritized | unknown
    driver        TEXT,
    evidence      TEXT,
    updated_at    TEXT NOT NULL
);
