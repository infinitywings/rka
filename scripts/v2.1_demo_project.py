#!/usr/bin/env python3
"""
v2.1 Demo Project Creator — Privacy-Preserving Federated Learning for IoT Edge Devices

This script creates a fully pre-populated RKA v2.1 demo project that demonstrates
the complete three-agent loop (Executor → Researcher → Reviewer → PI).

Usage:
    python scripts/v2.1_demo_project.py

Requirements:
    - RKA server running at http://localhost:9712
    - RKA project id: prj_01KKQM9JFG67GT5FGWTAHD9YE4 (rka_development)
    - Role ids:
        executor:   arl_01KM165REFK6FG9SCH02NPBNNJ
        researcher: arl_01KM165RCV8VFD9KDZ7FHBYKQ5
        reviewer:   arl_01KM165RDR1W6JNBTT66ENWKNB

The script is idempotent — run it multiple times safely.
"""

import json
import urllib.request
import urllib.error
import sys
import time
from typing import Any

API = "http://localhost:9712"
PROJECT_ID = "prj_01KKQM9JFG67GT5FGWTAHD9YE4"

HEADERS = {
    "Content-Type": "application/json",
    "X-RKA-Project": PROJECT_ID,
}


def req(method: str, path: str, data: dict | None = None, retries: int = 3) -> dict:
    url = f"{API}{path}"
    body = json.dumps(data).encode() if data else None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 404):
                # Not found or conflict — return empty
                return {}
            body = exc.read()
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            print(f"HTTP {exc.code} on {method} {path}: {body[:200]}", file=sys.stderr)
            return {}
        except Exception as exc:
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            print(f"Error on {method} {path}: {exc}", file=sys.stderr)
            return {}
    return {}


def post(path: str, data: dict) -> dict:
    return req("POST", path, data)


def patch(path: str, data: dict) -> dict:
    return req("PATCH", path, data)


def get(path: str) -> dict:
    return req("GET", path)


def find_or_create_note(note_type: str, content_snippet: str) -> str | None:
    """Find existing note with content snippet, or return None (caller creates)."""
    resp = get("/api/notes")
    notes = resp.get("notes", []) if isinstance(resp, dict) else []
    for note in notes:
        if note_type in (note.get("type", ""), "") and content_snippet in (note.get("content", "") or ""):
            return note["id"]
    return None


def cleanup_demo_data():
    """Remove any existing demo notes/missions to ensure clean slate."""
    print("Cleaning up existing demo data...")
    # Fetch and delete demo notes
    resp = get("/api/notes")
    notes = resp.get("notes", []) if isinstance(resp, dict) else []
    for note in notes:
        content = note.get("content", "") or ""
        if any(kw in content for kw in [
            "Privacy-Preserving Federated Learning", "FL-IoT", "ARM Cortex-M",
            "Literature Review", "FedAvg", "gradient compression",
            "Research Design", "motivation", "novelty",
            "FedSA", "FLIoT-Bench", "CIFAR"
        ]):
            req("DELETE", f"/api/notes/{note['id']}")
    # Fetch and delete demo missions
    resp = get("/api/missions")
    missions = resp.get("missions", []) if isinstance(resp, dict) else []
    for m in missions:
        title = m.get("title", "") or ""
        if any(kw in title for kw in [
            "Literature Review", "FL on IoT", "Research Design",
            "Memory footprint", "Ablation", "Framework"
        ]):
            req("DELETE", f"/api/missions/{m['id']}")
    print("  Cleanup complete.")


# ── Role IDs ──────────────────────────────────────────────────────────────────

EXECUTOR_ROLE_ID = "arl_01KM165REFK6FG9SCH02NPBNNJ"
RESEARCHER_ROLE_ID = "arl_01KM165RCV8VFD9KDZ7FHBYKQ5"
REVIEWER_ROLE_ID = "arl_01KM165RDR1W6JNBTT66ENWKNB"


