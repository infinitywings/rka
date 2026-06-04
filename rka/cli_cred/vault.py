"""RKA cred vault — file layout, dotenv parser, atomic-write helpers.

Phase 1 file layout (all OUTSIDE any git repo, on user's host):

    $XDG_CONFIG_HOME/rka/                 (dir mode 0700)
    ├── creds.env                         (mode 0600, KEY=VALUE lines)
    ├── manifest.toml                     (declarative cred requirements)
    ├── versions.toml                     (expected binary + container versions)
    └── projects/                         (Phase 2; empty in Phase 1)

The dotenv parser is order-preserving + comment-preserving so the PI
can hand-edit creds.env without `rka cred set/unset` clobbering their
layout on the next mutation.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


# ----------------------------------------------------------------------
# File-layout discovery
# ----------------------------------------------------------------------


def vault_root(env: dict[str, str] | None = None) -> Path:
    """Resolve the vault root: $XDG_CONFIG_HOME/rka, falling back to ~/.config/rka.

    Pass ``env`` to override the OS environment (used by tests).
    """
    e = env if env is not None else os.environ
    xdg = e.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser() / "rka"
    # ~/.config/rka — works on macOS + Linux + WSL.
    home = e.get("HOME", "") or str(Path.home())
    return Path(home) / ".config" / "rka"


def creds_path(env: dict[str, str] | None = None) -> Path:
    return vault_root(env) / "creds.env"


def manifest_path(env: dict[str, str] | None = None) -> Path:
    return vault_root(env) / "manifest.toml"


def versions_path(env: dict[str, str] | None = None) -> Path:
    return vault_root(env) / "versions.toml"


def projects_dir(env: dict[str, str] | None = None) -> Path:
    return vault_root(env) / "projects"


def ensure_vault_dir(env: dict[str, str] | None = None) -> Path:
    """Create vault root + projects/ with mode 0700; idempotent."""
    root = vault_root(env)
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass  # filesystem might not support chmod (e.g. some bind-mounts)
    pd = projects_dir(env)
    pd.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(pd, 0o700)
    except OSError:
        pass
    return root


# ----------------------------------------------------------------------
# Dotenv parser (order-preserving, comment-preserving)
# ----------------------------------------------------------------------


@dataclass
class DotenvLine:
    """One line of a .env file. Either a comment/blank or a KEY=VALUE entry."""

    kind: str  # 'kv' | 'comment' | 'blank'
    key: str = ""
    value: str = ""
    raw: str = ""  # full original text including any inline comment


@dataclass
class Dotenv:
    """Parsed .env file. Preserves the original line order + comments
    so subsequent `set`/`unset` operations don't reshuffle the PI's layout.
    """

    lines: list[DotenvLine] = field(default_factory=list)

    def get(self, key: str) -> str | None:
        for line in self.lines:
            if line.kind == "kv" and line.key == key:
                return line.value
        return None

    def keys(self) -> list[str]:
        return [line.key for line in self.lines if line.kind == "kv"]

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self.lines:
            if line.kind == "kv":
                out[line.key] = line.value
        return out

    def set(self, key: str, value: str) -> None:
        """Idempotently set KEY=VALUE. If KEY exists, replace in place;
        otherwise append a new line at the end.
        """
        for line in self.lines:
            if line.kind == "kv" and line.key == key:
                line.value = value
                line.raw = _format_kv(key, value)
                return
        self.lines.append(DotenvLine(kind="kv", key=key, value=value, raw=_format_kv(key, value)))

    def unset(self, key: str) -> bool:
        """Remove KEY. Returns True if a line was removed, False otherwise."""
        for i, line in enumerate(self.lines):
            if line.kind == "kv" and line.key == key:
                del self.lines[i]
                return True
        return False

    def render(self) -> str:
        out_lines: list[str] = []
        for line in self.lines:
            if line.kind == "kv":
                # Re-format from canonical key/value (in case raw is stale
                # after a set).
                out_lines.append(_format_kv(line.key, line.value))
            else:
                out_lines.append(line.raw)
        # Trailing newline so the file is POSIX-compliant.
        if out_lines and not out_lines[-1].endswith("\n"):
            return "\n".join(out_lines) + "\n"
        return "\n".join(out_lines)


def _format_kv(key: str, value: str) -> str:
    """Format a KEY=VALUE line. Quote value only when needed (contains
    whitespace, '#', or starts with a quote).
    """
    needs_quote = (
        any(c in value for c in (" ", "\t", "#", "\n"))
        or value.startswith(('"', "'"))
        or value == ""
    )
    if needs_quote:
        # Use double quotes; escape inner double-quotes + backslashes.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{escaped}"'
    return f"{key}={value}"


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        inner = s[1:-1]
        if s[0] == '"':
            # Un-escape backslash-escapes.
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return s


def parse_dotenv(text: str) -> Dotenv:
    """Parse a .env body. Preserves comments + blank lines + order."""
    dot = Dotenv()
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            dot.lines.append(DotenvLine(kind="blank", raw=line))
            continue
        if stripped.startswith("#"):
            dot.lines.append(DotenvLine(kind="comment", raw=line))
            continue
        if "=" not in stripped:
            # Malformed: keep verbatim as a "comment" so a round-trip
            # doesn't destroy data.
            dot.lines.append(DotenvLine(kind="comment", raw=line))
            continue
        # Strip optional `export ` prefix (POSIX shell style).
        body = stripped
        if body.startswith("export "):
            body = body[len("export ") :].lstrip()
        key, _, value = body.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip trailing inline comment only when value isn't quoted.
        if not (value.startswith('"') or value.startswith("'")):
            hash_idx = value.find("#")
            if hash_idx >= 0:
                value = value[:hash_idx].rstrip()
        value = _strip_quotes(value)
        dot.lines.append(DotenvLine(kind="kv", key=key, value=value, raw=line))
    return dot


def load_dotenv(path: Path) -> Dotenv:
    """Read + parse a .env file. Returns empty Dotenv if file missing."""
    if not path.exists():
        return Dotenv()
    return parse_dotenv(path.read_text())


# ----------------------------------------------------------------------
# Atomic write (mode 0600, tmp + rename)
# ----------------------------------------------------------------------


def atomic_write_text(path: Path, body: str, mode: int = 0o600) -> None:
    """Atomic write of ``body`` to ``path`` with the given file mode.

    Strategy: write to a tmp file in the SAME directory (so os.replace
    is atomic on POSIX); chmod the tmp file; os.replace into final.
    Cleans up the tmp file on any OSError.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(body)
        try:
            os.chmod(tmp_path, mode)
        except OSError:
            pass
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def save_dotenv(path: Path, dot: Dotenv) -> None:
    atomic_write_text(path, dot.render(), mode=0o600)


# ----------------------------------------------------------------------
# Convenience: high-level read/write
# ----------------------------------------------------------------------


def load_creds(env: dict[str, str] | None = None) -> Dotenv:
    return load_dotenv(creds_path(env))


def save_creds(dot: Dotenv, env: dict[str, str] | None = None) -> None:
    ensure_vault_dir(env)
    save_dotenv(creds_path(env), dot)


def file_mode(path: Path) -> int:
    """Return the octal file-mode bits (e.g. 0o600). Returns 0 if path missing."""
    if not path.exists():
        return 0
    return path.stat().st_mode & 0o777
