"""Local manifest: what was pulled, where it lives, and what changed since.

This is what lets push send only the edited objects without requiring git, and
what maps an SE80-style local path back to the canonical abapGit path SAP expects.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_DIR = ".abap"
MANIFEST_FILE = "manifest.json"
SNAPSHOT_DIR = "snapshots"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Entry:
    canonical: str
    sha256: str
    obj_type: str
    obj_name: str


@dataclass
class Manifest:
    root: Path
    package: str = ""
    system: str = ""
    pulled_at: str = ""
    include_subpackages: bool = True
    se80: bool = False
    files: dict[str, Entry] = field(default_factory=dict)

    # ------------------------------------------------------------------ storage

    @property
    def path(self) -> Path:
        return self.root / MANIFEST_DIR / MANIFEST_FILE

    @classmethod
    def load(cls, root: Path) -> Manifest:
        target = root / MANIFEST_DIR / MANIFEST_FILE
        if not target.is_file():
            return cls(root=root)
        raw = json.loads(target.read_text())
        return cls(
            root=root,
            package=raw.get("package", ""),
            system=raw.get("system", ""),
            pulled_at=raw.get("pulled_at", ""),
            include_subpackages=raw.get("include_subpackages", True),
            se80=raw.get("se80", False),
            files={
                local: Entry(
                    canonical=meta["canonical"],
                    sha256=meta["sha256"],
                    obj_type=meta.get("obj_type", ""),
                    obj_name=meta.get("obj_name", ""),
                )
                for local, meta in raw.get("files", {}).items()
            },
        )

    def save(self) -> None:
        self.pulled_at = self.pulled_at or time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "package": self.package,
                    "system": self.system,
                    "pulled_at": self.pulled_at,
                    "include_subpackages": self.include_subpackages,
                    "se80": self.se80,
                    "files": {
                        local: {
                            "canonical": entry.canonical,
                            "sha256": entry.sha256,
                            "obj_type": entry.obj_type,
                            "obj_name": entry.obj_name,
                        }
                        for local, entry in sorted(self.files.items())
                    },
                },
                indent=2,
            )
            + "\n"
        )

    @property
    def exists(self) -> bool:
        return bool(self.files)

    # ------------------------------------------------------------------ diffing

    def scan(self) -> tuple[list[str], list[str]]:
        """Return (modified, deleted) local paths relative to the manifest baseline."""
        modified, deleted = [], []
        for local, entry in sorted(self.files.items()):
            target = self.root / local
            if not target.is_file():
                deleted.append(local)
            elif sha256(target.read_bytes()) != entry.sha256:
                modified.append(local)
        return modified, deleted

    def objects_for(self, locals_: list[str]) -> set[tuple[str, str]]:
        return {
            (self.files[local].obj_type, self.files[local].obj_name)
            for local in locals_
            if local in self.files and self.files[local].obj_name
        }

    def files_of_objects(self, objects: set[tuple[str, str]]) -> list[str]:
        """Every file belonging to the given objects.

        abapGit deserializes an object from its complete file set, so a changed
        .abap must travel together with its .xml metadata.
        """
        return sorted(
            local
            for local, entry in self.files.items()
            if (entry.obj_type, entry.obj_name) in objects
        )

    def snapshot_path(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = self.root / MANIFEST_DIR / SNAPSHOT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self.package}-{stamp}.zip"
