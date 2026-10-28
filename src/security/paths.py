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
    root = os.path.realpath(base)
    if not names:
        return Path(root)
    lexical = os.path.abspath(os.path.join(root, *(safe_leaf(name) for name in names)))
    if not lexical.startswith(root + os.sep):
        raise InvalidPathError("Resource path escapes its workspace")
    resolved = os.path.realpath(lexical)
    if not resolved.startswith(root + os.sep):
        raise InvalidPathError("Resource path escapes its workspace")
    return Path(resolved)


def contained_path(base: str | Path, value: str | Path) -> Path:
    root = os.path.realpath(base)
    lexical = os.path.abspath(os.path.join(root, value))
    if lexical == root:
        return Path(root)
    if not lexical.startswith(root + os.sep):
        raise InvalidPathError("Resource path escapes its workspace")
    resolved = os.path.realpath(lexical)
    if resolved == root:
        return Path(root)
    if not resolved.startswith(root + os.sep):
        raise InvalidPathError("Resource path escapes its workspace")
    return Path(resolved)
