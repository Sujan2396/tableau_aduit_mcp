"""
Flags likely-duplicate worksheets using a weighted similarity score built from:
  - Jaccard similarity of the field-usage set (rows/cols/filters/marks/encodings)
  - whether the mark type matches (bar vs line vs ...)
  - whether the filter sets overlap

Score is 0.0-1.0. Anything above the threshold (default 0.85) is flagged as a
likely duplicate pair worth consolidating.
Random Commment
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .graph import WorkbookGraph, WorksheetNode


@dataclass
class DuplicatePair:
    sheet_a: str
    sheet_b: str
    similarity: float
    shared_fields: list[str]
    mark_match: bool


def _field_set(ws: WorksheetNode, graph: WorkbookGraph) -> set[str]:
    """Build a normalized set of field *captions* (display names) used by this
    worksheet. used_fields stores internal graph keys ('Datasource::[Name]'),
    while rows/cols/filters store raw bracketed tokens - we resolve everything
    to a caption so the resulting set is clean and comparable."""
    fields: set[str] = set()

    for key in ws.used_fields:
        f = graph.fields.get(key)
        fields.add(f.caption if f else key)

    for raw in (*ws.rows_shelf, *ws.cols_shelf, *ws.filters):
        internal = raw if raw.startswith("[") else f"[{raw}]"
        key = graph._find_field_key_by_internal_name(internal)
        f = graph.fields.get(key) if key else None
        fields.add(f.caption if f else raw)

    for extra in (ws.color_field, ws.size_field, ws.label_field):
        if not extra:
            continue
        internal = extra if extra.startswith("[") else f"[{extra}]"
        key = graph._find_field_key_by_internal_name(internal)
        f = graph.fields.get(key) if key else None
        fields.add(f.caption if f else extra)

    return fields


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def find_duplicate_worksheets(
    graph: WorkbookGraph, threshold: float = 0.85
) -> list[DuplicatePair]:
    names = list(graph.worksheets.keys())
    pairs: list[DuplicatePair] = []

    for name_a, name_b in combinations(names, 2):
        ws_a = graph.worksheets[name_a]
        ws_b = graph.worksheets[name_b]

        fields_a = _field_set(ws_a, graph)
        fields_b = _field_set(ws_b, graph)

        field_similarity = _jaccard(fields_a, fields_b)
        mark_match = (ws_a.mark_type is not None) and (ws_a.mark_type == ws_b.mark_type)
        filter_similarity = _jaccard(set(ws_a.filters), set(ws_b.filters))

        # Weighted blend: field usage matters most, mark type is a smaller
        # signal, filter overlap reinforces the field-usage signal.
        combined = (0.7 * field_similarity) + (0.15 * (1.0 if mark_match else 0.0)) + (
            0.15 * filter_similarity
        )

        if combined >= threshold:
            pairs.append(
                DuplicatePair(
                    sheet_a=name_a,
                    sheet_b=name_b,
                    similarity=round(combined, 3),
                    shared_fields=sorted(fields_a & fields_b),
                    mark_match=mark_match,
                )
            )

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs
