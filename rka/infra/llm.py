"""LLM integration via LiteLLM + Instructor for structured extraction."""

from __future__ import annotations

import logging
from typing import Any
from typing import Literal, TypeVar

import httpx
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
    suggested_type: str | None = Field(
        None,
        description="Corrected journal entry type based on content, if the provided type appears wrong.",
    )
    reasoning: str | None = Field(
        default="",
        description="One sentence explaining the inferred links.",
    )


# ---------- v2.0 distillation pipeline models ----------

class ExtractedClaim(BaseModel):
    """A single claim extracted from a journal entry."""
    claim_type: Literal["hypothesis", "evidence", "method", "result", "observation", "assumption"]
    content: str
    source_offset_start: int
    source_offset_end: int


class ExtractedClaims(BaseModel):
    """Output of claim extraction from a journal entry."""
    claims: list[ExtractedClaim] = Field(min_length=1, max_length=20)
    reasoning: str


class ClaimVerification(BaseModel):
    """Output of factored verification of a claim against source text."""
    exists_in_source: bool
    number_accuracy: bool
    direction_correct: bool
    overall_confidence: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)


class ClaimRelation(BaseModel):
    """A relationship between two claims."""
    target_claim_id: str
    relation: Literal["supports", "contradicts", "qualifies"]
    confidence: float = Field(ge=0.0, le=1.0)


class ClusterAssignment(BaseModel):
    """Output of cluster scoring for a claim."""
    cluster_id: str | None = None  # existing cluster or None for new
    cluster_label: str  # for new clusters
    relations: list[ClaimRelation] = Field(default_factory=list)


