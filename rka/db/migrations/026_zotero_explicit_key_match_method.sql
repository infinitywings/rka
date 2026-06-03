-- 026_zotero_explicit_key_match_method.sql
--
-- v2.7.0.2 (Bug 3 fix): extend the zotero_match_method CHECK constraint
-- to allow 'explicit_key' — the new match method used when the caller
-- supplies a Zotero item key directly (bypassing the five fuzzy
-- strategies). Pre-fix the constraint only allowed
--   doi | arxiv_id | url | isbn | title_author_year | manual
-- so persisting an explicit-key link tripped CHECK violation at write
-- time, even though Pydantic-side validation passed.
--
-- SQLite doesn't support ALTER TABLE ... DROP CHECK or
-- ALTER COLUMN. We use the documented `PRAGMA writable_schema = 1` +
-- direct UPDATE of sqlite_master technique to swap the constraint in
-- place without rebuilding the table. This is the same technique the
-- official SQLite docs recommend at https://sqlite.org/lang_altertable.html
-- (section "Making other kinds of table schema changes"); the schema
-- change is purely metadata — no row touches — so it's near-instant
-- regardless of literature row count.
--
-- Safety: PRAGMA writable_schema applies only inside this connection,
-- and we set integrity_check after the swap so a malformed rewrite
-- would surface immediately.

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
        ''manual''
    )',
    'zotero_match_method IN (
        ''doi'',
        ''arxiv_id'',
        ''url'',
        ''isbn'',
        ''title_author_year'',
        ''manual'',
        ''explicit_key''
    )'
)
WHERE type = 'table' AND name = 'literature';

PRAGMA writable_schema = 0;

PRAGMA integrity_check;
