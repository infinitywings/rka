"""The two halves of `blockers` disagreed about its type.

`UpdateStatusArgs.blockers` — the typed MCP surface, and what
`rka_describe('update_status')` shows a caller — is `Optional[list[str]]`.
`ProjectStateUpdate.blockers` was `str | None`, matching the column, which is
`TEXT -- Current blockers (free text)`.

So every list sent through the connector died at the REST boundary with
`Input should be a valid string`. The half a caller reads was the half that
could not be written, and the field stayed stale in this project's own status
for long enough that the staleness was itself recorded as a blocker.
"""

import pytest

from rka.mcp.operation_args import UpdateStatusArgs
from rka.models.project import ProjectStateUpdate


class TestTheAdvertisedTypeIsWritable:
    def test_the_mcp_surface_still_advertises_a_list(self):
        """If this changes, the fix below is aimed at the wrong half."""
        assert UpdateStatusArgs.model_fields["blockers"].annotation == (
            list[str] | None
        )

    def test_a_list_is_accepted(self):
        assert ProjectStateUpdate(blockers=["first", "second"]).blockers == (
            "first\nsecond"
        )

    def test_a_string_still_is(self):
        """Existing REST and web-UI callers must not break."""
        assert ProjectStateUpdate(blockers="one long line").blockers == "one long line"

    def test_none_stays_none(self):
        assert ProjectStateUpdate(blockers=None).blockers is None


class TestJoiningDoesNotEditTheCaller:
    def test_entries_are_not_renumbered(self):
        """Callers that number their own lines must not be numbered twice."""
        out = ProjectStateUpdate(blockers=["1. alpha", "2. beta"]).blockers
        assert out == "1. alpha\n2. beta"
        assert "1. 1." not in out

    def test_blank_entries_are_dropped(self):
        assert ProjectStateUpdate(blockers=["a", "", "   ", "b"]).blockers == "a\nb"

    def test_an_empty_list_clears_rather_than_storing_an_empty_string(self):
        assert ProjectStateUpdate(blockers=[]).blockers is None


class TestTheRestOfTheModelIsUnchanged:
    def test_unknown_fields_are_still_rejected(self):
        """extra='forbid' guards against silent write failures —
        see mis_01KQJH9MB65AR0GSVPQBT8707X."""
        with pytest.raises(Exception):
            ProjectStateUpdate(blockrs=["typo"])

    def test_other_list_fields_are_untouched(self):
        assert ProjectStateUpdate(phases_config=["a", "b"]).phases_config == ["a", "b"]
