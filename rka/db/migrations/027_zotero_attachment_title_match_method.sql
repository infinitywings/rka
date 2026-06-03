-- 027_zotero_attachment_title_match_method.sql
--
-- v2.7.0.3 (Bug 4 fix, per PI bug report 2026-06-03): extend the
-- zotero_match_method CHECK constraint to allow 'attachment_title' —
-- the new match method used by Strategy 6 in rka.services.zotero_linker
-- when a literature entry has no DOI / arXiv ID / ISBN / URL and no
-- parent bibliographic item exists in Zotero, but a standalone PDF
-- attachment OR webpage carries a title that fuzzy-matches the lit
-- title (gray literature / sector reports / working papers).
--
-- Strategy 6 NEVER auto-links — it returns weak_match_needs_confirmation
-- candidates the PI must ratify via a subsequent explicit zotero_key
-- call. The 'attachment_title' value is recorded only when the PI
-- confirms via that path (matched_by stamped on persistence) — but the
-- CHECK constraint must allow the value at write time regardless.
--
-- Pattern mirrors migration 026 (explicit_key) — see that file for the
-- PRAGMA writable_schema rationale. The change is purely schema
-- metadata; no rows touched.

PRAGMA writable_schema = 1;

UPDATE sqlite_master
SET sql = replace(
    sql,
    'zotero_match_method IN (
        ''doi'',
        ''arxiv_id'',
        ''url'',
        ''isbn'',
        ''title_author_year'',
        ''manual'',
        ''explicit_key''
    )',
    'zotero_match_method IN (
        ''doi'',
        ''arxiv_id'',
        ''url'',
        ''isbn'',
        ''title_author_year'',
        ''manual'',
        ''explicit_key'',
        ''attachment_title''
    )'
)
WHERE type = 'table' AND name = 'literature';

PRAGMA writable_schema = 0;

PRAGMA integrity_check;
