# Discourse Synthesis and Plain Academic Style

Use this workflow after the claim spine and outline are current and before
drafting public prose. RKA constrains what the paper may say. It must not
determine the order, sentence boundaries, or surface vocabulary of the paper.

## Evidence graph and discourse graph

Keep two representations separate:

1. **Evidence graph.** RKA records claims, scope, support, qualifiers,
   counterevidence, decisions, and provenance. Preserve this graph completely.
2. **Discourse graph.** The manuscript guides a reader through a small number
   of propositions in a deliberate order. Build this graph for comprehension
   and persuasion, then attach its propositions back to the evidence graph.

The mapping is many-to-many. Several RKA records may support one sentence or
paragraph. One RKA claim may inform several rhetorical moves. A manuscript
unit is an argument-planning object, not a required paragraph boundary.

Never traverse journal entries, claims, clusters, or manuscript units in
record order and turn each item into prose. Journal chronology is relevant
only when the history of the research or design is itself part of the
argument.

## Plain academic target

Write in direct academic language with visible reasoning and restrained
technical detail. Use these positive features:

- Begin from a concrete problem, consequence, or observation before moving to
  an abstraction.
- Use an explicit logic ladder: context, problem, prior approach, gap, insight,
  challenge, response, evidence, and implication. Include only the moves the
  section needs.
- Give each paragraph one communicative job, but allow several claims and
  evidence records to serve that job.
- State the main point early. Explain why it follows and why it matters before
  adding implementation detail.
- Use examples to make a threat, failure, or design need tangible.
- Prefer common verbs such as `use`, `show`, `compare`, `measure`, `detect`,
  `build`, and `reduce`. Use a technical term when it is more precise, not
  merely more formal.
- Keep one name for one concept. Repetition of the exact technical term is
  clearer than elegant variation.
- Use first-person active constructions when the venue permits them: `we
  observe`, `we design`, `we evaluate`, and `the results show`.
- Let a sentence carry a real logical relation. Plain language does not require
  uniformly short sentences or a sequence of clipped statements.
- Present a challenge and its corresponding design response close together.
- State bounded contributions confidently. Put a material boundary where the
  reader interprets the affected claim, not as an unrelated confession in the
  opening narrative.

Avoid these negative patterns:

- RKA vocabulary, record IDs, evidence-status labels, or audit language in
  public prose unless the system's provenance mechanism is itself a research
  contribution.
- One sentence per source, one paragraph per claim, or one subsection per
  manuscript unit.
- Catalogs of controls, checks, fields, or components before the reader
  understands the problem they solve.
- Early defensive qualifications that interrupt the problem-to-insight path.
- Repeated labels such as `bounded`, `typed`, `current`, `immutable`, or
  `auditable` when a concrete explanation would be clearer.
- Dense noun stacks, unnecessary nominalizations, and abstract topic
  sentences that merely classify the literature.
- Mechanical transitions added to connect otherwise unrelated facts.
- A paragraph that ends without changing what the reader knows or expects
  next.

## Drafting workflow

### 1. Build an evidence packet

For the section, resolve current support, qualifiers, counterevidence,
conditions, allowed interpretation, prohibited wording, and publication
boundary. Keep exact IDs and source details in private notes.

Do not start prose from this packet.

### 2. Distill discourse propositions

Compress the packet into three to seven reader-facing propositions for a
normal section. A proposition is a statement the reader must understand for
the next move to follow. It may combine many records.

For each proposition, record privately:

- its reader-facing statement;
- its role in the section;
- the evidence bundle that supports it;
- the condition or qualifier that changes its meaning;
- the inference that connects it to the next proposition.

Merge duplicate and closely related records. Omit records that do not serve
the section's communicative job. Omission from prose does not remove them from
RKA.

### 3. Arrange the logic ladder

Choose the ladder that fits the section. Do not force every move into every
section.

**Introduction or motivation**

```text
concrete setting and stakes
-> current practice or prior approach
-> precise limitation
-> central observation or insight
-> technical challenges
-> corresponding design responses
-> strongest evidence and payoff
-> contribution summary
```

