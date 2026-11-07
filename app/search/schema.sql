-- Applied at startup; safe to re-run. PLAN §6.1.

CREATE TABLE IF NOT EXISTS incidents (
    id                 TEXT PRIMARY KEY,
    created_at         TEXT NOT NULL,
    environment        TEXT NOT NULL,
    service            TEXT NOT NULL,
    severity           TEXT NOT NULL,
    title              TEXT NOT NULL,
    description        TEXT NOT NULL,
    resolution_summary TEXT NOT NULL,
    tags_json          TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    ingested_at        TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_incidents_environment ON incidents(environment);
CREATE INDEX IF NOT EXISTS ix_incidents_service ON incidents(service);
CREATE INDEX IF NOT EXISTS ix_incidents_severity ON incidents(severity);
CREATE INDEX IF NOT EXISTS ix_incidents_created_at ON incidents(created_at);

-- exact tag filtering without LIKE over JSON
CREATE TABLE IF NOT EXISTS incident_tags (
    incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    PRIMARY KEY (incident_id, tag)
);
CREATE INDEX IF NOT EXISTS ix_incident_tags_tag ON incident_tags(tag);

-- Standalone FTS table, written explicitly in the same transaction as the row.
-- No external-content triggers: they're easy to get subtly wrong and hard to see.
CREATE VIRTUAL TABLE IF NOT EXISTS incidents_fts USING fts5(
    incident_id UNINDEXED,
    title,
    description,
    resolution_summary,
    tags,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
