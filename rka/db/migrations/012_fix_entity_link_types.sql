-- Migration 012: Fix entity_links edge type mismatches
--
-- Historical data has decision→journal links typed as 'references' when they
-- should be 'justified_by', and mission motivated_by_decision links typed as
-- 'references' when they should be 'motivated'.
--
-- This migration:
-- 1. For each decision with related_journal, find the matching entity_links
--    rows (journal→decision with link_type='references') and update them to
--    justified_by with correct direction (decision→journal).
-- 2. For each mission with motivated_by_decision, find matching entity_links
--    rows and update to 'motivated' with correct direction (decision→mission).

-- Step 1: Fix decision↔journal links
-- These were created as (source=journal, target=decision, type=references)
-- They should be (source=decision, target=journal, type=justified_by)
--
-- We update the existing rows: flip source/target and change the type.
-- Only update rows where a decision's related_journal JSON contains the journal ID.

UPDATE entity_links
SET link_type = 'justified_by',
    source_type = 'decision',
    source_id = target_id,
    target_type = 'journal',
    target_id = source_id
WHERE id IN (
    SELECT el.id
    FROM entity_links el
    JOIN decisions d ON d.id = el.target_id AND d.project_id = el.project_id
    WHERE el.link_type = 'references'
      AND el.source_type = 'journal'
      AND el.target_type = 'decision'
      AND d.related_journal IS NOT NULL
      AND d.related_journal != '[]'
      AND d.related_journal != 'null'
      AND INSTR(d.related_journal, el.source_id) > 0
);

-- Step 2: Fix mission motivated_by_decision links
-- These may have been created as (source=mission/decision, target=decision/mission, type=references)
-- They should be (source=decision, target=mission, type=motivated)

UPDATE entity_links
SET link_type = 'motivated',
    source_type = 'decision',
    source_id = (
        SELECT m.motivated_by_decision
        FROM missions m
        WHERE m.id = entity_links.source_id AND m.project_id = entity_links.project_id
    ),
    target_type = 'mission',
    target_id = source_id
WHERE id IN (
    SELECT el.id
    FROM entity_links el
    JOIN missions m ON m.id = el.source_id AND m.project_id = el.project_id
    WHERE el.link_type = 'references'
      AND el.source_type = 'mission'
      AND el.target_type = 'decision'
      AND m.motivated_by_decision IS NOT NULL
      AND m.motivated_by_decision = el.target_id
);

-- Also handle the reverse direction (decision→mission with references)
UPDATE entity_links
SET link_type = 'motivated'
WHERE id IN (
    SELECT el.id
    FROM entity_links el
    JOIN missions m ON m.id = el.target_id AND m.project_id = el.project_id
    WHERE el.link_type = 'references'
      AND el.source_type = 'decision'
      AND el.target_type = 'mission'
      AND m.motivated_by_decision IS NOT NULL
      AND m.motivated_by_decision = el.source_id
);
