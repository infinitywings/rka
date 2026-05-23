#!/usr/bin/env python3
"""start-manuscript.py — bootstrap a Writer manuscript workspace from the
workspace-template shipped inside the rka plugin.

Cross-platform helper invoked by the /rka-start-manuscript slash command
(or directly: python3 plugin/scripts/start-manuscript.py [args]).

Behavior:
 1. Parse argv (--project-id, --venue, --path, --force).
 2. If no args: list supported venues, exit 2 (caller prompts user).
 3. Validate venue against references/venue/<VENUE>.md files in the
    sibling Writer skill bundle.
 4. Resolve target path (default: ./manuscripts/<project-slug>/<venue>/).
 5. Refuse to overwrite a non-empty target dir unless --force.
 6. Copy workspace-template/* into target, preserving hidden files
    (.latexmkrc, .mcp.json, .planning/, .gitkeep markers).
 7. Substitute placeholders in .mcp.json:
      <your-username>           → $USER (or USERNAME on Windows)
      prj_REPLACE_WITH_PROJECT_ID → --project-id value
 8. Probe `rka-writer-tools` binary on PATH; warn (don't fail) if absent.
 9. Output a clear next-step message.

Exit codes:
  0 = success (workspace bootstrapped)
  1 = recoverable error (bad venue, target exists non-empty, etc.)
  2 = no args provided (caller should prompt the user)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path


def plugin_root() -> Path:
    """Locate the plugin root via CLAUDE_PLUGIN_ROOT env, else this script's parent."""
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def writer_skill_dir() -> Path:
    return plugin_root() / "skills" / "writer"


def workspace_template_dir() -> Path:
    return writer_skill_dir() / "workspace-template"


def supported_venues() -> list[str]:
    venue_dir = writer_skill_dir() / "references" / "venue"
    if not venue_dir.is_dir():
        return []
    return sorted(p.stem for p in venue_dir.glob("*.md"))


def current_username() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "your-username"


