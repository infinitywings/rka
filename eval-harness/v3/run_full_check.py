#!/usr/bin/env python3
"""Eval-v3 全面体检 —— 一条命令跑完所有验收指标。

覆盖五个层面，每项都有明确阈值，输出 PASS/WARN/FAIL：

  A 系统健康   API、embedding 后端、skill 打包一致性
  B 索引完整性  向量覆盖率、metadata/vector 错配
  C 检索能力    决策自检索（scoped vs unscoped）、分类型自检索
  D 图层        pivot 一致性、back-trace recall（回归，确保没退化）
  E 图完整性    悬空边、supersede 链、孤儿决策

用法:
    python eval-harness/v3/run_full_check.py --db <snapshot.db> [--quick]

--quick 用较小样本（每项 60），完整跑用默认（决策全量）。
"""
from __future__ import annotations

import argparse, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS: list[tuple[str, str, str, str]] = []   # (层, 指标, 结果, 判定)


def rec(layer: str, metric: str, value: str, verdict: str) -> None:
    RESULTS.append((layer, metric, value, verdict))
    mark = {"PASS": "✓", "WARN": "!", "FAIL": "✗", "INFO": "·"}[verdict]
    print(f"  {mark} {metric:<44} {value}")


def sh(cmd: list[str], timeout: int = 1800) -> str:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return "<timeout>"


def docker_py(script: str, timeout: int = 300) -> str:
    tmp = Path("/tmp/_rka_check.py"); tmp.write_text(script)
    subprocess.run(["docker", "cp", str(tmp), "rka-server:/tmp/_rka_check.py"],
                   capture_output=True)
    p = subprocess.run(["docker", "exec", "rka-server", "python", "/tmp/_rka_check.py"],
                       capture_output=True, text=True, timeout=timeout)
    return p.stdout


def num(text: str, marker: str, cast=float):
    """抓取 'marker=<value>' 或 marker 后第一个数字。"""
    import re
    m = re.search(re.escape(marker) + r"[=:\s]*([0-9.]+)", text)
    return cast(m.group(1)) if m else None


