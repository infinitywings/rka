"""Project-scoped embedding backfill.

RKA's BackfillService is store-wide and, for claims, gates on
`claims.embedding_pending` -- a flag that is 0 for every claim in this store
even though 411 of them have no vector, so the service skips them entirely.
This script reuses RKA's own compose_text functions and EmbeddingService
.embed_and_store (which writes the vec row and its metadata row atomically),
but selects pending rows by the same `embedding_metadata` test the other
entity types use, scoped to one project.

Idempotent: embed_and_store internally re-checks needs_reembed.
"""
import asyncio, json, sys

PROJECT = sys.argv[1] if len(sys.argv) > 1 else "project-F"
DRY = "--dry-run" in sys.argv

from rka.config import RKAConfig
from rka.infra.database import Database
from rka.infra.embeddings import EmbeddingService
from rka.services.embedding_backfill import _ENTITY_BACKFILL_CONFIGS

# entity_type -> (table, columns needed by that type's compose_text)
SPEC = {
    "journal":    ("journal",    ["content", "summary"]),
    "decision":   ("decisions",  ["question", "rationale"]),
    "claim":      ("claims",     ["content"]),
    "literature": ("literature", ["title", "abstract"]),
    "mission":    ("missions",   ["objective", "context"]),
}


async def main() -> int:
    config = RKAConfig()
    db = Database(config.database_url)
    await db.connect()
    # Load the sqlite-vec extension only. initialize_phase2_schema() would also
    # re-run migrations (a write); this one-off script must not do that.
    await db._load_sqlite_vec()
    print(f"vec_available = {db.vec_available}")
    if not db.vec_available:
        print("ABORT: sqlite-vec unavailable; would write metadata without vectors")
        return 2

    saved = json.load(open("/data/embedding_config.json"))
    embeddings = EmbeddingService.from_config(saved, db=db)
    print(f"backend={saved['backend']} model={saved['config'].get('model')} dim={embeddings.dim}")
    print(f"project={PROJECT}  dry_run={DRY}\n")

    grand_ok = grand_fail = 0
    for etype, (table, cols) in SPEC.items():
        cfg = _ENTITY_BACKFILL_CONFIGS[etype]
        select = ", ".join(["id"] + cols)
        rows = await db.fetchall(
            f"SELECT {select} FROM {table} t"
            f" WHERE t.project_id = ?"
            f"   AND NOT EXISTS (SELECT 1 FROM embedding_metadata m"
            f"                   WHERE m.entity_type = ? AND m.entity_id = t.id)"
            f" ORDER BY t.id",
            (PROJECT, etype),
        )
        if not rows:
            print(f"{etype:11} pending=0")
            continue
        print(f"{etype:11} pending={len(rows)}", flush=True)
        if DRY:
            sample = cfg.compose_text(dict(rows[0]))[:90]
            print(f"            e.g. {rows[0]['id']} -> {sample!r}")
            grand_ok += len(rows)
            continue
        ok = fail = 0
        for i, row in enumerate(rows, 1):
            rec = dict(row)
            text = cfg.compose_text(rec)
            if not text.strip():
                continue
            try:
                await embeddings.embed_and_store(etype, rec["id"], text, project_id=PROJECT)
                ok += 1
            except Exception as exc:
                fail += 1
                if fail <= 3:
                    print(f"            FAIL {rec['id']}: {type(exc).__name__}: {exc}")
            if i % 25 == 0:
                print(f"            {i}/{len(rows)} ok={ok} fail={fail}", flush=True)
        print(f"            done ok={ok} fail={fail}")
        grand_ok += ok; grand_fail += fail

    await db.close()
    print(f"\nTOTAL embedded={grand_ok} failed={grand_fail}")
    return 0


raise SystemExit(asyncio.run(main()))
