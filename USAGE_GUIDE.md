# RKA Usage Guide — Scenario-Based Walkthrough

This guide supplements the [README](README.md) with end-to-end usage examples for three common research scenarios. Each scenario shows the exact tool calls (Brain or Executor side), the order of operations, and how to rapidly build a populated knowledge base.

> **Convention**: Tool calls shown as `rka_tool_name(...)` represent what Claude Desktop (Brain) or Claude Code (Executor) would call through MCP. You can also make equivalent REST calls via `curl` or the web dashboard.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Scenario 1: Starting a New Research Project from Scratch](#scenario-1-starting-a-new-research-project-from-scratch)
- [Scenario 2: Taking Over a Project with Existing Manuscript and Reviews](#scenario-2-taking-over-a-project-with-existing-manuscript-and-reviews)
- [Scenario 3: Taking Over a Project with Scattered Ideas and Memos](#scenario-3-taking-over-a-project-with-scattered-ideas-and-memos)
- [Batch Import Techniques](#batch-import-techniques)
- [Academic Import Tools (Phase 5)](#academic-import-tools-phase-5)
- [Workspace Bootstrap](#workspace-bootstrap)
- [Web Dashboard Pages](#web-dashboard-pages)
- [Tips for Maintaining the Knowledge Base](#tips-for-maintaining-the-knowledge-base)

---

## Prerequisites

Before starting any scenario:

```bash
# 1. Make sure the server is running
rka serve

# 2. (Optional) Enable LLM enrichment for auto-tagging
#    Edit .env:
#    RKA_LLM_ENABLED=true
#    RKA_EMBEDDINGS_ENABLED=true
#    Then restart: rka serve
```

Ensure Claude Desktop and/or Claude Code have RKA configured as an MCP server (see [README — Quick Start](README.md#quick-start)).

---

## Scenario 1: Starting a New Research Project from Scratch

**Situation**: You have a research topic in mind but no existing artifacts — no papers collected, no code written, no manuscript drafted. You want to go from zero to a fully structured research knowledge base.

### Step 1: Initialize the Project

In your terminal:

```bash
mkdir ~/research/iot-ids-eval && cd ~/research/iot-ids-eval
rka init "IoT Intrusion Detection Evaluation" \
  --description "Comparative evaluation of ML-based IDS for IoT/CPS environments"
rka serve
```

### Step 2: Set the Research Phase and Initial Direction (Brain)

Open Claude Desktop. The Brain establishes the project's strategic framework:

```
Brain → rka_update_status(
    current_phase="literature_review",
    summary="Starting systematic review of ML-based IDS approaches for IoT/CPS.
             Focus on detection accuracy, computational overhead, and real-time feasibility.",
    blockers=None,
    metrics={"papers_target": 30, "papers_reviewed": 0}
)
```

### Step 3: Seed the Decision Tree (Brain)

Record the fundamental research decisions, even before answers are known:

```
Brain → rka_add_decision(
    question="Which IDS detection paradigm should we focus on?",
    phase="literature_review",
    decided_by="pi",
    options=[
        {"label": "Signature-based", "description": "Pattern matching against known threats", "explored": false},
        {"label": "Anomaly-based ML", "description": "ML models trained on normal behavior", "explored": false},
        {"label": "Hybrid", "description": "Combine signature + anomaly detection", "explored": false}
    ],
    rationale=None
)
→ returns dec_01ABC...

Brain → rka_add_decision(
    question="Which IoT protocol scope?",
    phase="literature_review",
    decided_by="brain",
    options=[
        {"label": "MQTT only", "description": "Most common IoT protocol", "explored": false},
        {"label": "MQTT + CoAP", "description": "Cover two major protocols", "explored": false},
        {"label": "Protocol-agnostic", "description": "Network-level features only", "explored": false}
    ],
    parent_id="dec_01ABC...",
    rationale=None
)
```

### Step 4: Assign a Literature Survey Mission (Brain → Executor)

```
Brain → rka_create_mission(
    phase="literature_review",
    objective="Survey recent ML-based IDS papers for IoT networks (2020-2026).
              Find 15-20 papers, extract key techniques, datasets used, and reported metrics.",
    tasks=[
        {"description": "Search IEEE Xplore, ACM DL, and arXiv for 'IoT intrusion detection machine learning'", "status": "pending"},
        {"description": "For each paper: record title, authors, year, venue, key findings", "status": "pending"},
        {"description": "Identify the 3 most commonly used datasets", "status": "pending"},
        {"description": "Compile a comparison table of techniques vs. detection rates", "status": "pending"}
    ],
    context="This is a new project. No prior literature has been collected.
             Focus on papers from top security and IoT venues.",
    acceptance_criteria="At least 15 papers cataloged with key findings extracted.
                        Comparison table ready for Brain review.",
    scope_boundaries="Do NOT start any implementation. Literature only.",
    checkpoint_triggers="Raise a checkpoint if you find a very recent survey paper that might change our scope."
)
```

### Step 5: Executor Picks Up and Works

Claude Code connects, retrieves the mission, and begins:

```
Executor → rka_get_mission()
→ "Survey recent ML-based IDS papers..."

# Executor searches, reads papers, and logs each one:

Executor → rka_add_literature(
    title="A Survey on Intrusion Detection Systems for IoT Networks",
    authors=["A. Khraisat", "I. Gondal", "P. Vamplew"],
    year=2024,
    venue="IEEE IoT Journal",
    doi="10.1109/JIOT.2024.xxxxx",
    abstract="This paper surveys ML-based intrusion detection...",
    key_findings=[
        "Random Forest and CNN achieve highest detection rates (>97%)",
        "CICIDS2017 and NSL-KDD remain the most used benchmark datasets",
        "Real-time performance is rarely evaluated in existing work"
    ],
    relevance="Comprehensive survey — identifies gaps our work can fill",
    added_by="executor"
)

Executor → rka_add_literature(
    title="Lightweight CNN for IoT Traffic Anomaly Detection",
    authors=["J. Zhang", "M. Chen"],
    year=2025,
    venue="ACM CCS",
    key_findings=[
        "Pruned CNN achieves 95.2% detection with 3x less compute",
        "Tested on MQTT traffic from real smart home deployment",
        "Misses slow-rate attacks (below 12% detection for slowloris)"
    ],
    relevance="Directly relevant — lightweight approach for constrained IoT",
    added_by="executor"
)

# ... repeat for each paper ...
```

### Step 6: Executor Logs Insights Along the Way

```
Executor → rka_add_note(
    content="Most papers use CICIDS2017 or NSL-KDD, but both are outdated
             (pre-2020 traffic patterns). Only 2 out of 12 papers tested on
             real IoT traffic. This is a clear gap we can exploit.",
    type="insight",
    source="executor",
    phase="literature_review",
    confidence="tested",
    importance="high"
)

Executor → rka_add_note(
    content="Three papers mention MQTT-specific features (topic structure,
             QoS patterns) as more discriminative than generic network features.
             This supports focusing on MQTT-specific detection.",
    type="finding",
    source="executor",
    confidence="hypothesis",
    importance="normal",
    related_literature=["lit_01DEF...", "lit_01GHI...", "lit_01JKL..."]
)
```

### Step 7: Executor Raises a Checkpoint When Needed

```
Executor → rka_submit_checkpoint(
    mission_id="mis_01XYZ...",
    type="decision",
    description="Found a 2026 survey that already covers most of our planned scope.
                Should we narrow focus to MQTT-specific detection to differentiate?",
    options=[
        {"label": "Narrow to MQTT", "description": "Focus exclusively on MQTT protocol anomalies",
         "consequence": "Stronger novelty claim, smaller scope"},
        {"label": "Keep broad scope", "description": "Continue with protocol-agnostic approach",
         "consequence": "More comprehensive but less novel"},
        {"label": "Pivot to real-traffic evaluation", "description": "Focus on evaluation methodology gap",
         "consequence": "Different angle — evaluate existing methods on real IoT traffic"}
    ],
    recommendation="Option 3 — the evaluation gap seems strongest based on literature",
    blocking=true
)
```

### Step 8: Brain Resolves and Directs Next Phase

```
Brain → rka_resolve_checkpoint(
    id="chk_01MNO...",
    resolution="Go with option 3: focus on real-traffic evaluation methodology.
               This differentiates us from the existing survey.",
    resolved_by="brain",
    rationale="The survey gap in real-traffic evaluation is confirmed by 10+ papers
              using only synthetic datasets. Original contribution is clear.",
    create_decision=true
)

Brain → rka_update_status(
    current_phase="experiment_design",
    summary="Pivoted to evaluation methodology focus. Will compare 3 IDS frameworks
             on real IoT traffic vs. standard benchmarks.",
    metrics={"papers_target": 30, "papers_reviewed": 14}
)
```

### Step 9: Executor Submits the Mission Report

```
Executor → rka_submit_report(
    mission_id="mis_01XYZ...",
    tasks_completed=[
        "Searched IEEE Xplore, ACM DL, arXiv — 14 papers cataloged",
        "Key techniques identified: RF, CNN, LSTM, Autoencoder, GNN",
        "Top datasets: CICIDS2017, NSL-KDD, IoT-23",
        "Comparison table with detection rates compiled"
    ],
    findings=[
        "97% of papers use synthetic or outdated datasets",
        "Only 2 papers evaluate on real IoT deployments",
        "MQTT-specific features outperform generic network features in 3 studies",
        "No paper compares more than 2 IDS frameworks on the same real traffic"
    ],
    anomalies=[
        "Several papers report >99% accuracy but use train/test split from same capture session (data leakage risk)"
    ],
    questions=[
        "Should we collect our own MQTT traffic or use an existing IoT testbed?",
        "Which 3 IDS frameworks should we compare?"
    ],
    recommended_next="Design the evaluation framework: select IDS tools, define metrics, plan traffic collection"
)
```

At this point your knowledge base has: 14+ literature entries, a growing decision tree, journal entries with cross-references, and a complete audit trail — all searchable and context-aware.

---

## Scenario 2: Taking Over a Project with Existing Manuscript and Reviews

**Situation**: You're joining (or resuming) a project that already has a draft manuscript, reviewer feedback, collected data, and experimental code. You need to ingest all of this into RKA quickly so the Brain can reason over it.

### Step 1: Initialize and Set Phase

```bash
mkdir ~/research/cps-anomaly && cd ~/research/cps-anomaly
rka init "CPS Anomaly Detection" \
  --description "Resumed project — ML anomaly detection for cyber-physical systems. R1 revision in progress."
rka serve
```

```
Brain → rka_update_status(
    current_phase="revision_r1",
    summary="Taking over existing project with submitted manuscript and R1 reviews received.
             Need to catalog existing work and address reviewer comments.",
    blockers="Reviewer 2 requested new experiments on larger dataset"
)
```

### Step 2: Ingest the Manuscript Structure as Decisions (Brain)

Read through the manuscript and record the key research decisions that were already made:

```
Brain → rka_add_decision(
    question="What anomaly detection approach for CPS?",
    phase="initial_design",
    decided_by="pi",
    chosen="Autoencoder + LSTM hybrid",
    rationale="Autoencoder handles spatial features, LSTM captures temporal patterns.
              Justified in Section 3 of the manuscript.",
    options=[
        {"label": "Autoencoder + LSTM hybrid", "description": "Two-stage model", "explored": true},
        {"label": "Isolation Forest", "description": "Tree-based anomaly detection", "explored": true},
        {"label": "GNN-based", "description": "Graph neural network on CPS topology", "explored": false}
    ]
)
→ dec_01ROOT...

Brain → rka_add_decision(
    question="Which CPS dataset for evaluation?",
    phase="initial_design",
    decided_by="pi",
    chosen="SWaT + WADI",
    rationale="SWaT is the standard CPS benchmark. WADI adds water distribution context.",
    parent_id="dec_01ROOT...",
    options=[
        {"label": "SWaT + WADI", "description": "Standard CPS security datasets from iTrust", "explored": true},
        {"label": "BATADAL", "description": "Water distribution attacks", "explored": false},
        {"label": "Custom testbed", "description": "Collect from lab CPS", "explored": false}
    ]
)

Brain → rka_add_decision(
    question="How to handle class imbalance?",
    phase="experiment",
    decided_by="pi",
    chosen="SMOTE oversampling",
    rationale="Used SMOTE in training set only, kept test set at natural distribution.",
    parent_id="dec_01ROOT..."
)
```

### Step 3: Bulk-Ingest the Reference List (Brain or Executor)

Assign a mission to quickly populate the literature database from the manuscript's bibliography:

```
Brain → rka_create_mission(
    phase="revision_r1",
    objective="Ingest all 32 references from the manuscript bibliography into the literature database.
              Mark status as 'cited'. For the 5 most important papers, extract key findings.",
    tasks=[
        {"description": "Parse references from manuscript.bib or bibliography section", "status": "pending"},
        {"description": "Add all 32 papers with title, authors, year, venue", "status": "pending"},
        {"description": "For top-5 papers, add key_findings and relevance notes", "status": "pending"}
    ],
    acceptance_criteria="All 32 references in RKA, top 5 with key findings"
)
```

The Executor can then bulk-add:

```
Executor → rka_add_literature(
    title="A Systematic Study of DNN-based CPS Anomaly Detection",
    authors=["Y. Li", "R. Peng", "H. Song"],
    year=2023,
    venue="IEEE TDSC",
    doi="10.1109/TDSC.2023.xxxxx",
    status="cited",
    key_findings=[
        "Autoencoder outperforms IF on multivariate time series",
        "Window size of 50 timesteps optimal for SWaT"
    ],
    relevance="Core reference — our architecture builds on their autoencoder design",
    added_by="executor"
)

# ... repeat for remaining references, at minimum:
Executor → rka_add_literature(
    title="...", authors=["..."], year=2022, venue="...", status="cited", added_by="executor"
)
```

### Step 4: Ingest Reviewer Comments as PI Instructions (Brain)

Each reviewer comment becomes a traceable PI instruction:

```
Brain → rka_add_note(
    content="[Reviewer 1, Comment 3] The evaluation should include a comparison with
             at least one traditional (non-DL) baseline such as One-Class SVM or
             Isolation Forest. The current comparison only includes deep learning methods.",
    type="pi_instruction",
    source="pi",
    phase="revision_r1",
    importance="critical",
    confidence="verified"
)
→ jrn_01R1C3...

Brain → rka_add_note(
    content="[Reviewer 2, Major Comment 1] The SWaT dataset alone is insufficient.
             Please evaluate on at least one additional CPS dataset to demonstrate
             generalizability. WADI is acceptable but a third dataset would strengthen the claim.",
    type="pi_instruction",
    source="pi",
    phase="revision_r1",
    importance="critical",
    confidence="verified"
)
→ jrn_01R2M1...

Brain → rka_add_note(
    content="[Reviewer 2, Minor Comment 5] Table 3 is missing standard deviations.
             Please report mean ± std over multiple runs.",
    type="pi_instruction",
    source="pi",
    phase="revision_r1",
    importance="high",
    confidence="verified"
)

Brain → rka_add_note(
    content="[Reviewer 3, Comment 1] The paper would benefit from a discussion of
             computational overhead and real-time feasibility of the proposed approach.",
    type="pi_instruction",
    source="pi",
    phase="revision_r1",
    importance="high",
    confidence="verified"
)
```

### Step 5: Record Existing Results as Findings

```
Brain → rka_add_note(
    content="Current model achieves 94.7% F1 on SWaT and 91.2% F1 on WADI.
             These are the results from the submitted manuscript, Table 3.
             Autoencoder-LSTM with window=50, latent_dim=32, LSTM_units=64.",
    type="finding",
    source="pi",
    phase="experiment",
    confidence="verified",
    importance="high"
)

Brain → rka_add_note(
    content="Training time: 45 minutes on single V100. Inference: 1200 samples/sec.
             This is fast enough for real-time CPS monitoring at 100Hz sensor rate.",
    type="finding",
    source="pi",
    phase="experiment",
    confidence="verified",
    importance="normal"
)
```

### Step 6: Create Revision Missions (Brain → Executor)

Now create targeted missions for each major revision task:

```
Brain → rka_create_mission(
    phase="revision_r1",
    objective="Add Isolation Forest and One-Class SVM baselines to the evaluation
              (addresses Reviewer 1, Comment 3).",
    tasks=[
        {"description": "Implement IF baseline with scikit-learn on SWaT features", "status": "pending"},
        {"description": "Implement OC-SVM baseline with RBF kernel", "status": "pending"},
        {"description": "Run both on SWaT and WADI with same preprocessing", "status": "pending"},
        {"description": "Add results to Table 3 with mean ± std over 5 runs", "status": "pending"}
    ],
    context="Reviewer 1 requires non-DL baselines. Use same features and train/test split
             as the autoencoder-LSTM. Our current best: 94.7% F1 on SWaT.",
    acceptance_criteria="IF and OC-SVM results added to results table,
                        reproducible with provided scripts.",
    related_notes=["jrn_01R1C3..."]
)

Brain → rka_create_mission(
    phase="revision_r1",
    objective="Add BATADAL dataset evaluation (addresses Reviewer 2, Major Comment 1).
              Third dataset to demonstrate generalizability.",
    tasks=[
        {"description": "Download and preprocess BATADAL dataset", "status": "pending"},
        {"description": "Adapt feature extraction pipeline for BATADAL format", "status": "pending"},
        {"description": "Run autoencoder-LSTM + both baselines", "status": "pending"},
        {"description": "Report results with mean ± std", "status": "pending"}
    ],
    acceptance_criteria="BATADAL results added, all models compared,
                        cross-dataset analysis written.",
    checkpoint_triggers="If BATADAL preprocessing reveals incompatible features,
                        raise a checkpoint before adapting the model."
)
```

### What You End Up With

After this ingestion session (typically 30-60 minutes), your knowledge base contains:

- **Decision tree**: The full research path with rationale, reconstructed from the manuscript
- **Literature**: All cited references, searchable, with key findings for the most important ones
- **Journal entries**: Reviewer comments as traceable instructions, existing results as verified findings
- **Missions**: Specific revision tasks linked to reviewer comments
- **Audit trail**: Who added what, when, and why

From here, the Brain can call `rka_get_context(topic="reviewer comments on baselines")` and get a focused summary of everything related to the baseline evaluation task.

---

## Scenario 3: Taking Over a Project with Scattered Ideas and Memos

**Situation**: You have a folder of meeting notes, email threads, a rough outline, a few reference PDFs, and some prototype code — but nothing is organized. You need to turn this scattered collection into a structured knowledge base.

### Step 1: Initialize and Assess

```bash
mkdir ~/research/federated-iot && cd ~/research/federated-iot
rka init "Federated Learning for IoT Security" \
  --description "Early-stage exploration — federated anomaly detection across IoT devices"
rka serve
```

### Step 2: Have the Executor Catalog What Exists (Brain → Executor)

Before ingesting anything, understand what you have:

```
Brain → rka_create_mission(
    phase="setup",
    objective="Catalog all existing research artifacts in the project folder.
              List every document, code file, and note — but do NOT ingest yet.
              Just produce an inventory.",
    tasks=[
        {"description": "List all files in ~/research-notes/federated-iot/", "status": "pending"},
        {"description": "Summarize each document (1-2 lines) and classify: meeting notes, literature, code, idea sketch, email thread", "status": "pending"},
        {"description": "Identify which items are actionable research ideas vs. background context", "status": "pending"}
    ],
    acceptance_criteria="Complete inventory with classification, submitted as report"
)
```

The Executor reads through the files and submits a report:

```
Executor → rka_submit_report(
    mission_id="mis_01ABC...",
    tasks_completed=["Full inventory of 23 files completed"],
    findings=[
        "3 meeting notes (advisor meetings Jan-Mar) with action items",
        "7 PDFs — 5 relevant papers, 2 tangential",
        "1 rough outline (Google Doc export) for a workshop paper",
        "2 email threads with collaborator discussing dataset access",
        "4 Python notebooks with prototype federated averaging code",
        "6 misc text files with scattered ideas and TODO lists"
    ],
    questions=[
        "Should I ingest the email threads or just the actionable items from them?",
        "The prototype code is messy — should I log its architecture decisions or skip?"
    ],
    recommended_next="Ingest in order: (1) meeting notes as PI instructions,
                     (2) papers as literature, (3) outline as decisions,
                     (4) ideas as journal entries"
)
```

### Step 3: Brain Reviews and Creates Ingestion Plan

```
Brain → rka_resolve_checkpoint(...)  # if any were raised

Brain → rka_add_note(
    content="Ingestion plan: (1) Meeting notes → pi_instruction entries with action items.
             (2) Papers → literature entries. (3) Workshop outline → decision tree skeleton.
             (4) Scattered ideas → hypothesis/idea journal entries.
             (5) Prototype code → methodology notes.
             Skip raw email threads — extract only the dataset access decision.",
    type="pi_instruction",
    source="brain",
    phase="setup",
    importance="high"
)
```

### Step 4: Ingest Meeting Notes as Instructions and Observations (Executor)

```
# From meeting notes: Jan 15 advisor meeting
Executor → rka_add_note(
    content="[Advisor meeting Jan 15] PI suggests focusing on non-IID data distribution
             as the key challenge. Most federated learning papers assume IID —
             IoT devices have inherently non-IID traffic patterns.",
    type="pi_instruction",
    source="pi",
    phase="exploration",
    importance="critical"
)

Executor → rka_add_note(
    content="[Advisor meeting Jan 15] Discussed using differential privacy for gradient
             updates. PI concerned about accuracy trade-off. Wants experiments showing
             privacy budget vs. detection accuracy curve.",
    type="pi_instruction",
    source="pi",
    phase="exploration",
    importance="high"
)

# From meeting notes: Feb 20 advisor meeting
Executor → rka_add_note(
    content="[Advisor meeting Feb 20] Action item: contact Samsung IoT lab about
             accessing their smart home traffic dataset. PI has a contact there.",
    type="pi_instruction",
    source="pi",
    phase="exploration",
    importance="normal"
)

Executor → rka_add_note(
    content="[Advisor meeting Feb 20] Collaborator mentioned that FedAvg fails badly
             when devices have very different traffic volumes. May need FedProx or
             per-device weighting.",
    type="observation",
    source="pi",
    phase="exploration",
    importance="high"
)
```

### Step 5: Ingest Papers (Executor)

```
Executor → rka_add_literature(
    title="Communication-Efficient Learning of Deep Networks from Decentralized Data",
    authors=["H.B. McMahan", "E. Moore", "D. Ramage"],
    year=2017,
    venue="AISTATS",
    key_findings=[
        "FedAvg converges with 10-100x less communication than FedSGD",
        "Non-IID partitions significantly slow convergence",
        "Works best with large local batch sizes"
    ],
    relevance="Foundational paper — FedAvg is our baseline algorithm",
    status="read",
    added_by="executor"
)

Executor → rka_add_literature(
    title="Federated Anomaly Detection for IoT Security",
    authors=["T. Nguyen", "S. Marchal", "M. Miettinen"],
    year=2023,
    venue="IEEE TIFS",
    key_findings=[
        "First to apply federated learning to IoT anomaly detection",
        "88% detection rate with federated autoencoder — 6% lower than centralized",
        "Privacy guarantee via secure aggregation, not differential privacy"
    ],
    relevance="Most directly related prior work — we aim to improve their 88% number",
    status="read",
    added_by="executor"
)

# For papers not yet read, just catalog them:
Executor → rka_add_literature(
    title="FedProx: Heterogeneous Federated Optimization",
    authors=["T. Li", "A.K. Sahu", "M. Zaheer"],
    year=2020,
    venue="MLSys",
    relevance="Potential alternative to FedAvg for heterogeneous IoT devices",
    status="to_read",
    added_by="executor"
)
```

### Step 6: Ingest the Workshop Outline as a Decision Skeleton (Brain)

The rough outline reveals implicit decisions. Record them explicitly:

```
Brain → rka_add_decision(
    question="What is our core contribution?",
    phase="exploration",
    decided_by="brain",
    options=[
        {"label": "Non-IID federated anomaly detection", "description": "Handle non-IID IoT traffic distributions", "explored": true},
        {"label": "Privacy-preserving IDS", "description": "Differential privacy + anomaly detection", "explored": true},
        {"label": "Communication-efficient IDS", "description": "Reduce communication for resource-constrained IoT", "explored": false}
    ],
    rationale="Workshop outline focused on non-IID challenge. PI also interested in privacy angle.
              Not yet decided — needs more exploration."
)
→ dec_01CORE...

Brain → rka_add_decision(
    question="Federated algorithm choice?",
    phase="exploration",
    decided_by="brain",
    parent_id="dec_01CORE...",
    options=[
        {"label": "FedAvg", "description": "Standard baseline", "explored": true},
        {"label": "FedProx", "description": "Better for heterogeneous settings", "explored": false},
        {"label": "FedNova", "description": "Normalized averaging", "explored": false},
        {"label": "Custom weighted", "description": "Device-specific weights based on traffic volume", "explored": false}
    ]
)

Brain → rka_add_decision(
    question="Target venue?",
    phase="exploration",
    decided_by="pi",
    chosen="ACM WiSec 2026 Workshop",
    rationale="Short paper for workshop, then expand to full IEEE TIFS submission.",
    options=[
        {"label": "ACM WiSec 2026 Workshop", "description": "4-page workshop paper, deadline June", "explored": true},
        {"label": "IEEE TIFS", "description": "Full journal paper", "explored": false}
    ]
)
```

### Step 7: Ingest Scattered Ideas (Executor)

Turn those text files and sticky notes into searchable, tagged entries:

```
Executor → rka_add_note(
    content="Idea: Use device fingerprinting as a pre-filter before anomaly detection.
             Each IoT device has a unique traffic signature — if traffic doesn't match
             any known device fingerprint, flag it before even running the anomaly model.",
    type="idea",
    source="pi",
    phase="exploration",
    confidence="hypothesis",
    importance="high",
    tags=["device-fingerprinting", "pre-filter"]
)

Executor → rka_add_note(
    content="What if we use a GAN to generate synthetic attack traffic for devices
             that have no attack data? This would solve the label scarcity problem
             for new IoT device types joining the federation.",
    type="idea",
    source="pi",
    phase="exploration",
    confidence="hypothesis",
    importance="normal"
)

Executor → rka_add_note(
    content="From email with collaborator (Mar 5): Samsung dataset has 45 device types,
             3 months of traffic, but NO labeled attacks. Would need to inject synthetic
             attacks or use the unlabeled data for training the 'normal' model only.",
    type="observation",
    source="pi",
    phase="exploration",
    importance="high"
)

Executor → rka_add_note(
    content="Prototype code implements FedAvg with a simple autoencoder (3-layer).
             Architecture: input(40) → enc(20) → latent(10) → dec(20) → output(40).
             Tested on dummy data only — not validated on real IoT traffic yet.",
    type="methodology",
    source="executor",
    phase="exploration",
    confidence="hypothesis",
    importance="normal"
)
```

**Alternative**: If your scattered ideas are already in a single markdown file with headings, use `rka_ingest_document` instead of adding notes one by one — it splits the document by headings automatically and classifies each section:

```
Executor → rka_ingest_document(
    content=<contents of ideas.md>,
    source="pi",
    phase="exploration",
    tags=["initial-ideas"]
)
```

### Step 8: Establish the Knowledge Base Summary (Brain)

After ingestion, the Brain synthesizes:

```
Brain → rka_get_context(
    topic="federated learning IoT anomaly detection",
    max_tokens=3000,
    depth="detailed"
)
→ Returns a context package with all ingested knowledge, organized by temperature

Brain → rka_update_status(
    current_phase="exploration",
    summary="Ingested 4 meeting notes, 5 literature entries, 6 research ideas,
             prototype code notes, and workshop outline.
             Core direction: non-IID federated anomaly detection for IoT.
             Key open question: FedAvg vs. FedProx vs. custom weighting.
             Next: design experiments to compare federated algorithms.",
    metrics={
        "literature_count": 5,
        "ideas_captured": 6,
        "decisions_open": 3,
        "decisions_resolved": 1
    }
)
```

### What You End Up With

From a messy folder of 23 files, you now have:

- **5 literature entries** — searchable by title, author, year, venue, with relevance notes
- **8 journal entries** — meeting action items, observations, ideas, methodology notes
- **4 decision nodes** — research direction choices (some open, some resolved)
- **Complete audit trail** — everything traceable to its source (meeting, email, paper)
- **Searchable context** — `rka_search("non-IID")` returns all related entries across all types

---

## Batch Import Techniques

### Importing a BibTeX File

RKA has a dedicated BibTeX import tool that parses `.bib` content, extracts all entries, auto-detects duplicates by DOI and title, and creates literature entries in one call:

```
Brain → rka_import_bibtex(
    bibtex="@article{li2020federated,
      title={Federated Learning: Challenges, Methods, and Future Directions},
      author={Li, Tian and Sahu, Anit Kumar and Talwalkar, Ameet and Smith, Virginia},
      journal={IEEE Signal Processing Magazine},
      year={2020},
      doi={10.1109/MSP.2020.2975749}
    }
    @inproceedings{mcmahan2017fedavg,
      title={Communication-Efficient Learning of Deep Networks from Decentralized Data},
      author={McMahan, H. Brendan and Moore, Eider and Ramage, Daniel},
      booktitle={AISTATS},
      year={2017}
    }",
    default_status="cited",
    skip_duplicates=true
)
→ Returns: {total_parsed: 2, imported: [{id: "lit_01ABC...", title: "Federated Learning: ..."}], skipped: [], errors: []}
```

The Executor can also read a `.bib` file from disk and pass the contents:

```
Executor → rka_import_bibtex(
    bibtex="<contents of references.bib>",
    default_status="cited",
    skip_duplicates=true
)
```

Or use the REST API to upload a `.bib` file directly:

```bash
curl -X POST http://localhost:9712/api/import/bibtex-file \
  -F "file=@references.bib" \
  -F "default_status=cited" \
  -F "skip_duplicates=true"
```

For manual entry of individual papers (when you need to include key findings and relevance notes), the existing `rka_add_literature()` tool is still the best choice.

### Importing Reviewer Comments Systematically

For structured review comments (e.g., from OpenReview, HotCRP, or CMT):

```
# Pattern: one pi_instruction per actionable comment
Executor → rka_add_note(
    content="[R1.3] Add ablation study removing each component...",
    type="pi_instruction",
    source="pi",
    phase="revision_r1",
    importance="critical"  # for major comments
)

Executor → rka_add_note(
    content="[R2.7] Fix typo in Equation 4...",
    type="pi_instruction",
    source="pi",
    phase="revision_r1",
    importance="low"  # for minor comments
)
```

Use importance levels to triage: `critical` for major revisions, `high` for significant changes, `normal` for moderate, `low` for typos and formatting.

### Batch Import Multiple Entity Types

Use `rka_batch_import` to import a mix of notes, literature, and decisions in a single call:

```
Brain → rka_batch_import(
    entries=[
        {"entity_type": "literature", "data": {"title": "Paper A", "authors": ["Author 1"], "year": 2024, "status": "to_read"}},
        {"entity_type": "literature", "data": {"title": "Paper B", "authors": ["Author 2"], "year": 2023, "status": "cited"}},
        {"entity_type": "note", "data": {"content": "Key insight from meeting notes", "type": "insight", "source": "pi"}},
        {"entity_type": "decision", "data": {"question": "Which framework to use?", "phase": "design", "decided_by": "brain"}}
    ],
    actor="import"
)
→ Returns: {imported: [{index: 0, id: "lit_01...", type: "literature"}, ...], errors: []}
```

This is especially useful when migrating from another system or ingesting structured documents that contain mixed entity types.

### Document Ingestion

Use `rka_ingest_document` to send a full markdown document and have it automatically split into individual journal entries by heading. Each `##` or `###` heading becomes a separate entry with auto-classified type and tags:

```
Brain → rka_ingest_document(
    content="## Anomaly Detection Findings\n\nAutoencoder outperforms...\n\n## Methodology Notes\n\nUsed 5-fold cross-validation...\n\n## Next Steps\n\nInvestigate attention mechanisms...",
    source="brain",
    phase="experiment",
    tags=["round-1"]
)
→ Ingested document: 3 entries created from 3 sections
  + jrn_01ABC [finding] Anomaly Detection Findings (142 chars)
  + jrn_01DEF [methodology] Methodology Notes (98 chars)
  + jrn_01GHI [idea] Next Steps (76 chars)
```

**How it works:**
- Splits on `##` and `###` headings — each section becomes one journal entry
- Auto-classifies entry type from heading keywords (e.g. "methodology" → methodology, "findings" → finding, "next steps" → idea)
- Derives a tag from each heading (slugified: "Anomaly Detection Findings" → `anomaly-detection-findings`)
- Base `tags` you provide are applied to all entries; heading-derived tags are added per entry
- Content before the first heading becomes a separate "preamble" entry
- Set `split_by_headings=false` to import the entire document as a single entry

This is ideal for the Brain to push structured analysis, literature reviews, or session summaries into the knowledge base in a single call.

### Importing from a Structured Notes Document

For documents containing **mixed entity types** (notes, literature, decisions), use `rka_batch_import`. For pure markdown documents that should become journal entries, `rka_ingest_document` is simpler and handles splitting automatically.

For mixed-type imports, create a mission to orchestrate:

```
Brain → rka_create_mission(
    phase="setup",
    objective="Parse research-notes.md and import each section as the appropriate
              RKA entity type. Headings that start with 'Decision:' become decisions.
              Headings with 'Paper:' become literature. Everything else becomes journal entries.",
    tasks=[
        {"description": "Read and parse research-notes.md", "status": "pending"},
        {"description": "Import 'Decision:' sections as rka_add_decision", "status": "pending"},
        {"description": "Import 'Paper:' sections as rka_add_literature", "status": "pending"},
        {"description": "Import remaining sections as rka_add_note", "status": "pending"}
    ],
    acceptance_criteria="All content from research-notes.md imported into RKA"
)
```

**Tip**: If your document contains only journal-type content (findings, insights, ideas), skip the mission overhead and use `rka_ingest_document` directly — it handles splitting, classification, and tagging automatically.

---

## Academic Import Tools (Phase 5)

Phase 5 adds powerful tools for discovering, importing, and enriching academic literature.

### DOI Auto-Enrichment

After importing papers (via BibTeX or manually), enrich them with metadata from CrossRef:

```
Brain → rka_enrich_doi(lit_id="lit_01ABC...")
→ Returns: {status: "enriched", fields_updated: ["abstract", "venue", "url"]}
```

This looks up the paper's DOI via the CrossRef API and fills in any missing fields (title, authors, year, venue, abstract, URL). Fields that already have values are not overwritten.

### Searching Semantic Scholar

Search the Semantic Scholar database for papers related to your research:

```
Brain → rka_search_semantic_scholar(
    query="federated learning IoT anomaly detection",
    limit=10,
    year_min=2022,
    fields_of_study=["Computer Science"],
    add_to_library=false
)
→ Returns up to 10 papers with title, authors, year, abstract, citation count, and URLs
```

Set `add_to_library=true` to automatically create literature entries for all results:

```
Brain → rka_search_semantic_scholar(
    query="differential privacy federated learning",
    limit=5,
    add_to_library=true
)
→ Results are returned AND added to the literature database with status "to_read"
```

### Searching arXiv

Search arXiv for preprints and recent papers:

```
Executor → rka_search_arxiv(
    query="machine learning cyber physical systems security",
    limit=10,
    sort_by="submittedDate",
    add_to_library=false
)
→ Returns arXiv papers with title, authors, abstract, categories, and PDF/HTML links
```

As with Semantic Scholar, set `add_to_library=true` to auto-add results to your literature database.

### Mermaid Decision Tree Export

Export your decision tree as a Mermaid flowchart diagram for inclusion in documents or presentations:

```
Brain → rka_export_mermaid(phase="literature_review", active_only=false)
→ Returns Mermaid syntax:
  graph TD
    dec_01ABC["Which detection paradigm?<br/>✅ Anomaly-based ML"]
    dec_01ABC --> dec_01DEF["Which protocol scope?<br/>❓ Unresolved"]
    ...
```

The Mermaid output uses status-based styling:
- **Active** decisions: green border
- **Abandoned** decisions: red dashed border
- **Revisit** decisions: yellow border
- **Unresolved** decisions: default style

You can also get this via the REST API:

```bash
curl http://localhost:9712/api/decisions/mermaid?phase=literature_review
```

Or via the general export tool:

```
Brain → rka_export(scope="decisions", format="mermaid")
```

### Workflow Example: Literature Discovery Pipeline

A typical workflow combining these tools:

```
# 1. Search for papers on your topic
Brain → rka_search_semantic_scholar(
    query="IoT intrusion detection evaluation methodology",
    limit=20,
    year_min=2023,
    add_to_library=true
)

# 2. Enrich any papers that have DOIs but missing metadata
Brain → rka_enrich_doi(lit_id="lit_01NEW...")

# 3. Also check arXiv for recent preprints
Brain → rka_search_arxiv(
    query="IoT intrusion detection real traffic evaluation",
    limit=10,
    add_to_library=true
)

# 4. Import your existing BibTeX bibliography
Brain → rka_import_bibtex(
    bibtex="<contents of references.bib>",
    skip_duplicates=true
)

# 5. Ingest a literature review document as journal entries
Brain → rka_ingest_document(
    content="## Key Themes\n\nMost papers use...\n\n## Methodology Gaps\n\nFew studies evaluate...",
    source="brain",
    phase="literature_review",
    tags=["survey-synthesis"]
)

# 6. Review everything in the web dashboard
#    Navigate to /literature to see all imported papers
#    Navigate to /graph to see entity relationships
```

---

## Workspace Bootstrap

The workspace bootstrap feature lets you drop all your existing research files (code, meeting notes, manuscripts, PDFs, BibTeX) into a folder and have RKA detect, classify, and ingest them into the knowledge base in one shot. This is designed for the RKA → Brain → Executor workflow:

1. **RKA** (this feature) does fast scan + ingest with regex heuristics + optional local LLM classification
2. **Brain** reviews the bootstrap via `rka_review_bootstrap()` and reorganizes entries
3. **Executor** is delegated deep analysis tasks (e.g., reading complex PDFs, cross-referencing)

### Supported File Types

| Extension | Category | What Happens |
|-----------|----------|--------------|
| `.md`, `.markdown` | Markdown | Split by headings into multiple journal entries |
| `.txt` | Text | Single entry or split by headings |
| `.bib`, `.bibtex` | BibTeX | Each entry → literature record |
| `.pdf` | PDF | Literature entry (title from metadata or LLM) |
| `.py`, `.r`, `.do`, `.js`, `.ts`, `.jl` | Code | Single journal entry with docstring + first 50 lines |
| `.docx` | Document | Text extracted and split by headings (requires `python-docx`) |
| `.csv`, `.xlsx` | Data | Single observation entry with file metadata |

### Quick Bootstrap (One-Shot via MCP)

The fastest way to bootstrap — Brain calls a single tool:

```
rka_bootstrap_workspace(
    folder_path="~/research/my_project/files",
    phase="phase_1",
    override_tags=["bootstrap", "initial-import"]
)
```

This scans the folder, classifies every file, ingests them into the knowledge base, and returns a summary:

```
✅ Bootstrap complete
   Scan ID: scn_01HXY...
   Processed: 23 files
   Created: 47 entries (markdown files split into multiple entries)
   Skipped: 2 (duplicates)
   Errors: 0

   By category: markdown=8, pdf=5, code=4, bibtex=2, text=3, data=1
   By target: ingest_document=11, literature_entry=5, journal_entry=5, import_bibtex=2
```

### Two-Step Workflow (Scan → Review → Ingest)

For more control, scan first and review before ingesting:

**Step 1: Scan and preview**

```
rka_scan_workspace(
    folder_path="~/research/my_project/files",
    use_llm=true
)
```

Returns a manifest showing how each file would be classified:

```
📂 Scanned: /home/user/research/my_project/files
   Files: 25 found, 23 scanned (2 ignored)

   INGEST AS DOCUMENT (11 files):
     meeting_notes.md [markdown, meeting_notes → summary]
     draft_paper.md [markdown, paper_manuscript → finding]
     ...

   IMPORT AS BIBTEX (2 files):
     refs.bib [bibtex]

   SINGLE JOURNAL ENTRY (5 files):
     analysis.py [code, code_documentation → methodology]
     results.csv [data → observation]
     ...

   LITERATURE ENTRY (5 files):
     smith2023.pdf [pdf → literature]
     ...
```

**Step 2: Bootstrap with adjustments**

After reviewing, ingest with skip/override options:

```
rka_bootstrap_workspace(
    folder_path="~/research/my_project/files",
    phase="phase_1",
    skip_files=["old_draft.md", "scratch.txt"],
    override_tags=["bootstrap"]
)
```

**Step 3: Brain reviews and reorganizes**

```
rka_review_bootstrap(scan_id="scn_01HXY...")
```

Returns a structured review with suggestions:

```
📋 Bootstrap Review — scn_01HXY...
   Entries created: 47
   By type: finding=15, methodology=8, summary=6, observation=5, ...
   Tags: 23 unique, 8 singleton

   🔴 HIGH: Enrich 5 literature entries missing abstracts
      → Have Executor read these PDFs and summarize

   🟡 MEDIUM: Review 8 singleton tags for consolidation
      → Merge similar tags or add them to related entries

   🟡 MEDIUM: Create cross-references between related entries

   🟢 LOW: Create decisions from recurring themes
```

### CLI Usage

```bash
# Preview scan
rka bootstrap scan ~/research/files --no-llm

# Scan with JSON output (for scripting)
rka bootstrap scan ~/research/files --json-output > manifest.json

# Ingest with confirmation
rka bootstrap ingest ~/research/files --phase phase_1 --tags bootstrap

# Dry run (preview without creating)
rka bootstrap ingest ~/research/files --dry-run

# Skip confirmation prompt
rka bootstrap ingest ~/research/files -y
```

### LLM-Enhanced Classification

When `RKA_LLM_ENABLED=true` and the local LLM is available, the scanner uses it for:

1. **Smart content classification** — Classifies files beyond simple regex patterns. The LLM considers context, writing style, and domain-specific cues. Overrides regex when confidence > 0.7.
2. **PDF metadata extraction** — Extracts title, authors, abstract, and year from PDF first-page text when PDF metadata is missing.
3. **Tag suggestions** — Proposes domain-specific tags based on content.

LLM classification falls back gracefully to regex heuristics when the LLM is unavailable.

### Duplicate Detection

Files are identified by SHA-256 hash. Once a file is ingested, re-scanning the same folder will mark it as a duplicate. Duplicates are automatically skipped during ingestion, preventing double-imports when iterating on your workspace.

---

## Web Dashboard Pages

The web dashboard at `http://localhost:9712` provides visual interfaces for all RKA data. Here's what each page offers:

### Dashboard (`/`)
Project overview with active missions, open checkpoints, recent journal entries, and entity counts. This is your starting point for understanding project state at a glance.

### Journal (`/journal`)
Timeline view of all journal entries grouped by date. Filter by entry type (finding, insight, idea, etc.), confidence level, and source. Create and edit entries inline. A "hide superseded" toggle (on by default) keeps the view clean.

### Decisions (`/decisions`)
Interactive decision tree powered by React Flow with elkjs layout. Nodes are color-coded by status (active=green, abandoned=gray dashed, unresolved=orange). Click any node to open a side panel with full details, options, rationale, and related entities.

### Literature (`/literature`)
Table/list view with status column tracking the reading pipeline (to_read → reading → read → cited → excluded). Filter by status tabs. Click to expand detail panels showing abstract, notes, and related decisions.

### Missions (`/missions`)
Active missions with task checklists (parsed from task JSON), checkpoint badges with status indicators, and a report viewer that renders structured mission reports as readable summaries.

### Timeline (`/timeline`)
Event stream visualization grouped by date. Shows all state changes with color-coded event type badges (15+ event types) and actor icons (brain, executor, PI, LLM, web_ui, system). Causal chains are displayed — see which events triggered follow-up events. Filter by entity type and actor.

### Knowledge Graph (`/graph`)
Entity relationship visualization using React Flow. All entity types are displayed as colored nodes:
- **Decisions** (blue) — with parent/child and related literature edges
- **Literature** (indigo) — with related decision edges
- **Journal** (green) — with related decision, literature, mission, and supersession edges
- **Missions** (pink) — with dependency edges

A legend and MiniMap help navigate large graphs.

### Audit Log (`/audit`)
System audit trail displayed as a sortable table. Filter by action type (create, update, delete, resolve), entity type, and actor. Color-coded action badges and a summary bar showing counts per action type help identify activity patterns.

### Context Inspector (`/context`)
Generate context packages by specifying a topic, phase, depth, and max token budget. The split view shows raw entries with temperature badges (HOT/WARM/COLD) on the left and the generated narrative on the right. Token count display and "Copy to Clipboard" for the full context package JSON.

### Settings (`/settings`)
Project configuration display, LLM status (enabled/disabled, model name), database stats (entity counts per type), and health endpoint status.

---

## Tips for Maintaining the Knowledge Base

### Daily Workflow

1. **Start of session**: Brain calls `rka_get_status()` and `rka_get_context(topic="current work")` to orient. Or open the Dashboard (`/`) in the web UI for a visual overview.
2. **During work**: Log findings and insights as you go — small frequent entries are better than rare large ones
3. **End of session**: Executor calls `rka_submit_report()` even for informal progress updates
4. **Weekly**: Brain calls `rka_eviction_sweep(dry_run=true)` to review stale entries. Check the Timeline (`/timeline`) to review the event stream and the Audit Log (`/audit`) for a complete activity trail.
5. **Periodically**: Visit the Knowledge Graph (`/graph`) to visualize how entities connect. Use Mermaid export (`rka_export_mermaid()`) for including decision trees in documents.

### Keep Entries Atomic

Each journal entry should capture one idea, one finding, or one decision. If you find yourself writing a paragraph that covers three different things, split it into three entries. This makes search and cross-referencing work much better.

**Tip**: If you have a large document with multiple sections, use `rka_ingest_document` — it splits markdown by headings automatically, so each section becomes its own atomic entry with proper type classification and tags.

### Use Cross-References

When adding a note that relates to a paper or decision, include the IDs:

```
rka_add_note(
    content="Confirmed that FedProx converges 2x faster than FedAvg on non-IID partition",
    type="finding",
    confidence="tested",
    related_literature=["lit_01FEDPROX..."],
    related_decisions=["dec_01ALGO..."],
    tags=["convergence", "fedprox-vs-fedavg"]
)
```

This makes `rka_get_context()` much more effective — it can trace the full chain from a finding back to the paper that inspired it and the decision it informs. Tags make entries discoverable through the web dashboard's filter controls and improve search relevance.

### Supersede, Don't Delete

When a finding is outdated or corrected, don't delete it. Create a new entry that supersedes it:

```
rka_add_note(
    content="Updated: FedProx converges 1.8x faster (not 2x) after fixing the learning rate bug.",
    type="finding",
    confidence="verified",
    supersedes="jrn_01OLDRESULT..."
)
```

The old entry remains in the knowledge base for audit trail purposes, but is automatically deprioritized in search and context packages.

### Use the Decision Tree for Major Forks

Whenever you face a choice that affects the research direction, record it as a decision — even if you resolve it immediately. Six months later, when writing the paper or answering reviewer questions, having the decision tree with rationale is invaluable.

### Leverage Context Packages for New Sessions

When starting a new Claude session (either Desktop or Code), the first thing to do is:

```
rka_get_context(topic="your current focus area", max_tokens=3000)
```

This gives the fresh Claude session all the relevant context from previous sessions, classified by recency (HOT/WARM/COLD), within the token budget. No more manually pasting previous conversation summaries.
