-- 025_literature_zotero_link.sql
--
-- Add Zotero linkage to literature entries so the AI can navigate from
-- an RKA lit_… entry to its full-text PDF in the user's Zotero library.
--
-- Two columns:
--   zotero_item_key      — 8-char Zotero item key (e.g., "ABC123XY")
--   zotero_match_method  — how the link was made; audit trail for
--                          confidence in the linkage
--
-- A future schema may add zotero_library_id to support per-project group
-- libraries; for now we assume a single user library per machine.

ALTER TABLE literature ADD COLUMN zotero_item_key TEXT;
ALTER TABLE literature ADD COLUMN zotero_match_method TEXT
    CHECK (zotero_match_method IS NULL OR zotero_match_method IN (
        'doi',
        'arxiv_id',
        'url',
        'isbn',
        'title_author_year',
        'manual'
    ));

CREATE INDEX IF NOT EXISTS idx_literature_zotero_item_key
    ON literature(zotero_item_key)
    WHERE zotero_item_key IS NOT NULL;
