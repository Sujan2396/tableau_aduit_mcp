"""
Loads a .twb or .twbx file and returns:
  - an lxml root element for the workbook XML
  - metadata about any embedded extracts (.hyper files) found inside a .twbx,
    which we use later for dashboard "weight" scoring.

Tableau's .twb files are plain XML with no namespace, so lxml.etree works
directly with unprefixed tag names (e.g. root.findall(".//worksheet")).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree


@dataclass
class ExtractInfo:
    filename: str
    size_bytes: int


@dataclass
class LoadedWorkbook:
    path: str
    root: etree._Element
    extracts: list[ExtractInfo] = field(default_factory=list)
    is_packaged: bool = False

    @property
    def total_extract_bytes(self) -> int:
        return sum(e.size_bytes for e in self.extracts)


def load_workbook(path: str) -> LoadedWorkbook:
    """
    Load a .twb or .twbx file from disk.

    .twbx is a zip archive containing one .twb plus data/extract files.
    .twb is raw XML.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")

    suffix = p.suffix.lower()

    if suffix == ".twbx":
        return _load_packaged(p)
    elif suffix == ".twb":
        root = etree.parse(str(p)).getroot()
        return LoadedWorkbook(path=str(p), root=root, extracts=[], is_packaged=False)
    else:
        raise ValueError(
            f"Unsupported file type '{suffix}'. Expected .twb or .twbx."
        )


def _load_packaged(p: Path) -> LoadedWorkbook:
    with zipfile.ZipFile(p, "r") as zf:
        twb_names = [n for n in zf.namelist() if n.lower().endswith(".twb")]
        if not twb_names:
            raise ValueError(f"No .twb file found inside {p.name}")

        twb_name = twb_names[0]
        with zf.open(twb_name) as f:
            root = etree.parse(f).getroot()

        extracts = [
            ExtractInfo(filename=n, size_bytes=zf.getinfo(n).file_size)
            for n in zf.namelist()
            if n.lower().endswith(".hyper") or n.lower().endswith(".tde")
        ]

    return LoadedWorkbook(path=str(p), root=root, extracts=extracts, is_packaged=True)
