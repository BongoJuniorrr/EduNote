#!/usr/bin/env python3
"""Copy a former user workspace into the single-user layout without overwriting.

Dry-run by default. The source is retained, and conflicts abort before copying.
Provider/account databases are deliberately not migrated.
"""

import argparse
import hashlib
from pathlib import Path
import shutil


def _digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def migration_plan(source: Path, data_dir: Path, storage_root: Path) -> list[tuple[Path, Path]]:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError("Source must be an existing former user directory")
    mappings = {
        "knowledge_bases": data_dir / "knowledge_bases",
        "settings": data_dir / "user" / "settings",
        "artifacts/edu-studio": data_dir / "user" / "edu-studio",
    }
    plan = []
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"Refusing symlink: {item}")
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        if any(part.startswith(".") for part in relative.parts):
            raise ValueError(f"Refusing hidden file: {relative}")
        target_root = storage_root.resolve()
        target = target_root / relative
        for prefix, destination in mappings.items():
            if relative.is_relative_to(prefix):
                target_root = destination.resolve()
                target = target_root / relative.relative_to(prefix)
                break
        target = target.resolve()
        if not target.is_relative_to(target_root):
            raise ValueError(f"Destination symlink escapes the workspace: {target}")
        if target == item or source in target.parents:
            raise ValueError("Destination must not be inside the source directory")
        if target.exists():
            same = target.is_file() and _digest(item) == _digest(target)
            if not same:
                raise ValueError(f"Conflicting destination (nothing copied): {target}")
            continue
        plan.append((item, target))
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data"
    )
    parser.add_argument("--storage-root", type=Path, help="Defaults to DATA_DIR/user")
    parser.add_argument(
        "--apply", action="store_true", help="Copy after a successful conflict check"
    )
    args = parser.parse_args()
    try:
        plan = migration_plan(
            args.source,
            args.data_dir.resolve(),
            (args.storage_root or args.data_dir / "user").resolve(),
        )
    except ValueError as error:
        parser.error(str(error))
    for source, destination in plan:
        print(f"{source} -> {destination}")
    if args.apply:
        for source, destination in plan:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also prevents a race from overwriting a new file.
            with source.open("rb") as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
    print(f"{'Copied' if args.apply else 'Dry run:'} {len(plan)} files. Source preserved.")


if __name__ == "__main__":
    main()
