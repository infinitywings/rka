-- Migration 021: enforce CHECK constraint on entity_links.link_type.
--
-- Background. The entity_links schema (migrations 004 → 020) never enforced
-- a CHECK on link_type, so a typo in any caller (or a stale historical row)
-- could silently land. Migration 012 already had to retroactively repair
-- mistyped 'references' rows that should have been 'justified_by' or
-- 'motivated'. This migration closes that hole at the schema level.
--
-- Pre-flight. The live rka_development DB at the time of this migration's
-- authoring had 7 distinct link_types in entity_links:
--   produced (1534), references (1109), derived_from (756), cites (519),
--   justified_by (446), informed_by (151), motivated (112).
-- That is a strict subset of the CHECK enumeration below, so existing rows
-- migrate cleanly. Other deployments are protected by the same INSERT-SELECT
-- pattern: any pre-existing link_type outside the enumeration would surface
-- as an INSERT error during the rebuild step rather than silently land.
--
-- Enumeration. The CHECK enumerates every link_type that production code
-- (rka/services, rka/api, rka/mcp) emits via BaseService.add_link or
-- backfill._insert_link, plus the two legacy types preserved per the
-- mission-A scope:
--
--   Active (9): justified_by, informed_by, supersedes, motivated, references,
--               cites, produced, derived_from, resolved_as.
--   Legacy (2): evidence_for (original schema.sql comment, no current code
--               path), triggered (still emitted by services/backfill.py for
--               hierarchical decision/mission relations; mission-A spec
--               labels it legacy pending a post-v2.3.4 migration to
--               'motivated' or to a richer relation name).
--
-- Future types must be added to this CHECK in a follow-up migration.
--
-- Mechanical safety. SQLite cannot ALTER TABLE to add a CHECK; we follow
-- migration 020's table-swap pattern: rename old → create new with CHECK →
-- INSERT SELECT → drop old → recreate indexes. The new constraint is
-- additive: existing satisfying rows migrate; non-satisfying rows would
-- fail at INSERT time rather than silently land.
--
-- Provenance. Mission mis_01KR1Z28QW9WYXG4VV8PGYWD8G (T1 of v2.3.4 defect
-- remediation). Motivating decision dec_01KR1Z06E6W51GHYQZ9TFM7WVP. Source
-- plan jrn_01KR1YGNH8YGN2DQJAYDB6KBZX (revision report, defect 5).

PRAGMA foreign_keys = OFF;

-- =============================================================
-- Step 1: rebuild entity_links with the CHECK constraint.
-- Column set mirrors the post-020 shape (link_weight, link_reason
-- columns added after the original schema.sql definition).
-- =============================================================

ALTER TABLE entity_links RENAME TO entity_links_old;

CREATE TABLE entity_links (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    link_type   TEXT NOT NULL CHECK (link_type IN (
        -- Active types (emitted by production code paths)
        'justified_by',
        'informed_by',
        'supersedes',
        'motivated',
        'references',
        'cites',
        'produced',
        'derived_from',
        'resolved_as',
        -- Legacy types preserved for historical rows + backfill compatibility
        'evidence_for',
        'triggered'
    )),
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by  TEXT,
    link_weight REAL DEFAULT 0.0,
    link_reason TEXT,
    project_id  TEXT
);

INSERT INTO entity_links (
    id, source_type, source_id, link_type, target_type, target_id,
    created_at, created_by, link_weight, link_reason, project_id
)
SELECT
    id, source_type, source_id, link_type, target_type, target_id,
    created_at, created_by, link_weight, link_reason, project_id
FROM entity_links_old;

DROP TABLE entity_links_old;

-- =============================================================
-- Step 2: recreate the index set established by migrations 004
-- (base indexes), 020 (project-scoped UNIQUE).
-- =============================================================

CREATE INDEX IF NOT EXISTS idx_entity_links_source ON entity_links(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_target ON entity_links(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_type   ON entity_links(link_type);
CREATE INDEX IF NOT EXISTS idx_entity_links_project ON entity_links(project_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_links_project_triple
    ON entity_links(project_id, source_id, link_type, target_id);

PRAGMA foreign_keys = ON;