def slugify_project(project_id: str) -> str:
    """Turn 'prj_01KS5KEPX…' into 'prj-01ks5kepx…' for filesystem use."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", project_id).lower()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap a Writer manuscript workspace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", help="RKA project ID (e.g. prj_01ABC…)")
    parser.add_argument(
        "--venue",
        help="Venue name (must match a references/venue/<VENUE>.md file in the Writer skill bundle).",
    )
    parser.add_argument(
        "--path",
        help="Manuscript workspace directory to create (default: ./manuscripts/<project-slug>/<venue>/).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the target directory.",
    )
    return parser.parse_args(argv)


def fatal(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(msg)


def substitute_mcp_json(src: Path, dst: Path, username: str, project_id: str) -> None:
    """Copy .mcp.json with placeholder substitution. Preserves `_comment` / `_install` keys."""
    text = src.read_text(encoding="utf-8")
    text = text.replace("<your-username>", username)
    text = text.replace("prj_REPLACE_WITH_PROJECT_ID", project_id)
    # Validate JSON survives substitution (defensive — placeholders could land in a value
    # that breaks JSON if the user passed an odd project_id; reject early with a clear msg).
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        fatal(
            f"placeholder substitution produced invalid JSON in .mcp.json: {exc}. "
            f"Check --project-id value for shell-special characters.",
        )
    dst.write_text(text, encoding="utf-8")


def copy_workspace(template: Path, target: Path, username: str, project_id: str) -> None:
    """Copy workspace-template/* into target with placeholder substitution.

    Preserves hidden files (.latexmkrc, .mcp.json, .planning/, .gitkeep markers).
    `.mcp.json` is substituted; everything else is byte-copied.
    """
    target.mkdir(parents=True, exist_ok=True)
    for src in template.rglob("*"):
        rel = src.relative_to(template)
        dst = target / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        # Skip macOS AppleDouble leftover files if any sneak in via copy
        if src.name.startswith("._"):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.name == ".mcp.json":
            substitute_mcp_json(src, dst, username, project_id)
        else:
            shutil.copy2(src, dst)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    venues = supported_venues()
    if not venues:
        fatal(
            f"no venue files found at {writer_skill_dir() / 'references' / 'venue'}. "
            f"Is the Writer skill bundle installed correctly?",
        )

    # No args path: list venues, exit 2 (caller prompts).
    if not args.project_id and not args.venue and not args.path:
        info("/rka-start-manuscript: no arguments provided.")
        info("")
        info("Supported venues:")
        for v in venues:
            info(f"  - {v}")
        info("")
        info("Re-invoke with:")
        info("  /rka-start-manuscript <project_id> <venue> [path]")
        info("Example:")
        info("  /rka-start-manuscript prj_01ABC CHI manuscripts/my-paper/")
        return 2

    if not args.project_id:
        fatal("--project-id required (e.g. --project-id prj_01ABC…)")
    if not args.venue:
        fatal(f"--venue required. Supported: {', '.join(venues)}")
    if args.venue not in venues:
        fatal(
            f"venue '{args.venue}' not recognized. Supported: {', '.join(venues)}",
        )

    # Resolve target path.
    if args.path:
        target = Path(args.path).expanduser().resolve()
    else:
        target = (
            Path.cwd()
            / "manuscripts"
            / slugify_project(args.project_id)
            / args.venue
        ).resolve()

    # Refuse non-empty target unless --force.
    if target.exists() and any(target.iterdir()) and not args.force:
        fatal(
            f"target directory exists and is non-empty: {target}\n"
            f"  Re-run with --force to overwrite, or pick a different --path.",
        )

    template = workspace_template_dir()
    if not template.is_dir():
        fatal(
            f"workspace-template not found at {template}. "
            f"Is the Writer skill bundle installed correctly?",
        )

    username = current_username()
    copy_workspace(template, target, username, args.project_id)

    # Probe rka-writer-tools binary; warn (don't fail) if absent.
    writer_tools = shutil.which("rka-writer-tools")
    binary_note = ""
    if writer_tools is None:
        binary_note = (
            "\n  NOTE: rka-writer-tools binary not on PATH. The .mcp.json registers it,\n"
            "  but you need to install it before `cd && claude`:\n"
            "    UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall '.[writer-tools]'\n"
            "  (run from the rka repo root)"
        )

    info("")
    info(f"manuscript workspace bootstrapped: {target}")
    info("")
    info("Files created:")
    info("  main.tex, refs.bib, ai_tic_config.yaml")
    info("  .latexmkrc, .mcp.json (placeholders substituted)")
    info("  .planning/ (ACTIVE_WORKFLOW.md, OUTLINE.md, PRECIS.md, REVIEW_STATE.md)")
    info("  charts/, figures/, sections/, styles/, tables/ (empty, .gitkeep markers)")
    info("")
    info("Next steps:")
    info(f"  1. Fill SerpAPI key + emails in {target}/.mcp.json `env` block (placeholders visible)")
    info(f"  2. cd {target} && claude")
    info("     (Writer skill auto-activates when you mention manuscript drafting,")
    info("      venue, references, or load .planning/PRECIS.md)")
    if binary_note:
        info(binary_note)

    return 0


def _smoke_test() -> None:
    """Inline smoke test of the substitution logic. Run via: python3 start-manuscript.py --self-test"""
    import tempfile

    sample = (
        '{"mcpServers":{"rka":{"command":"/Users/<your-username>/.local/bin/rka",'
        '"env":{"RKA_PROJECT":"prj_REPLACE_WITH_PROJECT_ID"}}}}'
    )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.json"
        dst = Path(tmp) / "out.json"
        src.write_text(sample)
        substitute_mcp_json(src, dst, "alice", "prj_01TEST")
        result = json.loads(dst.read_text())
        cmd = result["mcpServers"]["rka"]["command"]
        project = result["mcpServers"]["rka"]["env"]["RKA_PROJECT"]
        assert cmd == "/Users/alice/.local/bin/rka", f"bad cmd: {cmd}"
        assert project == "prj_01TEST", f"bad project: {project}"
    print("smoke test OK: <your-username> → alice; prj_REPLACE_WITH_PROJECT_ID → prj_01TEST")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        _smoke_test()
        sys.exit(0)
    sys.exit(main())
