"""
tableau_audit
-------------
A library for parsing Tableau .twb / .twbx files and auditing them for:
  - unused worksheets, calculated fields, parameters, groups, and sets
  - near-duplicate worksheets (similarity scoring)
  - dashboard "weight" / likely load-time risk

This package has no dependency on Tableau Server/Cloud - it works entirely
from a local workbook file.
"""

from .parser import load_workbook
from .graph import WorkbookGraph
from .analysis import find_unused_assets, analyze_dashboards, compute_health_summary
from .similarity import find_duplicate_worksheets
from .report import render_markdown_report, render_health_summary

__all__ = [
    "load_workbook",
    "WorkbookGraph",
    "find_unused_assets",
    "analyze_dashboards",
    "compute_health_summary",
    "find_duplicate_worksheets",
    "render_markdown_report",
    "render_health_summary",
]
