"""
Automated tests for the tableau_audit library, run against the synthetic
tests/sample.twb workbook. This file documents the *expected* findings for
that workbook, so any regression in parsing/analysis logic gets caught.

Run with:
    pytest tests/test_audit.py -v
"""

import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tableau_audit import (
    load_workbook,
    WorkbookGraph,
    find_unused_assets,
    analyze_dashboards,
    find_duplicate_worksheets,
    render_markdown_report,
)

SAMPLE_TWB = os.path.join(os.path.dirname(__file__), "sample.twb")


@pytest.fixture
def graph():
    loaded = load_workbook(SAMPLE_TWB)
    return WorkbookGraph(loaded.root)


def test_load_workbook_parses_correct_counts(graph):
    assert len(graph.worksheets) == 4
    assert len(graph.dashboards) == 1


def test_unused_worksheets_detected(graph):
    unused = find_unused_assets(graph)
    assert set(unused.unused_worksheets) == {"Sales by Region (Copy)", "Orphaned Sheet"}
    # The sheets actually embedded on the dashboard must NOT be flagged
    assert "Sales by Region" not in unused.unused_worksheets
    assert "Profit Ratio by Category" not in unused.unused_worksheets


def test_unused_calculation_detected(graph):
    unused = find_unused_assets(graph)
    assert unused.unused_calculations == ["Unused Calc"]
    # Profit Ratio IS used (by "Profit Ratio by Category" sheet) so must not appear
    assert "Profit Ratio" not in unused.unused_calculations


def test_unused_parameter_detected(graph):
    unused = find_unused_assets(graph)
    assert unused.unused_parameters == ["Unused Param"]
    # Parameter 1 / "Top N" IS referenced by the dashboard's param control
    assert "Top N" not in unused.unused_parameters


def test_unused_group_detected(graph):
    unused = find_unused_assets(graph)
    assert unused.unused_groups_or_sets == ["Unused Group"]
    assert "High Value Regions" not in unused.unused_groups_or_sets


def test_duplicate_sheets_detected(graph):
    dups = find_duplicate_worksheets(graph, threshold=0.8)
    assert len(dups) == 1
    pair = dups[0]
    assert {pair.sheet_a, pair.sheet_b} == {"Sales by Region", "Sales by Region (Copy)"}
    assert pair.similarity == 1.0
    assert pair.mark_match is True


def test_no_false_duplicate_for_dissimilar_sheets(graph):
    dups = find_duplicate_worksheets(graph, threshold=0.8)
    flagged_names = {n for p in dups for n in (p.sheet_a, p.sheet_b)}
    assert "Profit Ratio by Category" not in flagged_names
    assert "Orphaned Sheet" not in flagged_names


def test_dashboard_weight_scoring(graph):
    results = analyze_dashboards(graph)
    assert len(results) == 1
    dw = results[0]
    assert dw.name == "Executive Overview"
    assert dw.sheet_count == 2
    assert dw.filter_count == 2
    assert dw.risk_level in {"Low", "Medium", "High"}


def test_markdown_report_contains_all_sections(graph):
    unused = find_unused_assets(graph)
    dups = find_duplicate_worksheets(graph)
    dws = analyze_dashboards(graph)
    report = render_markdown_report("sample.twb", unused, dups, dws)

    assert "## 1. Unused Assets" in report
    assert "## 2. Likely Duplicate Worksheets" in report
    assert "## 3. Dashboard Weight" in report
    assert "Unused Calc" in report
    assert "Sales by Region (Copy)" in report


def test_twbx_zip_loading_and_extract_size(tmp_path):
    twbx_path = tmp_path / "sample.twbx"
    with zipfile.ZipFile(twbx_path, "w") as zf:
        zf.write(SAMPLE_TWB, arcname="sample.twb")
        zf.writestr("Data/Superstore/superstore.hyper", b"0" * (2 * 1024 * 1024))

    loaded = load_workbook(str(twbx_path))
    assert loaded.is_packaged is True
    assert len(loaded.extracts) == 1
    assert loaded.total_extract_bytes == 2 * 1024 * 1024


def test_unsupported_file_type_raises(tmp_path):
    bad_file = tmp_path / "not_a_workbook.txt"
    bad_file.write_text("hello")
    with pytest.raises(ValueError):
        load_workbook(str(bad_file))


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_workbook("/nonexistent/path/workbook.twb")
