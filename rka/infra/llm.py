"""LLM integration via LiteLLM + Instructor for structured extraction."""

from __future__ import annotations

import logging
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from rka.config import RKAConfig

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


# ---------- Instructor response models ----------

class AutoTags(BaseModel):
    """Auto-generated tags for a research entry."""
    tags: list[str] = Field(
        ...,
        min_length=2,
        max_length=7,
        description="Lowercase topic tags. Reuse existing tags when applicable.",
    )


class AutoClassification(BaseModel):
    """Auto-classification of confidence and importance."""
    confidence: Literal["hypothesis", "tested", "verified"] = Field(
        ..., description="How well-established is this finding?",
    )
    importance: Literal["critical", "high", "normal", "low"] = Field(
        ..., description="How important is this to the current research direction?",
    )
    reasoning: str = Field(
        ..., description="Brief explanation for the classification",
    )


class SupersessionCheck(BaseModel):
    """Check if a new entry supersedes an existing one."""
    supersedes: str | None = Field(
        None, description="ID of the superseded entry, or null",
    )
    reason: str | None = Field(
        None, description="Why this entry supersedes the other",
    )


class EntrySummary(BaseModel):
    """One-line summary of a research entry."""
    summary: str = Field(
        ..., max_length=200,
        description="One concise sentence summarising the entry.",
    )


class NarrativeSummary(BaseModel):
    """Multi-paragraph narrative for context packages."""
    narrative: str = Field(
        ..., description="A coherent narrative integrating the provided entries.",
    )


class SemanticLinks(BaseModel):
    """Semantically inferred links between a new entry and existing entities."""
    related_decision_ids: list[str] = Field(
        default_factory=list,
        description="IDs of decisions this entry is directly related to or produced by.",
    )
    related_literature_ids: list[str] = Field(
        default_factory=list,
        description="IDs of literature entries this entry references, supports, or is informed by.",
    )
    related_mission_id: str | None = Field(
        None,
        description="ID of the mission that produced or is most relevant to this entry, or null.",
    )
    suggested_type: Literal[
        "finding", "insight", "methodology", "idea", "observation",
        "hypothesis", "exploration", "pi_instruction", "summary",
    ] | None = Field(
        None,
        description="Corrected journal entry type based on content, if the provided type appears wrong.",
    )
    reasoning: str = Field(
        ..., description="One sentence explaining the inferred links.",
    )


class FileClassification(BaseModel):
    """LLM classification of a research file's content."""
    content_type: Literal[
        "meeting_notes", "paper_manuscript", "brainstorm",
        "action_items", "code_documentation", "structured_document",
        "literature_review", "experimental_results", "general",
    ] = Field(..., description="What kind of document is this?")
    journal_type: Literal[
        "finding", "insight", "methodology", "idea", "observation",
        "hypothesis", "exploration", "pi_instruction", "summary",
    ] = Field(..., description="Best-fit RKA journal entry type.")
    tags: list[str] = Field(
        ...,
        min_length=2,
        max_length=7,
        description="Lowercase topic tags for this file.",
    )
    title_suggestion: str = Field(
        ..., description="Short descriptive title for this file.",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="How confident in this classification (0=guess, 1=certain).",
    )


class PDFMetadataExtraction(BaseModel):
    """Structured metadata extracted from a PDF's first page text."""
    title: str = Field(..., description="Title of the paper/document.")
    authors: list[str] = Field(
        default_factory=list, description="Author names if identifiable.",
    )
    abstract: str | None = Field(
        None, description="Abstract text if present on the first page.",
    )
    year: int | None = Field(
        None, description="Publication year if identifiable.",
    )


# ---------- LLM Client ----------

class LLMUnavailableError(Exception):
    """Raised when a required LLM call cannot be fulfilled."""


