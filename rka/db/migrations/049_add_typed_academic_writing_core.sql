-- Migration 049: typed academic-writing semantics over the progressive outline.
-- requires-table: manuscript_unit_outline_profiles, manuscript_unit_evidence, manuscript_claim_versions, manuscript_reference_members, change_events

ALTER TABLE manuscript_unit_outline_profiles
    ADD COLUMN unit_role TEXT NOT NULL DEFAULT 'unspecified'
    CHECK (unit_role IN (
        'unspecified', 'section', 'argument_block', 'paragraph_plan',
        'result', 'caption', 'appendix', 'other'
    ));

ALTER TABLE manuscript_unit_outline_profiles
    ADD COLUMN rhetorical_move TEXT NOT NULL DEFAULT 'unspecified'
    CHECK (rhetorical_move IN (
        'unspecified', 'frame_problem', 'establish_gap', 'state_insight',
        'explain_mechanism', 'address_challenge', 'present_innovation',
        'pose_research_question', 'state_contribution', 'describe_method',
        'present_result', 'interpret_result', 'compare_prior_work',
        'state_limitation', 'transition', 'summarize', 'other'
    ));

ALTER TABLE manuscript_unit_evidence
    ADD COLUMN supported_proposition TEXT
    CHECK (
        supported_proposition IS NULL
        OR length(trim(supported_proposition)) > 0
    );

ALTER TABLE manuscript_unit_evidence
    ADD COLUMN warrant TEXT
    CHECK (warrant IS NULL OR length(trim(warrant)) > 0);

ALTER TABLE manuscript_claim_versions
    ADD COLUMN conditions TEXT NOT NULL DEFAULT '[]'
    CHECK (json_valid(conditions) AND json_type(conditions) = 'array');

ALTER TABLE manuscript_claim_versions
    ADD COLUMN falsification_criteria TEXT NOT NULL DEFAULT '[]'
    CHECK (
        json_valid(falsification_criteria)
        AND json_type(falsification_criteria) = 'array'
    );

CREATE TABLE manuscript_unit_citations (
    id TEXT PRIMARY KEY
        CHECK (substr(id, 1, 4) = 'muc_' AND length(id) > 4),
    manuscript_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    reference_member_id TEXT NOT NULL,
    citation_role TEXT NOT NULL
        CHECK (citation_role IN (
            'imports', 'bounds', 'baseline', 'extends', 'refutes'
        )),
    supported_proposition TEXT NOT NULL
        CHECK (length(trim(supported_proposition)) > 0),
    verification_state TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_state IN (
            'unverified', 'self_attested', 'verified', 'rejected'
        )),
    comparison_axis TEXT
        CHECK (comparison_axis IS NULL OR length(trim(comparison_axis)) > 0),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, manuscript_id, project_id),
    UNIQUE (
        unit_id, reference_member_id, citation_role, supported_proposition
    ),
    FOREIGN KEY (unit_id, manuscript_id, project_id)
        REFERENCES manuscript_units(id, manuscript_id, project_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (reference_member_id, manuscript_id, project_id)
        REFERENCES manuscript_reference_members(id, manuscript_id, project_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_manuscript_unit_citations_unit
    ON manuscript_unit_citations(
        project_id, manuscript_id, unit_id, citation_role, id
    );

CREATE INDEX idx_manuscript_unit_citations_reference
    ON manuscript_unit_citations(
        project_id, reference_member_id, verification_state
    );

CREATE TRIGGER trg_change_manuscript_unit_citations_insert
AFTER INSERT ON manuscript_unit_citations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, related_entity_type,
        related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_unit_citations', 'insert',
        'manuscript_citation', NEW.id, NEW.manuscript_id, NEW.unit_id,
        'manuscript_reference', NEW.reference_member_id,
        json_object(
            'citation_role', NEW.citation_role,
            'verification_state', NEW.verification_state
        )
    );
END;

CREATE TRIGGER trg_change_manuscript_unit_citations_update
AFTER UPDATE ON manuscript_unit_citations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, related_entity_type,
        related_entity_id, details
    ) VALUES (
        NEW.project_id, 'manuscript_unit_citations', 'update',
        'manuscript_citation', NEW.id, NEW.manuscript_id, NEW.unit_id,
        'manuscript_reference', NEW.reference_member_id,
        json_object(
            'citation_role', NEW.citation_role,
            'verification_state', NEW.verification_state
        )
    );
END;

CREATE TRIGGER trg_change_manuscript_unit_citations_delete
AFTER DELETE ON manuscript_unit_citations
BEGIN
    INSERT INTO change_events (
        project_id, source_table, operation, entity_type, entity_id,
        manuscript_id, manuscript_unit_id, related_entity_type,
        related_entity_id, details
    ) VALUES (
        OLD.project_id, 'manuscript_unit_citations', 'delete',
        'manuscript_citation', OLD.id, OLD.manuscript_id, OLD.unit_id,
        'manuscript_reference', OLD.reference_member_id,
        json_object(
            'citation_role', OLD.citation_role,
            'verification_state', OLD.verification_state
        )
    );
END;