**System or method**

```text
goal and input-output contract
-> why the direct approach fails
-> design insight
-> mechanism
-> how the mechanism resolves the challenge
-> interface with the next component
```

**Evaluation or results**

```text
research question
-> setup needed to interpret the result
-> principal result
-> explanation or mechanism
-> comparison or sensitivity evidence
-> supported implication and material boundary
```

**NSF project or thrust**

```text
need and consequence
-> knowledge or capability gap
-> preliminary insight or evidence
-> objective
-> challenges
-> tasks matched to those challenges
-> evaluation and expected knowledge gain
```

The logic ladder is a reasoning path, not a set of headings. A reader should be
able to explain why each move makes the next move necessary.

### 4. Form paragraph cards

Group propositions into paragraphs before writing sentences. For each
paragraph, decide:

- **job:** what changes in the reader's understanding;
- **opening:** the main point or concrete setup;
- **development:** explanation, example, contrast, or evidence bundle;
- **bridge:** the inference that makes the next paragraph natural;
- **takeaway:** the claim the reader should retain.

A paragraph may realize several manuscript units, and a complex unit may span
several paragraphs. Choose boundaries from rhetorical continuity, not from RKA
IDs or unit keys.

### 5. Draft clean prose

Draft from the logic ladder and paragraph cards with RKA IDs, citations, and
private risk labels hidden. Keep the evidence packet available as a boundary,
not as a sentence template.

Explain the idea before the machinery. Delay exhaustive implementation lists
until the reader understands their purpose. Use the strongest concrete
example or result once; do not restate it in slightly different words merely
because several records support it.

### 6. Attach provenance post-hoc

After the prose is coherent, map each checkable assertion or substantive block
back to its evidence bundle. Add hidden provenance comments and validated
citations without changing the reader-facing organization. If a sentence
cannot be grounded, narrow or remove it. Do not split a coherent paragraph
into record-shaped fragments merely to make provenance attachment easier.

### 7. Revise in the right order

Run separate passes in this order:

1. **Section argument:** verify that the central takeaway and logic ladder are
   complete.
2. **Paragraph coherence:** verify topic continuity, known-to-new information,
   causal bridges, and non-redundant paragraph jobs.
3. **Plain language:** replace avoidable jargon, noun stacks, and abstract
   bookkeeping terms; define necessary terminology once.
4. **Evidence and boundaries:** verify every factual assertion, citation,
   qualifier, and M1/M2 treatment.
5. **Surface style:** run AI-tic, repetition, and venue checks last.

A linter pass does not establish coherence. Absence of banned terms, varied
sentence length, and valid provenance are necessary checks, not a writing
strategy.

## Coherence review

Before presenting a section to the PI, answer these questions from the public
prose alone:

1. What single takeaway does the section establish?
2. Why does each paragraph follow the previous one?
3. Does each paragraph develop one job rather than list several records?
4. Are challenges paired with the design choices that answer them?
5. Can a reader understand the idea before encountering detailed mechanisms?
6. Do examples and results advance the argument rather than decorate it?
7. Does the final paragraph deliver the promise made by the opening?
8. Would removing all provenance comments leave a fluent, self-contained
   manuscript?

If any answer is unclear, revise the discourse plan before polishing
sentences.

## Calibrating to author samples

When the author supplies several good examples and one or more disliked
examples, derive a project-local style profile before drafting:

1. Compare matched rhetorical locations such as abstracts, introduction
   openings, gap paragraphs, approach overviews, result summaries, and task
   descriptions.
2. Record positive patterns in logic order, paragraph construction,
   terminology, voice, example use, and technical-detail timing.
3. Record negative patterns as operational prohibitions, not vague labels such
   as `bad style`.
4. Paraphrase short examples; do not copy sentences from the calibration
   corpus into a new manuscript.
5. Treat the profile as a positive drafting target. Venue requirements and
   current PI instructions override it.

Do not imitate grammar errors, stale terminology, unsupported claims, or
venue-specific formatting from a sample. Learn the author's reasoning and
information-packaging habits rather than copying surface text.