def main(a) -> int:
    t0 = time.time()
    print("=" * 74); print("Eval-v3 全面体检"); print("=" * 74)

    # ---------------------------------------------------------------- A 系统健康
    print("\n[A] 系统健康")
    out = sh(["curl", "-s", "-m", "15", "http://localhost:9712/api/health"])
    ok = '"status":"ok"' in out
    rec("A", "REST API /api/health", out.strip()[:60] or "<无响应>", "PASS" if ok else "FAIL")

    emb = sh(["curl", "-s", "-m", "60", "-o", "/dev/null", "-w", "%{http_code} %{time_total}s",
              "-X", "POST", "http://localhost:1234/v1/embeddings", "-H", "Content-Type: application/json",
              "-d", '{"model":"text-embedding-qwen3-embedding-4b","input":"health"}'])
    rec("A", "embedding 后端可达", emb.strip(), "PASS" if emb.startswith("200") else "FAIL")

    out = sh([sys.executable, "-m", "pytest", "tests/test_skills_packaging.py",
              "eval-harness/v3/tests/", "-q"], timeout=600)
    passed = "failed" not in out and " passed" in out
    line = [l for l in out.splitlines() if "passed" in l or "failed" in l]
    rec("A", "测试套件 (skills parity + eval harness)",
        line[-1].strip() if line else "?", "PASS" if passed else "FAIL")

    # ------------------------------------------------------------ B 索引完整性
    print("\n[B] 索引完整性")
    cov = docker_py('''
import sqlite3
c=sqlite3.connect('file:/data/rka.db?mode=ro',uri=True)
T=[('journal','vec_journal_rowids'),('decisions','vec_decisions_rowids'),('claims','vec_claims_rowids'),
   ('literature','vec_literature_rowids'),('missions','vec_missions_rowids')]
gt=ge=0; worst=[]
for tbl,vec in T:
    t=c.execute('SELECT COUNT(*) FROM %s'%tbl).fetchone()[0]
    e=c.execute('SELECT COUNT(*) FROM %s x WHERE EXISTS(SELECT 1 FROM %s v WHERE v.id=x.id)'%(tbl,vec)).fetchone()[0]
    gt+=t; ge+=e
print("TOTALCOV=%.2f MISSING=%d" % (100*ge/gt, gt-ge))
# 每项目最低覆盖
rows=[]
for pid,name in c.execute("SELECT id,name FROM projects"):
    tt=ee=0
    for tbl,vec in T:
        tt+=c.execute('SELECT COUNT(*) FROM %s WHERE project_id=?'%tbl,(pid,)).fetchone()[0]
        ee+=c.execute('SELECT COUNT(*) FROM %s x WHERE x.project_id=? AND EXISTS(SELECT 1 FROM %s v WHERE v.id=x.id)'%(tbl,vec),(pid,)).fetchone()[0]
    if tt: rows.append((100*ee/tt,name,tt))
rows.sort()
print("WORST=%.2f WORSTNAME=%s" % (rows[0][0], rows[0][1]))
# metadata 与 vector 错配
mm=c.execute("""SELECT COUNT(*) FROM embedding_metadata m WHERE m.entity_type='claim'
   AND NOT EXISTS(SELECT 1 FROM vec_claims_rowids v WHERE v.id=m.entity_id)""").fetchone()[0]
print("ORPHANMETA=%d" % mm)
''')
    tot = num(cov, "TOTALCOV"); miss = num(cov, "MISSING", int)
    worst = num(cov, "WORST"); orphan = num(cov, "ORPHANMETA", int)
    wname = cov.split("WORSTNAME=")[1].split()[0] if "WORSTNAME=" in cov else "?"
    rec("B", "全库向量覆盖率 (目标 ≥99%)", f"{tot}% (缺 {miss})",
        "PASS" if tot and tot >= 99 else "WARN" if tot and tot >= 90 else "FAIL")
    rec("B", "最低项目覆盖率", f"{worst}% ({wname})",
        "PASS" if worst and worst >= 99 else "WARN" if worst and worst >= 90 else "FAIL")
    rec("B", "有 metadata 无向量的 claim (应为 0)", str(orphan),
        "PASS" if orphan == 0 else "FAIL")

    # ------------------------------------------------------------ C 检索能力
    print("\n[C] 检索能力")
    n = "60" if a.quick else "150"
    base = [sys.executable, "eval-harness/v3/currency/self_retrieval.py", "--db", a.db, "--sample", n]
    out = sh(base, timeout=2400)
    un = num(out, "hit=") ; un_rate = None
    for l in out.splitlines():
        if l.strip().startswith("全部"):
            un_rate = float(l.split("(")[1].split("%")[0])
    rec("C", "决策自检索 · 不过滤 (基线)", f"{un_rate}%", "INFO")

    out = sh(base + ["--types", "decision", "--truncate-words", "8"], timeout=2400)
    sc_rate = None
    for l in out.splitlines():
        if l.strip().startswith("全部"):
            sc_rate = float(l.split("(")[1].split("%")[0])
    rec("C", "决策自检索 · 类型过滤+8词 (目标 ≥90%)", f"{sc_rate}%",
        "PASS" if sc_rate and sc_rate >= 90 else "WARN" if sc_rate and sc_rate >= 75 else "FAIL")
    if un_rate and sc_rate:
        rec("C", "类型过滤带来的提升", f"+{sc_rate - un_rate:.1f} 个百分点", "INFO")

    for ent in ["claim", "journal", "literature", "mission"]:
        out = sh(base + ["--entity", ent, "--types", ent, "--truncate-words", "8"], timeout=2400)
        r = None
        for l in out.splitlines():
            if l.strip().startswith("全部"):
                r = float(l.split("(")[1].split("%")[0])
        rec("C", f"{ent} 自检索 · 类型过滤", f"{r}%",
            "PASS" if r and r >= 80 else "WARN" if r and r >= 60 else "FAIL")

    # ------------------------------------------------------------ D 图层回归
    print("\n[D] 图层（回归）")
    for tag, corpus, proj in [
        ("CAREER", "scenarios.CAREER.jsonl", "prj_01KWFRG2TZGHV1A8G4MXVDFPJ5"),
        ("rka_development", "scenarios.rka_development.jsonl", "prj_01KKQM9JFG67GT5FGWTAHD9YE4"),
    ]:
        outdir = f"eval-harness/v3/tracing/results/{tag}-check"
        sh([sys.executable, "eval-harness/v3/tracing/runner.py", "--corpus",
            f"eval-harness/v3/tracing/{corpus}", "--rka-url", "http://localhost:9712",
            "--project", proj, "--out-dir", outdir], timeout=900)
        f = ROOT / outdir / "metrics.json"
        if f.is_file():
            m = json.loads(f.read_text())["aggregate"]
            rec("D", f"{tag} · trace_recall (critical)", str(m["trace_recall_mean"]),
                "PASS" if m["trace_recall_mean"] >= 0.99 else "FAIL")
            rec("D", f"{tag} · pivot 正确率", f"{m['pivot_correct']}/{m['pivot_scenarios']}",
                "PASS" if m["pivot_correct"] == m["pivot_scenarios"] else "FAIL")
            rec("D", f"{tag} · 只返回旧决策 (应为 0)", str(m["stale_surfacing"]),
                "PASS" if m["stale_surfacing"] == 0 else "FAIL")
            rec("D", f"{tag} · anchor_mrr", str(m["anchor_mrr"]), "INFO")
        else:
            rec("D", f"{tag} · tracing", "<未产出>", "FAIL")

        out = sh([sys.executable, "eval-harness/v3/currency/runner.py", "--db", a.db,
                  "--project", proj, "--out",
                  f"eval-harness/v3/currency/results/{tag}-check.json"], timeout=900)
        blind = num(out, "BLIND STALE EXPOSURE:")
        cf = num(out, "current_first_rate:")
        sig = "True" in out.split("any status signal:")[1][:12] if "any status signal:" in out else None
        if blind is not None:
            rec("D", f"{tag} · blind_stale_exposure (目标 0)", str(blind),
                "PASS" if blind == 0 else "WARN")
            rec("D", f"{tag} · current_first_rate", str(cf), "INFO")
            rec("D", f"{tag} · search 暴露 status (目标 True)", str(sig),
                "PASS" if sig else "FAIL")

    # ------------------------------------------------------------ E 图完整性
    print("\n[E] 图完整性")
    g = docker_py('''
import sqlite3
c=sqlite3.connect('file:/data/rka.db?mode=ro',uri=True)
idproj={}
for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    try: cols={r[1] for r in c.execute('PRAGMA table_info("%s")'%t)}
    except sqlite3.OperationalError: continue
    if 'id' in cols and 'project_id' in cols:
        try:
            for r in c.execute('SELECT id,project_id FROM "%s"'%t):
                if r[0] is not None: idproj[r[0]]=r[1]
        except sqlite3.OperationalError: pass
tot=dang=cross=0
for s,t in c.execute("SELECT source_id,target_id FROM entity_links"):
    tot+=1; a=idproj.get(s); b=idproj.get(t)
    if a is None or b is None: dang+=1
    elif a!=b: cross+=1
print("EDGES=%d DANGLING=%d CROSS=%d" % (tot,dang,cross))
print("BROKENCHAIN=%d" % c.execute("SELECT COUNT(*) FROM decisions d WHERE d.superseded_by IS NOT NULL AND NOT EXISTS(SELECT 1 FROM decisions n WHERE n.id=d.superseded_by)").fetchone()[0])
print("ORPHANSUP=%d" % c.execute("SELECT COUNT(*) FROM decisions WHERE status='superseded' AND superseded_by IS NULL").fetchone()[0])
''')
    rec("E", "悬空 entity_links 端点", str(num(g, "DANGLING", int)),
        "PASS" if num(g, "DANGLING", int) == 0 else "WARN")
    rec("E", "跨项目边", str(num(g, "CROSS", int)), "INFO")
    rec("E", "断裂的 supersede 链 (应为 0)", str(num(g, "BROKENCHAIN", int)),
        "PASS" if num(g, "BROKENCHAIN", int) == 0 else "FAIL")
    rec("E", "作废但无继任指针的决策", str(num(g, "ORPHANSUP", int)),
        "PASS" if num(g, "ORPHANSUP", int) == 0 else "WARN")

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 74)
    tally = {v: sum(1 for r in RESULTS if r[3] == v) for v in ("PASS", "WARN", "FAIL", "INFO")}
    print(f"汇总: PASS {tally['PASS']} | WARN {tally['WARN']} | FAIL {tally['FAIL']} "
          f"| INFO {tally['INFO']}   用时 {time.time()-t0:.0f}s")
    if tally["FAIL"]:
        print("\n未通过项:")
        for l, m, v, verd in RESULTS:
            if verd == "FAIL": print(f"  ✗ [{l}] {m}: {v}")
    if tally["WARN"]:
        print("\n需关注项:")
        for l, m, v, verd in RESULTS:
            if verd == "WARN": print(f"  ! [{l}] {m}: {v}")
    if a.out:
        Path(a.out).write_text(json.dumps(
            [{"layer": l, "metric": m, "value": v, "verdict": d} for l, m, v, d in RESULTS],
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n结果已写入 {a.out}")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="只读快照，用于自检索与 currency 语料")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="eval-harness/v3/results-full-check.json")
    raise SystemExit(main(ap.parse_args()))
