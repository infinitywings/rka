"""The present_decision option contract must agree across its two layers.

`present_decision` was uncallable on 2.9.0. The typed-args model required an
`id` on every option so that `record_pi_selection.selected_option_id` would be
dereferenceable; the REST payload it feeds, `DecisionOptionCreate`, declares
`extra="forbid"` and has no `id` field. Without `id` the MCP model refused;
with `id` the API returned 422 `extra_forbidden`. No call could satisfy both.

Option ids are server-assigned and come back as `presented_option_ids`.

These tests pin the agreement between the two layers, and check the documented
example against the model that actually receives it — the check whose absence
let a worked example ship that fails twice over: it carried an `id`, and it
omitted all twelve other required fields.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rka.mcp.operation_args import PresentDecisionArgs
from rka.mcp.operations_schema import OPERATIONS_SCHEMA
from rka.models.decision_option import DecisionOptionCreate


def valid_option(**overrides) -> dict:
    option = {
        "label": "Option A",
        "summary": "Do the thing.",
        "justification": "Measured best on our corpus.",
        "explanation": "Longer rationale.",
        "pros": ["fast", "cheap", "reversible"],
        "cons": ["new", "unproven", "needs reindex"],
        "confidence_verbal": "moderate",
        "confidence_numeric": 0.6,
        "confidence_evidence_strength": "moderate",
        "confidence_known_unknowns": ["behaviour at scale"],
        "effort_time": "M",
        "effort_reversibility": "reversible",
        "presentation_order_seed": 1,
    }
    option.update(overrides)
    return option


def present(options: list[dict]) -> PresentDecisionArgs:
    return PresentDecisionArgs(
        project_id="prj_01TEST0000000000000000000",
        decision_id="dec_01TEST0000000000000000000",
        confirmation_brief="brief",
        options=options,
    )


class TestLayersAgree:
    def test_an_option_the_api_accepts_is_accepted_here(self):
        """The regression: this shape used to be refused for lacking an id."""
        option = valid_option()
        DecisionOptionCreate.model_validate(option)  # REST layer accepts it
        assert present([option]).options == [option]

    def test_an_option_carrying_an_id_is_refused_by_both_layers(self):
        option = valid_option(id="A")

        with pytest.raises(ValidationError) as rest:
            DecisionOptionCreate.model_validate(option)
        assert "extra" in str(rest.value).lower()

        with pytest.raises(ValidationError) as mcp:
            present([option])
        assert "must not carry an 'id'" in str(mcp.value)

    def test_the_refusal_says_where_the_id_comes_from(self):
        """A bare 'extra_forbidden' reads as a schema mismatch, not a rule."""
        with pytest.raises(ValidationError) as exc:
            present([valid_option(id="A")])
        message = str(exc.value)
        assert "presented_option_ids" in message
        assert "record_pi_selection" in message

    def test_empty_options_still_refused(self):
        """TWO-TAP is void with nothing to ratify."""
        with pytest.raises(ValidationError):
            present([])

    def test_non_dict_option_still_refused(self):
        with pytest.raises(ValidationError):
            present(["not a dict"])


class TestDocumentedExample:
    """The worked example must survive the model that receives it."""

    @staticmethod
    def _example_calls() -> list[dict]:
        return [ex["call"] for ex in OPERATIONS_SCHEMA["present_decision"]["examples"]]

    def test_example_options_validate_against_the_rest_model(self):
        for call in self._example_calls():
            for index, option in enumerate(call["options"]):
                try:
                    DecisionOptionCreate.model_validate(option)
                except ValidationError as exc:  # pragma: no cover - failure path
                    pytest.fail(
                        f"documented present_decision example options[{index}] "
                        f"is rejected by DecisionOptionCreate: {exc}"
                    )

    def test_example_validates_against_the_typed_args_model(self):
        for call in self._example_calls():
            present(call["options"])

    def test_example_does_not_show_a_caller_supplied_id(self):
        for call in self._example_calls():
            for option in call["options"]:
                assert "id" not in option