class LLMClient:
    """Unified LLM interface via LiteLLM + Instructor.

    The LLM is a required dependency — services should fail loudly
    if the LLM is unreachable rather than silently degrading.
    Supports any OpenAI-compatible backend: Ollama, LM Studio, vLLM, cloud APIs.
    """

    def __init__(self, config: RKAConfig):
        self.config = config
        self.model = config.llm_model
        self._instructor_client = None
        self._available: bool | None = None

    @property
    def _api_key(self) -> str | None:
        """Resolve API key: use configured key, or dummy key for openai/ prefix."""
        if self.config.llm_api_key:
            return self.config.llm_api_key
        # LiteLLM requires an API key for openai/ prefixed models even when
        # the backend (LM Studio) doesn't need one.
        if self.model.startswith("openai/"):
            return "lm-studio"
        return None

    def _get_instructor(self):
        """Lazy-init Instructor client.

        Uses JSON_SCHEMA mode instead of tool/function-calling mode because
        local backends (LM Studio, Ollama) don't support tool_choice objects.
        """
        if self._instructor_client is None:
            import litellm
            import instructor
            self._instructor_client = instructor.from_litellm(
                litellm.acompletion, mode=instructor.Mode.JSON_SCHEMA,
            )
        return self._instructor_client

    async def is_available(self) -> bool:
        """Health check — can we reach the LLM?"""
        if not self.config.llm_enabled:
            return False
        try:
            import litellm
            kwargs: dict = dict(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=256,
            )
            if self.config.llm_api_base:
                kwargs["api_base"] = self.config.llm_api_base
            if self._api_key:
                kwargs["api_key"] = self._api_key
            await litellm.acompletion(**kwargs)
            self._available = True
            return True
        except Exception as exc:
            logger.debug("LLM health check failed: %s", exc)
            self._available = False
            return False

    async def extract(
        self,
        response_model: type[T],
        messages: list[dict],
        temperature: float = 0.1,
        max_retries: int = 2,
    ) -> T:
        """Structured extraction via Instructor. Raises LLMUnavailableError on failure."""
        if not self.config.llm_enabled:
            raise LLMUnavailableError(
                "LLM is not enabled. Configure it in Settings or set "
                "RKA_LLM_ENABLED=true with RKA_LLM_API_BASE pointing to your LM Studio / Ollama."
            )
        try:
            client = self._get_instructor()
            kwargs: dict = dict(
                model=self.model,
                response_model=response_model,
                messages=messages,
                temperature=temperature,
                max_retries=max_retries,
                think=self.config.llm_think,
            )
            if self.config.llm_api_base:
                kwargs["api_base"] = self.config.llm_api_base
            if self._api_key:
                kwargs["api_key"] = self._api_key
            result = await client.chat.completions.create(**kwargs)
            self._available = True
            return result
        except LLMUnavailableError:
            raise
        except Exception as exc:
            self._available = False
            raise LLMUnavailableError(
                f"LLM call failed: {exc}. "
                f"Ensure your LM Studio / Ollama is running and the model is loaded."
            ) from exc

    async def auto_tag(
        self, content: str, existing_tags: list[str] | None = None,
    ) -> list[str]:
        """Generate tags for content."""
        existing_hint = ""
        if existing_tags:
            existing_hint = f"\n\nExisting tags in the project (reuse when applicable): {', '.join(existing_tags[:30])}"

        result = await self.extract(
            AutoTags,
            messages=[{
                "role": "user",
                "content": (
                    f"Generate 2-7 lowercase topic tags for this research entry. "
                    f"Tags should capture key concepts, methods, and domains.{existing_hint}"
                    f"\n\nEntry:\n{content[:2000]}"
                ),
            }],
        )
        return result.tags

    async def auto_classify(self, content: str) -> AutoClassification:
        """Classify confidence and importance."""
        return await self.extract(
            AutoClassification,
            messages=[{
                "role": "user",
                "content": (
                    f"Classify this research entry's confidence level and importance.\n\n"
                    f"Entry:\n{content[:2000]}"
                ),
            }],
        )

    async def check_supersession(
        self, new_content: str, candidates: list[dict],
    ) -> SupersessionCheck | None:
        """Check if new entry supersedes any existing entries."""
        if not candidates:
            return None
        cand_text = "\n".join(
            f"- ID: {c['id']}, Content: {c['content'][:200]}"
            for c in candidates[:10]
        )
        return await self.extract(
            SupersessionCheck,
            messages=[{
                "role": "user",
                "content": (
                    f"Does this new entry supersede (replace/update/invalidate) any of the existing entries?\n\n"
                    f"New entry:\n{new_content[:1000]}\n\n"
                    f"Existing entries:\n{cand_text}\n\n"
                    f"If the new entry supersedes one, return its ID. Otherwise return null."
                ),
            }],
        )

    async def summarize_entry(self, content: str) -> str:
        """Generate a one-line summary."""
        result = await self.extract(
            EntrySummary,
            messages=[{
                "role": "user",
                "content": f"Summarize this research entry in one concise sentence:\n\n{content[:2000]}",
            }],
        )
        return result.summary

    async def summarize_entries(
        self, entries: list[dict], max_tokens: int = 500,
    ) -> str:
        """Produce a narrative combining multiple entries."""
        entries_text = "\n\n".join(
            f"[{e.get('type', 'entry')}] {e.get('content', e.get('title', ''))[:300]}"
            for e in entries[:20]
        )
        result = await self.extract(
            NarrativeSummary,
            messages=[{
                "role": "user",
                "content": (
                    f"Produce a coherent summary integrating these research entries "
                    f"(max {max_tokens} tokens):\n\n{entries_text}"
                ),
            }],
        )
        return result.narrative

    async def produce_narrative(self, package_dict: dict) -> str:
        """Produce a full narrative for a context package."""
        import json
        return await self.summarize_entries(
            [{"content": json.dumps(package_dict, default=str)}],
            max_tokens=1000,
        )

    async def semantic_link(
        self,
        content: str,
        current_type: str,
        decisions: list[dict],
        literature: list[dict],
        missions: list[dict],
    ) -> SemanticLinks:
        """Infer relationships between a new entry and existing entities.

        Returns SemanticLinks with IDs of related entities.
        Only IDs that appear in the provided candidate lists will be returned.
        """

        def fmt(items: list[dict], id_key: str, text_key: str) -> str:
            return "\n".join(
                f"  {it[id_key]}: {str(it.get(text_key, ''))[:120]}"
                for it in items[:20]
            ) or "  (none)"

        dec_text = fmt(decisions, "id", "question")
        lit_text = fmt(literature, "id", "title")
        mis_text = fmt(missions, "id", "objective")

        valid_dec_ids = {d["id"] for d in decisions}
        valid_lit_ids = {l["id"] for l in literature}
        valid_mis_ids = {m["id"] for m in missions}

        result = await self.extract(
            SemanticLinks,
            messages=[{
                "role": "user",
                "content": (
                    f"You are organizing a research knowledge base. Given the entry below, "
                    f"identify which existing decisions, literature, and missions it is related to. "
                    f"Only return IDs that appear in the candidate lists. "
                    f"Also suggest a corrected type if '{current_type}' seems wrong.\n\n"
                    f"Entry (type={current_type}):\n{content[:1500]}\n\n"
                    f"Candidate decisions:\n{dec_text}\n\n"
                    f"Candidate literature:\n{lit_text}\n\n"
                    f"Candidate missions:\n{mis_text}"
                ),
            }],
        )
        # Filter to only valid IDs (LLM may hallucinate)
        result.related_decision_ids = [i for i in result.related_decision_ids if i in valid_dec_ids]
        result.related_literature_ids = [i for i in result.related_literature_ids if i in valid_lit_ids]
        if result.related_mission_id and result.related_mission_id not in valid_mis_ids:
            result.related_mission_id = None
        return result

    async def classify_file(
        self, filename: str, content_preview: str, extension: str,
    ) -> FileClassification:
        """Classify a research file's content for workspace bootstrap."""
        return await self.extract(
            FileClassification,
            messages=[{
                "role": "user",
                "content": (
                    f"Classify this research file for ingestion into a knowledge base.\n\n"
                    f"Filename: {filename}\n"
                    f"Extension: {extension}\n\n"
                    f"Content preview:\n{content_preview[:2000]}\n\n"
                    f"Determine the content type, best-fit journal entry type, "
                    f"2-7 lowercase tags, a short title, and your confidence (0-1)."
                ),
            }],
        )

    async def extract_figure(
        self,
        context_text: str,
        page: int | None = None,
        artifact_id: str | None = None,
    ):
        """Extract structured data from a figure/image context.

        Returns FigureExtraction or None if LLM unavailable.
        """
        from rka.infra.llm_models import FigureExtraction

        loc_hint = ""
        if page is not None:
            loc_hint = f" (from page {page})"
        if artifact_id:
            loc_hint += f" [artifact: {artifact_id}]"

        return await self.extract(
            FigureExtraction,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract structured data from this figure/image{loc_hint}.\n\n"
                    f"Provide: a caption (if visible), a one-paragraph summary, "
                    f"factual claims with numeric values and confidence scores, "
                    f"whether it's table-like, and suggested journal entries for notable findings.\n\n"
                    f"Context:\n{context_text[:3000]}"
                ),
            }],
        )

    async def extract_table(
        self,
        table_text: str,
        context_text: str | None = None,
    ):
        """Extract structured table data from text.

        Returns TableExtraction or None if LLM unavailable.
        """
        from rka.infra.llm_models import TableExtraction

        ctx = ""
        if context_text:
            ctx = f"\n\nSurrounding context:\n{context_text[:1000]}"

        return await self.extract(
            TableExtraction,
            messages=[{
                "role": "user",
                "content": (
                    f"Parse this table into structured data. Extract headers, rows, "
                    f"a one-sentence summary, and key factual claims.{ctx}\n\n"
                    f"Table:\n{table_text[:3000]}"
                ),
            }],
        )

    async def generate_summary(
        self,
        evidence_blocks: list[dict],
        scope_label: str = "project",
        granularity: str = "paragraph",
    ):
        """Generate a multi-granularity summary from evidence blocks.

        Each evidence block: {entity_type, entity_id, text, loc?}
        Returns SummaryOutput or None if LLM unavailable.
        """
        from rka.infra.llm_models import SummaryOutput

        evidence_text = "\n\n".join(
            f"[{b.get('entity_type', 'unknown')}:{b.get('entity_id', '?')}] "
            f"{b.get('text', '')[:500]}"
            for b in evidence_blocks[:30]
        )

        granularity_instr = {
            "one_line": "Provide only a one-line summary.",
            "paragraph": "Provide a one-line summary and a one-paragraph summary with key points.",
            "narrative": "Provide all three: one-line, paragraph, and a multi-paragraph narrative.",
        }.get(granularity, "Provide a one-line summary and a one-paragraph summary.")

        return await self.extract(
            SummaryOutput,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize these research evidence blocks for scope '{scope_label}'.\n"
                    f"{granularity_instr}\n"
                    f"Cite sources using entity IDs. Identify open questions or gaps.\n\n"
                    f"Evidence:\n{evidence_text}"
                ),
            }],
        )

    async def answer_qa(
        self,
        question: str,
        evidence_blocks: list[dict],
        session_context: str | None = None,
    ):
        """Answer a research question grounded in evidence blocks (NotebookLM-style).

        Each evidence block: {entity_type, entity_id, text, loc?}
        Returns QAAnswer or None if LLM unavailable.
        """
        from rka.infra.llm_models import QAAnswer

        evidence_text = "\n\n".join(
            f"[{b.get('entity_type', 'unknown')}:{b.get('entity_id', '?')}] "
            f"{b.get('text', '')[:500]}"
            for b in evidence_blocks[:30]
        )

        ctx = ""
        if session_context:
            ctx = f"\n\nSession context:\n{session_context[:500]}"

        return await self.extract(
            QAAnswer,
            messages=[{
                "role": "user",
                "content": (
                    f"Answer this research question using ONLY the provided evidence. "
                    f"Quote exact excerpts from sources. Suggest follow-up questions.{ctx}\n\n"
                    f"Question: {question}\n\n"
                    f"Evidence:\n{evidence_text}"
                ),
            }],
        )

    async def extract_pdf_metadata(
        self, first_page_text: str,
    ) -> PDFMetadataExtraction:
        """Extract title, authors, abstract from PDF first-page text."""
        return await self.extract(
            PDFMetadataExtraction,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the paper title, author names, abstract, and year "
                    f"from this PDF first page text. Return null for fields "
                    f"you cannot identify.\n\n{first_page_text[:3000]}"
                ),
            }],
        )
