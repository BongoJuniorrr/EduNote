"""Contain workspace resources without silently rewriting their identifiers."""
import os
from pathlib import Path


class InvalidPathError(ValueError):
    pass


def safe_leaf(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in {".", ".."} or len(value.encode("utf-8")) > 255:
        raise InvalidPathError("Invalid resource identifier")
    if any(char in value for char in ("/", "\\", "\x00")) or any(ord(char) < 32 for char in value):
        raise InvalidPathError("Invalid resource identifier")
    return os.path.basename(value)


def safe_child(base: str | Path, *names: str) -> Path:
    root = Path(base).resolve()
    candidate = root.joinpath(*(safe_leaf(name) for name in names)).resolve()
    if not candidate.is_relative_to(root):
        raise InvalidPathError("Resource path escapes its workspace")
    return candidate


def contained_path(base: str | Path, value: str | Path) -> Path:
    root = Path(base).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and not str(resolved).startswith(str(root) + os.sep):
        raise InvalidPathError("Resource path escapes its workspace")
    return resolved