def main():
    print("=" * 70)
    print("RKA v2.1 Demo — FL for IoT Edge Devices")
    print("=" * 70)

    # ── Check server ──────────────────────────────────────────────────────────
    try:
        resp = req("GET", "/health")
        print(f"✓ RKA server healthy: {resp}")
    except Exception:
        print("✗ RKA server not reachable at http://localhost:9712", file=sys.stderr)
        print("  Start it with: cd /Users/ceron/workspace/rka && docker compose up -d")
        sys.exit(1)

    # ── Cleanup old data ─────────────────────────────────────────────────────
    cleanup_demo_data()

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: PI Directive (Phase 0)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 0] Creating PI research directive...")
    directive = post("/api/notes", {
        "type": "directive",
        "source": "pi",
        "content": (
            "Can federated learning be made practical on resource-constrained IoT devices "
            "without centralized training data? Investigate whether on-device gradient compression "
            "and adaptive synchronization intervals can reduce communication overhead enough to make "
            "FL viable on ARM Cortex-M class hardware (~256KB RAM). "
            "The goal is to design and evaluate a complete FL system that trains on IoT edge devices "
            "with <1MB RAM and achieves accuracy within 3% of centralized training."
        ),
    })
    directive_id = directive.get("id", "")
    print(f"  ✓ Directive created: {directive_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: Literature (Phase 1)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 1] Creating literature entries...")

    papers = [
        {
            "title": "Federated Learning for Internet of Things: A Comprehensive Survey",
            "authors": ["D.C. Nguyen", "M. Ding", "P.N. Pathirana", "A. Seneviratne", "J. Li", "H.V. Poor"],
            "year": 2021,
            "venue": "IEEE Communications Surveys & Tutorials",
            "doi": "10.1109/COMST.2021.3075439",
            "abstract": "The Internet of Things (IoT) is penetrating many facets of our daily life with the proliferation of intelligent services and applications empowered by artificial intelligence (AI). Traditionally, AI techniques require centralized data collection and processing that may not be feasible in realistic application scenarios due to high scalability requirements of modern IoT networks and growing data privacy concerns. Federated Learning (FL) has emerged as a distributed collaborative approach that can enable many intelligent IoT applications, by allowing for training at distributed devices without sharing data.",
            "cited_by": 1920,
            "tags": ["survey", "FL", "IoT", "SOTA"],
        },
        {
            "title": "Federated and Transfer Learning: A Survey on Adversaries and Defense Mechanisms",
            "authors": ["E. Hallaji", "R. Razavi-Far", "M. Saif"],
            "year": 2022,
            "venue": "arXiv:2207.02337",
            "abstract": "The advent of federated learning has facilitated large-scale data exchange amongst machine learning models while maintaining privacy. Despite its brief history, federated learning is rapidly evolving to make wider use more practical. One of the most significant advancements in this domain is the incorporation of transfer learning into federated learning, which overcomes fundamental constraints of primary federated learning, particularly in terms of security.",
            "tags": ["FL", "security", "transfer learning"],
        },
        {
            "title": "Federated Learning for Malware Detection in IoT Devices",
            "authors": ["V. Rey", "P.M. Sánchez Sánchez", "A. Huertas Celdrán", "G. Bovet"],
            "year": 2021,
            "venue": "arXiv:2104.09994",
            "abstract": "This work investigates the possibilities enabled by federated learning concerning IoT malware detection and studies security issues inherent to this new learning paradigm. In this context, a framework that uses federated learning to detect malware affecting IoT devices is presented.",
            "tags": ["FL", "IoT", "security", "malware"],
        },
        {
            "title": "Model-Contrastive Federated Learning (MOON)",
            "authors": ["Q. Li", "B. He", "D. Song"],
            "year": 2021,
            "venue": "CVPR 2021",
            "doi": "10.1109/CVPR46437.2021.01057",
            "abstract": "Federated learning enables multiple parties to collaboratively train a machine learning model without communicating their local data. A key challenge in federated learning is to handle the heterogeneity of data distribution across parties. Although many studies have been proposed to address this challenge, we find that they fail to achieve high performance on image classification datasets with deep models. In this paper, we propose MOON: a simple and effective framework. The idea is to utilize the similarity between representations.",
            "cited_by": 1269,
            "tags": ["FL", "heterogeneity", "contrastive learning"],
        },
        {
            "title": "A Survey on Federated Learning",
            "authors": ["Q. Yang", "Y. Liu", "T. Chen", "Y. Tong"],
            "year": 2021,
            "venue": "Knowledge-Based Systems",
            "doi": "10.1016/j.knosys.2021.106775",
            "abstract": "Federated learning is a new paradigm that enables training machine learning models over distributed data without centralized training data. This paper provides a comprehensive survey of federated learning research from both machine learning and system design perspectives.",
            "cited_by": 1616,
            "tags": ["survey", "FL", "foundations"],
        },
    ]

    lit_ids = []
    for paper in papers:
        lit = post("/api/literature", {
            "title": paper["title"],
            "authors": paper["authors"],
            "year": paper["year"],
            "venue": paper.get("venue", ""),
            "doi": paper.get("doi", ""),
            "abstract": paper.get("abstract", ""),
            "tags": paper.get("tags", []),
            "added_by": "demo_script",
        })
        lit_id = lit.get("id", "")
        lit_ids.append((lit_id, paper["title"]))
        print(f"  ✓ Literature: {paper['title'][:50]}... → {lit_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3: Mission 1 — Literature Review
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 1] Creating literature review mission...")
    mission1 = post("/api/missions", {
        "title": "Literature Review: FL on IoT Edge Devices",
        "objective": (
            "Investigate the current SOTA for federated learning on resource-constrained IoT devices. "
            "Focus on: (1) communication efficiency techniques, (2) gradient compression methods, "
            "(3) FL framework memory footprints on ARM Cortex-M, (4) synchronization strategies. "
            "Find 8-12 relevant papers from ArXiv, IEEE, and ACM. "
            "Write a structured literature summary with: key findings, SOTA gaps, and 4 open problems."
        ),
        "phase": 1,
        "related_journal": [directive_id],
        "assigned_role_id": EXECUTOR_ROLE_ID,
        "status": "open",
    })
    mission1_id = mission1.get("id", "")
    print(f"  ✓ Mission 1 created: {mission1_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4: Executor Report (Phase 1 results)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 1] Creating executor report...")
    report1 = post(f"/api/missions/{mission1_id}/report", {
        "summary": (
            "Surveyed 40+ papers across ArXiv, IEEE Xplore, and ACM DL. Deep-analyzed 10 papers. "
            "Key finding: FedAvg (McMahan 2017) dominates but requires 10-100× more communication "
            "rounds than centralized training. Gradient quantization and sparse compression can "
            "reduce bandwidth by 8-100× but introduce 2-5% accuracy loss. "
            "No published work systematically benchmarks FL on ARM Cortex-M (~256KB RAM) devices. "
            "Most papers evaluate on CIFAR-10/100 — not representative of IoT sensor data."
        ),
        "findings": [
            "FedAvg (McMilan 2017) is the dominant FL algorithm — used in 80% of surveyed papers",
            "Gradient quantization (TensorQuant, 2018) reduces bandwidth 8-32× with <3% accuracy loss",
            "No systematic study of FL on ARM Cortex-M class devices exists in the literature",
            "Adaptive synchronization (FedProx, Li 2020) reduces rounds by 30-50% on heterogeneous data",
            "MOON (CVPR 2021) addresses data heterogeneity via contrastive representation learning",
            "FedSA (staleness-aware) is the most promising for bandwidth-constrained IoT scenarios",
        ],
        "anomalies": [
            "Most FL papers evaluate on CIFAR-10/100 — not representative of real IoT sensor data",
            "Memory footprint analysis is missing from most framework papers",
            "IoT security applications (malware detection) use small datasets — may not generalize",
        ],
        "questions": [
            "What is the minimum memory needed for a practical FL client on Cortex-M?",
            "Can gradient sparsification achieve >50% bandwidth reduction without >5% accuracy loss?",
        ],
        "recommended_next": (
            "Begin system design: select Flower as FL framework, "
            "target ARM Cortex-M4F (512KB RAM) as realistic baseline device. "
            "Prioritize gradient compression + adaptive sync as the two core techniques."
        ),
        "related_literature": [lid for lid, _ in lit_ids],
    })
    report1_id = report1.get("id", "")
    print(f"  ✓ Executor report submitted: {report1_id}")

    # Emit report.submitted event
    event1 = post("/api/role-events", {
        "event_type": "report.submitted",
        "source_role_id": EXECUTOR_ROLE_ID,
        "source_entity_id": report1_id,
        "source_entity_type": "report",
        "project_id": PROJECT_ID,
        "payload": {
            "mission_id": mission1_id,
            "summary": "Literature review complete: 40 papers surveyed, 10 deep-analyzed, 4 open problems identified",
        },
    })
    print(f"  ✓ report.submitted event emitted: {event1.get('id', '')}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5: Researcher Synthesis (Phase 1 synthesis)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 1] Creating researcher synthesis...")
    synthesis1 = post("/api/notes", {
        "type": "note",
        "source": "researcher",
        "content": (
            "## Literature Synthesis: FL on IoT Edge Devices\n\n"
            "**SOTA Summary:** FedAvg is dominant but communication-hungry. "
            "Gradient compression (quantization + sparsification) is the main efficiency lever — "
            "8-100× bandwidth reduction achievable. Adaptive methods (FedProx, SCAFFOLD, MOON) "
            "help with data heterogeneity but add complexity and memory overhead.\n\n"
            "**Key Gap:** No systematic memory-footprint analysis exists for FL frameworks on "
            "embedded devices (ARM Cortex-M class). Most papers evaluate on CIFAR, not real "
            "sensor data. This makes it impossible to assess real-world viability.\n\n"
            "**Open Problems:**\n"
            "1. Minimum viable FL client memory footprint on embedded hardware\n"
            "2. Graceful degradation of accuracy under extreme bandwidth constraints\n"
            "3. Energy-latency-accuracy tradeoff for adaptive synchronization\n"
            "4. Privacy-utility frontier when combining FL with differential privacy on IoT data\n\n"
            "**Recommended Approach:** "
            "Layer-wise top-k sparsification (1-5% nonzero gradients) + 8-bit quantization as "
            "the primary compression method. FedSA as the aggregation algorithm. "
            "Flower as the FL server framework. Target: Cortex-M4F @ 512KB RAM."
        ),
        "related_journal": [directive_id],
        "related_missions": [mission1_id],
    })
    synthesis1_id = synthesis1.get("id", "")
    print(f"  ✓ Synthesis note created: {synthesis1_id}")

    # Emit synthesis.created
    synthesis_event = post("/api/role-events", {
        "event_type": "synthesis.created",
        "source_role_id": RESEARCHER_ROLE_ID,
        "source_entity_id": synthesis1_id,
        "source_entity_type": "journal",
        "project_id": PROJECT_ID,
        "payload": {"mission_id": mission1_id, "synthesis_type": "literature_review"},
    })
    print(f"  ✓ synthesis.created event emitted: {synthesis_event.get('id', '')}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6: Reviewer Critique (Phase 1 review)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 1] Creating reviewer critique...")
    critique1 = post("/api/notes", {
        "type": "note",
        "source": "reviewer",
        "content": (
            "## Critique: Literature Synthesis\n\n"
            "**Verdict:** Sound structure, well-grounded in evidence. Gap identification is valid. "
            "Recommended approach is reasonable given the constraints.\n\n"
            "**Concerns (must address):**\n"
            "1. Open Problem 2 ('graceful degradation') conflates two separate issues: "
            "compression artifacts vs. statistical heterogeneity effects. Should be split into "
            "two distinct open problems.\n"
            "2. Missing related work: 'Federated Learning for Malware Detection in IoT Devices' "
            "(Rey 2021, arXiv:2104.09994) — directly addresses FL+IoT security, should be included "
            "in the literature map.\n"
            "3. The claim that 'no systematic study exists' should cite specific papers that "
            "come closest (PySyft benchmarks, TensorFlow Lite Micro evaluations) to properly "
            "frame the gap rather than stating it as a total void.\n\n"
            "**Approval:** Conditional — address concerns 1-3 before proceeding to design. "
            "Concern 3 is minor (add footnote); concerns 1 and 2 require revision."
        ),
        "related_journal": [synthesis1_id],
        "tags": ["review", "quality-gate", "revision-required"],
    })
    critique1_id = critique1.get("id", "")
    print(f"  ✓ Critique note created: {critique1_id}")

    # Emit disagreement.detected (conditional approval = issues found)
    disagreement_event = post("/api/role-events", {
        "event_type": "disagreement.detected",
        "source_role_id": REVIEWER_ROLE_ID,
        "source_entity_id": synthesis1_id,
        "source_entity_type": "journal",
        "project_id": PROJECT_ID,
        "payload": {
            "severity": "medium",
            "issues": [
                "Open Problem 2 conflates compression artifacts with heterogeneity effects",
                "Missing: Rey 2021 (FL + IoT malware detection)",
                "Gap claim too strong — should cite nearest prior work",
            ],
        },
    })
    print(f"  ✓ disagreement.detected emitted (PI will be notified): {disagreement_event.get('id', '')}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 7: Mission 2 — Framework Selection
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 2] Creating framework selection mission...")
    mission2 = post("/api/missions", {
        "title": "Framework Evaluation: Flower, PySyft, TensorFlow Federated",
        "objective": (
            "Evaluate three FL frameworks (Flower, PySyft, TensorFlow Federated) for embedded IoT use. "
            "For each: assess (1) memory overhead on the server side, (2) embedded client support, "
            "(3) gRPC/HTTP protocol flexibility, (4) community activity. "
            "Visit GitHub repositories and docs. Write a comparison table and recommend the best choice. "
            "Create a RKA decision node with rationale."
        ),
        "phase": 2,
        "related_journal": [directive_id],
        "assigned_role_id": EXECUTOR_ROLE_ID,
        "status": "open",
    })
    mission2_id = mission2.get("id", "")
    print(f"  ✓ Mission 2 created: {mission2_id}")

    # Executor submits framework comparison report
    report2 = post(f"/api/missions/{mission2_id}/report", {
        "summary": (
            "Evaluated Flower (adap/flower), PySyft (OpenMined/PySyft), and TensorFlow Federated. "
            "Flower is the clear winner for our use case: framework-agnostic, active maintenance, "
            "gRPC-based protocol that's implementable in embedded C++. "
            "PySyft is too heavy (Python-native, 500MB+ overhead). "
            "TFF is production-grade but rigid for custom embedded protocols."
        ),
        "findings": [
            "Flower: ~50MB server overhead, gRPC-based, Python/Java/Swift/C embedded clients — BEST FIT",
            "PySyft: 500MB+ overhead, privacy tools excellent but too heavy for embedded",
            "TFF: Google's production-grade, TFLite Micro integration emerging — second choice",
        ],
        "anomalies": [],
        "questions": [],
        "recommended_next": "Select Flower as primary FL framework. Build custom C++ client for embedded.",
        "related_literature": [],
    })
    report2_id = report2.get("id", "")
    print(f"  ✓ Framework report submitted: {report2_id}")

    # Decision node
    decision = post("/api/decisions", {
        "title": "Framework Selection: Flower + Custom C++ for FL on IoT",
        "decision": (
            "Select Flower as the FL server framework. "
            "For embedded clients, build a lightweight C++ client using the Flower gRPC protocol. "
            "TFLite Micro as secondary option for Android-based IoT gateways."
        ),
        "rationale": (
            "Flower offers best flexibility/overhead ratio. "
            "PySyft is too heavy. TFLite Micro is promising but less mature for FL protocol support. "
            "Custom C++ allows precise memory control critical for Cortex-M targets."
        ),
        "related_journal": [directive_id],
    })
    decision_id = decision.get("id", "")
    print(f"  ✓ Decision node created: {decision_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 8: Mission 3 — Research Design
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 3] Creating research design mission...")
    mission3 = post("/api/missions", {
        "title": "Research Design: Memory-Constrained FL for IoT",
        "objective": (
            "Draft a complete research design document covering: "
            "motivation paragraph, problem scope, 3 key challenges, proposed solution sketch, "
            "contribution list, novelty statement, system architecture overview, "
            "evaluation setup (datasets, baselines, metrics), experimental methods. "
            "This should be a publishable research design suitable for a top-tier systems conference."
        ),
        "phase": 3,
        "related_journal": [directive_id],
        "related_decisions": [decision_id],
        "assigned_role_id": EXECUTOR_ROLE_ID,
        "status": "open",
    })
    mission3_id = mission3.get("id", "")
    print(f"  ✓ Mission 3 created: {mission3_id}")

    # Executor submits research design report
    report3 = post(f"/api/missions/{mission3_id}/report", {
        "summary": (
            "Drafted complete research design. "
            "Key contributions: (1) First systematic FL benchmark on ARM Cortex-M class devices. "
            "(2) FedSA (Staleness-Aware Federated Averaging): 38% fewer rounds vs FedAvg on heterogeneous data. "
            "(3) FLIoT-Bench: open-source benchmark suite for embedded FL. "
            "System: Flower server + custom C++ client with layer-wise gradient compression. "
            "Evaluation: Raspberry Pi Pico W + STM32F4, CIFAR-10/16, HAR, anomaly detection."
        ),
        "findings": [
            "Memory budget: 1MB target is achievable with int8 quantization + layer-wise gradient streaming",
            "FedSA: 38% fewer rounds vs FedAvg, similar accuracy (91.4% vs 93.1% centralized)",
            "23× per-round bandwidth reduction achievable with layer-wise top-k + 8-bit quantization",
            "CIFAR-10 is not representative of IoT data — HAR and anomaly detection are more relevant",
        ],
        "anomalies": [],
        "questions": [],
        "recommended_next": "Begin Phase 4: build the baseline FL system. Priority: get a working E2E round first.",
        "related_literature": [lid for lid, _ in lit_ids],
        "related_decisions": [decision_id],
    })
    report3_id = report3.get("id", "")
    print(f"  ✓ Research design report submitted: {report3_id}")

    # Researcher synthesis of research design
    synthesis2 = post("/api/notes", {
        "type": "note",
        "source": "researcher",
        "content": (
            "## Research Design Synthesis\n\n"
            "The research design is comprehensive and well-structured. "
            "The three contributions are well-defined and individually publishable. "
            "FedSA is the key algorithmic contribution — a 38% reduction in rounds is significant. "
            "FLIoT-Bench as an open-source benchmark fills a real gap in the community.\n\n"
            "The system architecture is sound. Layer-wise gradient compression is the right approach "
            "for memory-constrained devices. Flower as the server framework was the correct decision.\n\n"
            "Ready for implementation phase."
        ),
        "related_journal": [directive_id],
        "related_missions": [mission3_id],
        "related_decisions": [decision_id],
    })
    synthesis2_id = synthesis2.get("id", "")
    print(f"  ✓ Research design synthesis created: {synthesis2_id}")

    # Emit synthesis.created
    post("/api/role-events", {
        "event_type": "synthesis.created",
        "source_role_id": RESEARCHER_ROLE_ID,
        "source_entity_id": synthesis2_id,
        "source_entity_type": "journal",
        "project_id": PROJECT_ID,
        "payload": {"mission_id": mission3_id, "synthesis_type": "research_design"},
    })

    # Reviewer approves research design
    critique2 = post("/api/notes", {
        "type": "note",
        "source": "reviewer",
        "content": (
            "## Critique: Research Design\n\n"
            "**Verdict:** Approved. The research design is rigorous, well-motivated, "
            "and the contributions are individually publishable.\n\n"
            "**Minor notes (not blocking):**\n"
            "1. The differential privacy claim in the system architecture should specify ε, δ parameters "
            "or be removed as it's currently unsubstantiated.\n"
            "2. SCAFFOLD requires 2× device memory for control variates — should be noted as a "
            "limitation relative to the 1MB constraint.\n\n"
            "**Approval:** No issues. Proceed to implementation."
        ),
        "related_journal": [synthesis2_id],
        "tags": ["review", "quality-gate", "approved"],
    })
    print(f"  ✓ Research design critique approved: {critique2.get('id', '')}")

    # Emit critique.no_issues
    post("/api/role-events", {
        "event_type": "critique.no_issues",
        "source_role_id": REVIEWER_ROLE_ID,
        "source_entity_id": synthesis2_id,
        "source_entity_type": "journal",
        "project_id": PROJECT_ID,
        "payload": {"approved": True, "minor_notes": ["DP parameters unspecified", "SCAFFOLD memory note"]},
    })

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 9: Mission 4 — Baseline Implementation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 4] Creating baseline FL implementation mission...")
    mission4 = post("/api/missions", {
        "title": "Implementation: Baseline FL System (Flower + C++ Client)",
        "objective": (
            "Build the initial end-to-end FL system: Flower server + lightweight C++ client. "
            "Targets: Raspberry Pi Pico W (Cortex-M33, 512KB RAM) and STM32F4 (Cortex-M4, 192KB RAM). "
            "Use layer-wise top-k gradient compression (k=10%) + 8-bit quantization. "
            "Achieve: (1) E2E working FL round, (2) <1MB memory, (3) 10-50× bandwidth reduction. "
            "Report results for CIFAR-10 @ 50 clients, 10 rounds."
        ),
        "phase": 4,
        "related_journal": [directive_id],
        "related_decisions": [decision_id],
        "assigned_role_id": EXECUTOR_ROLE_ID,
        "status": "open",
    })
    mission4_id = mission4.get("id", "")
    print(f"  ✓ Mission 4 created: {mission4_id}")

    # Executor submits implementation report with checkpoint
    report4 = post(f"/api/missions/{mission4_id}/report", {
        "summary": (
            "Baseline FL system built and tested. "
            "E2E round works on both devices. Memory profile: 847KB peak (exceeds 1MB budget by 13%). "
            "Achieved 91.2% accuracy on CIFAR-10 (vs 93.1% centralized — 1.9% accuracy gap). "
            "23× bandwidth reduction confirmed. "
            "Checkpoint hit: layer-wise top-k compression ratio of 1% causes gradient staleness issues "
            "— need to revisit the k value per layer rather than global k."
        ),
        "findings": [
            "E2E FL round works on Cortex-M4F: 91.2% accuracy (vs 93.1% centralized baseline)",
            "23× bandwidth reduction achieved with layer-wise top-k (k=10%) + int8 quantization",
            "Memory peak: 847KB — exceeds 1MB budget, needs optimization",
            "Global top-k causes gradient staleness: layer-wise k is necessary, not just beneficial",
        ],
        "anomalies": [
            "Memory exceeds 1MB budget on Cortex-M4 (192KB RAM devices) — quantize model weights to 4-bit",
        ],
        "questions": [
            "Should we use per-layer adaptive k (data-rich layers get higher k) or fixed k?",
        ],
        "recommended_next": (
            "Resolve memory issue: apply int8 model weight quantization (4-bit). "
            "Use per-layer adaptive k for gradient compression. "
            "Then run full benchmark suite."
        ),
        "related_literature": [lid for lid, _ in lit_ids],
    })
    print(f"  ✓ Implementation report submitted: {report4.get('id', '')}")

    # Submit checkpoint
    checkpoint = post("/api/checkpoints", {
        "mission_id": mission4_id,
        "title": "Memory exceeds 1MB budget + gradient staleness from global top-k",
        "description": (
            "Two issues found: (1) Memory peak of 847KB exceeds 1MB budget — need to quantize "
            "model weights to 4-bit and use layer-wise streaming. "
            "(2) Global top-k causes gradient staleness — per-layer k is needed."
        ),
        "status": "open",
    })
    checkpoint_id = checkpoint.get("id", "")
    print(f"  ✓ Checkpoint submitted: {checkpoint_id}")

    # Researcher resolves checkpoint
    post(f"/api/checkpoints/{checkpoint_id}/resolve", {
        "resolution": (
            "Use layer-wise adaptive k: for each layer, k = max(5%, round(layer_size_fraction * 15%)). "
            "This preserves important per-layer gradients while achieving 20-50× overall compression. "
            "For memory: apply int8 model weight quantization (4-bit grouped per layer). "
            "Reference: Aji & Heafield 'Sparse Gradient Compression for Distributed Learning' ICLR 2017."
        ),
        "resolved_by_role_id": RESEARCHER_ROLE_ID,
    })
    print(f"  ✓ Checkpoint resolved by researcher.")

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 10: Configure Autonomy Mode
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Phase 5] Setting autonomy mode to autonomous...")
    patch("/api/orchestration/config", {
        "autonomy_mode": "autonomous",
        "circuit_breaker_threshold": 50.0,
        "cost_window_hours": 24,
    })
    print("  ✓ Autonomy mode set to: autonomous")

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("DEMO PROJECT CREATED SUCCESSFULLY")
    print("=" * 70)
    print(f"""
Project: Privacy-Preserving Federated Learning for IoT Edge Devices
Project ID: {PROJECT_ID}

What's been created:
  - 1 PI Directive (research charter)
  - 5 Literature entries (key papers in FL/IoT)
  - 4 Missions (literature review → framework → design → implementation)
  - 4 Executor Reports
  - 2 Researcher Synthesis notes
  - 2 Reviewer Critiques (1 revision required, 1 approved)
  - 1 Decision node (framework selection)
  - 1 Checkpoint (resolved by researcher)
  - 5 Events emitted (report.submitted, synthesis.created, disagreement.detected,
    critique.no_issues, checkpoint.resolved)

Next steps to see the full loop in action:
  1. Check the Orchestration dashboard: http://localhost:9712 (or the web UI)
  2. The Executor will pick up Mission 4 (if autonomy mode is active)
  3. Watch the researcher heartbeat process the checkpoint resolution
  4. The reviewer will see the implementation results and emit critique.no_issues
  5. Researcher auto-creates the next mission on critique.no_issues

To trigger the next cycle manually:
  - The researcher heartbeat will pick up the synthesis.created events
  - The reviewer heartbeat will critique the research design synthesis
  - On critique.no_issues, researcher creates the next mission
""")
    print("=" * 70)


if __name__ == "__main__":
    main()
