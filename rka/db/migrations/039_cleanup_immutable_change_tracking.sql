-- Migration 039: remove unreachable change triggers and a redundant index.
-- requires-table: manuscript_claim_versions, manuscript_claim_ratifications, manuscript_claim_verification_attestations, reference_validation_attestations
--
-- These four audit tables reject every UPDATE in BEFORE UPDATE immutability
-- triggers, so their AFTER UPDATE change-event triggers can never execute.
-- The validation-job lookup is already covered by the unique partial index.
--
-- change_events intentionally remains an unpruned durable cursor ledger.
-- Retention must not be introduced until the sync protocol has an explicit
-- cursor floor and snapshot/rebase mechanism for clients behind that floor.

DROP TRIGGER IF EXISTS trg_change_manuscript_claim_versions_update;
DROP TRIGGER IF EXISTS trg_change_manuscript_claim_ratifications_update;
DROP TRIGGER IF EXISTS trg_change_manuscript_claim_verifications_update;
DROP TRIGGER IF EXISTS trg_change_reference_validations_update;

DROP INDEX IF EXISTS idx_reference_validations_job;
