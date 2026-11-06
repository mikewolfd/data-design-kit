"""Explicitly locate a copied evidence tree without changing captured records."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvidenceDirectory:
    root: Path
    captured_root: Path | None = None

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).resolve())
        if self.captured_root is not None:
            captured = Path(self.captured_root)
            if not captured.is_absolute() or ".." in captured.parts:
                raise ValueError("The captured evidence root must be an absolute path without parent traversal.")
            # The original directory need not still exist. Do not resolve it
            # through the new machine's symlinks or consult its old contents.
            object.__setattr__(self, "captured_root", captured)


def evidence_directory(root):
    return root.root if isinstance(root, EvidenceDirectory) else Path(root).resolve()


def evidence_path(root, value):
    """Admit relative or exactly remapped captured paths under one directory."""
    directory = evidence_directory(root)
    path = Path(value)
    if path.is_absolute() and isinstance(root, EvidenceDirectory) and root.captured_root is not None:
        if path.is_relative_to(root.captured_root):
            path = directory / path.relative_to(root.captured_root)
        elif not path.is_relative_to(directory):
            raise ValueError("An absolute evidence reference is outside the captured root.")
    path = (directory / path).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("An evidence reference escapes the admitted directory.")
    return path