class ThemeSynthesis(BaseModel):
    """Output of cluster synthesis."""
    synthesis: str  # paragraph
    confidence: Literal["strong", "moderate", "emerging", "contested", "refuted"]
    gaps: list[str] = Field(default_factory=list)  # what evidence is missing
    contradictions: list[str] = Field(default_factory=list)  # what evidence conflicts


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
    def ctx(self) -> int:
        """Model context window in tokens."""
        return self.config.llm_context_window

    @property
    def available(self) -> bool:
        """Latest known availability status from health checks."""
        return bool(self._available)

    @property
    def _content_limit(self) -> int:
        """Max chars for a single content block sent to LLM.
        With 256k context → ~200k chars; with 4k → ~3k chars."""
        return max(2000, self.ctx * 3 // 4)

    @property
    def _evidence_block_limit(self) -> int:
        """Max chars per evidence block in Q&A/summary."""
        if self.ctx >= 128_000:
            return 4000
        elif self.ctx >= 32_000:
            return 2000
        elif self.ctx >= 8_000:
            return 1000
        return 500

    @property
    def _max_evidence_blocks(self) -> int:
        """Max evidence blocks for Q&A/summary."""
        if self.ctx >= 128_000:
            return 200
        elif self.ctx >= 32_000:
            return 80
        elif self.ctx >= 8_000:
            return 40
        return 30

    @property
    def _entries_limit(self) -> int:
        """Max entries to include in summarize_entries."""
        if self.ctx >= 128_000:
            return 100
        elif self.ctx >= 32_000:
            return 50
        return 20

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

        Uses JSON mode (plain JSON extraction) for maximum compatibility
        across LLM backends. JSON_SCHEMA mode causes markdown formatting and
        retry loops with some models like MiniMax.
        """
        if self._instructor_client is None:
            import litellm
            import instructor
            self._instructor_client = instructor.from_litellm(
                litellm.acompletion, mode=instructor.Mode.JSON,
            )
        return self._instructor_client

    @property
    def _bare_model(self) -> str:
        """Model ID without LiteLLM provider prefixes."""
        return self.model.removeprefix("openai/").removeprefix("ollama/")

    def _models_probe_headers(self) -> dict[str, str]:
        """Headers for model-list probing."""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _model_matches(self, model_id: str | None) -> bool:
        """Best-effort model ID matching across OpenAI-compatible backends."""
        if not model_id:
            return False
        bare_model = self._bare_model
        return model_id in {self.model, bare_model} or model_id.endswith(f"/{bare_model}")

    async def _probe_models_endpoint(self) -> bool | None:
        """Check backend reachability via model-list endpoints before generating tokens.

        Returns True when the backend is reachable and the configured model is listed.
        Returns None when the probe is inconclusive and a completion fallback should be tried.
        """
        if not self.config.llm_api_base:
            return None

        base = self.config.llm_api_base.rstrip("/")
        if base.endswith("/v1"):
            normalized_base = base[:-3]
        else:
            normalized_base = base

        endpoints = [
            f"{normalized_base}/api/v0/models",
            f"{normalized_base}/v1/models",
        ]
        headers = self._models_probe_headers()

        try:
            async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
                for url in endpoints:
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                    except Exception as exc:
                        logger.debug("LLM model probe failed for %s: %s", url, exc)
                        continue

                    data: Any = response.json()
                    models = data if isinstance(data, list) else data.get("data", [])
                    if any(self._model_matches(str(model.get("id", ""))) for model in models):
                        return True
                    logger.debug(
                        "LLM model probe reached %s but did not find configured model %s",
                        url,
                        self.model,
                    )
                    return None
        except Exception as exc:
            logger.debug("LLM model probe setup failed: %s", exc)

        return None

    async def is_available(self) -> bool:
        """Health check — can we reach the LLM?"""
        if not self.config.llm_enabled:
            return False
        if not self.model:
            self._available = False
            logger.debug("LLM health check skipped: no model configured")
            return False
        probed = await self._probe_models_endpoint()
        if probed is True:
            self._available = True
            return True
        try:
            import litellm
            kwargs: dict = dict(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                timeout=60,
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
                "RKA_LLM_ENABLED=true and provide model/backend settings."
            )
        if not self.model:
            raise LLMUnavailableError(
                "LLM model is not configured. Set a model in Settings before using LLM features."
            )
        try:
            client = self._get_instructor()
            kwargs: dict = dict(
                model=self.model,
                response_model=response_model,
                messages=messages,
                temperature=temperature,
                max_retries=max_retries,
                timeout=self.config.llm_request_timeout,
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
                f"Ensure your configured LLM backend is reachable and the selected model is available."
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
                    f"\n\nEntry:\n{content[:self._content_limit]}"
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
                    f"Entry:\n{content[:self._content_limit]}"
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
            f"- ID: {c['id']}, Content: {c['content'][:self._evidence_block_limit]}"
            for c in candidates[:self._max_evidence_blocks // 3]
        )
        return await self.extract(
            SupersessionCheck,
            messages=[{
                "role": "user",
                "content": (
                    f"Does this new entry supersede (replace/update/invalidate) any of the existing entries?\n\n"
                    f"New entry:\n{new_content[:self._content_limit]}\n\n"
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
                "content": f"Summarize this research entry in one concise sentence:\n\n{content[:self._content_limit]}",
            }],
        )
        return result.summary

    async def summarize_entries(
        self, entries: list[dict], max_tokens: int = 500,
    ) -> str:
        """Produce a narrative combining multiple entries."""
        entries_text = "\n\n".join(
            f"[{e.get('type', 'entry')}] {e.get('content', e.get('title', ''))[:self._evidence_block_limit]}"
            for e in entries[:self._entries_limit]
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
                f"  {it[id_key]}: {str(it.get(text_key, ''))[:self._evidence_block_limit // 2]}"
                for it in items[:self._entries_limit]
            ) or "  (none)"

        dec_text = fmt(decisions, "id", "question")
        lit_text = fmt(literature, "id", "title")
        mis_text = fmt(missions, "id", "objective")

        valid_dec_ids = {d["id"] for d in decisions}
        valid_lit_ids = {lit["id"] for lit in literature}
        valid_mis_ids = {m["id"] for m in missions}

        result = await self.extract(
            SemanticLinks,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You must respond ONLY with valid JSON matching the required schema. "
                        "Do not include any markdown formatting (no **bold**, no bullet points, no headings), "
                        "no explanations, and no text outside the JSON structure. "
                        "Output raw JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"You are organizing a research knowledge base. Given the entry below, "
                        f"identify which existing decisions, literature, and missions it is related to. "
                        f"Only return IDs that appear in the candidate lists. "
                        f"Also suggest a corrected type if '{current_type}' seems wrong.\n\n"
                        f"Entry (type={current_type}):\n{content[:self._content_limit]}\n\n"
                        f"Candidate decisions:\n{dec_text}\n\n"
                        f"Candidate literature:\n{lit_text}\n\n"
                        f"Candidate missions:\n{mis_text}"
                    ),
                },
            ],
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
                    f"Content preview:\n{content_preview[:self._content_limit]}\n\n"
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
                    f"Context:\n{context_text[:self._content_limit]}"
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
            ctx = f"\n\nSurrounding context:\n{context_text[:self._evidence_block_limit]}"

        return await self.extract(
            TableExtraction,
            messages=[{
                "role": "user",
                "content": (
                    f"Parse this table into structured data. Extract headers, rows, "
                    f"a one-sentence summary, and key factual claims.{ctx}\n\n"
                    f"Table:\n{table_text[:self._content_limit]}"
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
            self._format_evidence_block(b)
            for b in evidence_blocks[:self._max_evidence_blocks]
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
                    f"Cite sources using entity IDs and preserve loc when provided. "
                    f"If a figure supports a claim, prefer citing the figure directly. "
                    f"Identify open questions or gaps.\n\n"
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
            self._format_evidence_block(b)
            for b in evidence_blocks[:self._max_evidence_blocks]
        )

        ctx = ""
        if session_context:
            ctx = f"\n\nSession context:\n{session_context[:self._evidence_block_limit]}"

        return await self.extract(
            QAAnswer,
            messages=[{
                "role": "user",
                "content": (
                    f"Answer this research question using ONLY the provided evidence. "
                    f"Quote exact excerpts from sources. Preserve loc when available. "
                    f"If a figure contains the strongest evidence, cite it directly. "
                    f"Suggest follow-up questions.{ctx}\n\n"
                    f"Question: {question}\n\n"
                    f"Evidence:\n{evidence_text}"
                ),
            }],
        )

    def _format_evidence_block(self, block: dict) -> str:
        """Render an evidence block for QA/summary prompts."""
        header = f"[{block.get('entity_type', 'unknown')}:{block.get('entity_id', '?')}]"
        loc = block.get("loc")
        if loc:
            header = f"{header} ({loc})"
        return f"{header} {str(block.get('text', ''))[:self._evidence_block_limit]}"

    # ---------- v2.0 distillation pipeline ----------

    async def extract_claims(
        self, entry_content: str, existing_claims: list[str] | None = None,
    ) -> ExtractedClaims:
        """Extract structured claims from a journal entry."""
        dedup_hint = ""
        if existing_claims:
            limit = 50 if self.ctx >= 128_000 else 20 if self.ctx >= 32_000 else 10
            dedup_hint = (
                f"\n\nAlready extracted claims (do NOT duplicate these):\n"
                + "\n".join(f"- {c}" for c in existing_claims[:limit])
            )
        return await self.extract(
            ExtractedClaims,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract structured claims from this research journal entry. "
                    f"Each claim should be an atomic, self-contained statement with a type "
                    f"(hypothesis, evidence, method, result, observation, assumption). "
                    f"Provide character offsets into the source text for each claim. "
                    f"Do not paraphrase — stay close to the source wording.{dedup_hint}"
                    f"\n\nEntry:\n{entry_content[:self._content_limit]}"
                ),
            }],
        )

    async def verify_claim(
        self, claim_content: str, source_text: str,
    ) -> ClaimVerification:
        """Factored verification of a claim against its source text."""
        return await self.extract(
            ClaimVerification,
            messages=[{
                "role": "user",
                "content": (
                    f"Verify this extracted claim against the source text with three checks:\n"
                    f"1. Existence: Does the claim follow from or appear in the source?\n"
                    f"2. Number accuracy: Are quantities/percentages accurately extracted?\n"
                    f"3. Direction: Is the direction of effects correct (increase vs decrease)?\n\n"
                    f"Claim: {claim_content}\n\n"
                    f"Source text:\n{source_text[:self._content_limit]}"
                ),
            }],
        )

    async def assign_to_cluster(
        self,
        claim_content: str,
        claim_type: str,
        existing_clusters: list[dict],
        nearby_claims: list[dict],
    ) -> ClusterAssignment:
        """Determine which cluster a claim belongs to and its relations to nearby claims."""
        cluster_text = "\n".join(
            f"  {c['id']}: {c['label']} ({c.get('claim_count', 0)} claims)"
            for c in existing_clusters[:30]
        ) or "  (none — create a new cluster)"
        claims_text = "\n".join(
            f"  {c['id']}: [{c['claim_type']}] {c['content'][:200]}"
            for c in nearby_claims[:20]
        ) or "  (none)"
        return await self.extract(
            ClusterAssignment,
            messages=[{
                "role": "user",
                "content": (
                    f"Assign this claim to an evidence cluster and identify relations to nearby claims.\n\n"
                    f"Claim [{claim_type}]: {claim_content}\n\n"
                    f"Existing clusters:\n{cluster_text}\n\n"
                    f"Nearby claims in potential clusters:\n{claims_text}\n\n"
                    f"If no existing cluster is a good fit, set cluster_id to null and provide a new label."
                ),
            }],
        )

    async def synthesize_theme(
        self, cluster_label: str, claims: list[dict],
    ) -> ThemeSynthesis:
        """Generate a synthesis paragraph for an evidence cluster."""
        claims_text = "\n".join(
            f"- [{c.get('claim_type', '?')}] {c.get('content', '')[:300]} "
            f"(confidence: {c.get('confidence', '?')})"
            for c in claims[:50]
        )
        return await self.extract(
            ThemeSynthesis,
            messages=[{
                "role": "user",
                "content": (
                    f"Synthesize these claims into a coherent research theme for the cluster '{cluster_label}'.\n"
                    f"Identify: what's known, what's contested, what evidence is missing.\n"
                    f"Set confidence based on evidence strength and consistency.\n\n"
                    f"Claims:\n{claims_text}"
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
                    f"you cannot identify.\n\n{first_page_text[:self._content_limit]}"
                ),
            }],
        )
