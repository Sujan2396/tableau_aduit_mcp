"""
Renders the combined findings (unused assets, duplicates, dashboard weight)
into a single Markdown report. Kept dependency-free (no Jinja2) so the
library only needs lxml to run.
"""

from __future__ import annotations

from .analysis import UnusedAssetsReport, DashboardWeightResult, WorkbookHealthSummary
from .similarity import DuplicatePair


def render_health_summary(summary: WorkbookHealthSummary) -> str:
    """Compact scorecard: counts + one honest percentage (structural
    complexity reduction) + one qualitative rating (load-time risk, since
    Tableau publishes no formula for a load-time percentage - see
    compute_health_summary's docstring)."""
    lines = [
        "Workbook Health",
        "",
        f"Worksheets: {summary.total_worksheets}",
        f"Used: {summary.used_worksheets}",
        f"Unused: {summary.unused_worksheets}",
        "",
        "Calculated Fields:",
        f"Used: {summary.used_calculations}",
        f"Unused: {summary.unused_calculations}",
        "",
        "Parameters:",
        f"Unused: {summary.unused_parameters}",
        "",
        "Groups / Sets:",
        f"Unused: {summary.unused_groups_sets}",
        "",
        "Potential Structural Complexity Reduction",
        "",
        f"{summary.potential_size_reduction_pct}%",
        "",
        "Dashboard Load-Time Risk",
        "",
        summary.load_time_risk,
        summary.load_time_risk_note,
    ]
    return "\n".join(lines)


def _bullet_list(items: list[str], empty_msg: str) -> str:
    if not items:
        return f"_{empty_msg}_\n"
    return "\n".join(f"- {item}" for item in items) + "\n"


def render_markdown_report(
    workbook_name: str,
    unused: UnusedAssetsReport,
    duplicates: list[DuplicatePair],
    dashboard_weights: list[DashboardWeightResult],
    total_extract_mb: float | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# Tableau Workbook Audit: {workbook_name}\n")

    if total_extract_mb is not None:
        lines.append(f"**Total embedded extract size:** {total_extract_mb:.1f} MB\n")

    # --- Unused assets ---
    lines.append("## 1. Unused Assets\n")

    lines.append(f"### Worksheets not on any dashboard ({len(unused.unused_worksheets)})\n")
    lines.append(_bullet_list(unused.unused_worksheets, "None found - every worksheet is embedded somewhere."))

    lines.append(f"\n### Unused calculated fields ({len(unused.unused_calculations)})\n")
    lines.append(_bullet_list(unused.unused_calculations, "None found - all calculations trace to a used worksheet."))

    lines.append(f"\n### Unused parameters ({len(unused.unused_parameters)})\n")
    lines.append(_bullet_list(unused.unused_parameters, "None found - all parameters are referenced somewhere."))

    lines.append(f"\n### Unused groups / sets ({len(unused.unused_groups_or_sets)})\n")
    lines.append(_bullet_list(unused.unused_groups_or_sets, "None found - all groups/sets are referenced somewhere."))

    # --- Duplicates ---
    lines.append("\n## 2. Likely Duplicate Worksheets\n")
    if not duplicates:
        lines.append("_No worksheet pairs exceeded the similarity threshold._\n")
    else:
        lines.append("| Sheet A | Sheet B | Similarity | Mark Match | Shared Fields |")
        lines.append("|---|---|---|---|---|")
        for pair in duplicates:
            shared = ", ".join(pair.shared_fields[:6]) + (
                "..." if len(pair.shared_fields) > 6 else ""
            )
            lines.append(
                f"| {pair.sheet_a} | {pair.sheet_b} | {pair.similarity:.0%} | "
                f"{'Yes' if pair.mark_match else 'No'} | {shared or '-'} |"
            )

    # --- Dashboard weight ---
    lines.append("\n## 3. Dashboard Weight / Load-Time Risk\n")
    if not dashboard_weights:
        lines.append("_No dashboards found in this workbook._\n")
    else:
        for dw in dashboard_weights:
            lines.append(f"### {dw.name} — Risk: **{dw.risk_level}** (score {dw.score})\n")
            lines.append(
                f"- Worksheets embedded: {dw.sheet_count}\n"
                f"- Filter objects: {dw.filter_count}\n"
                f"- Actions (workbook-wide): {dw.action_count}\n"
                f"- Web/extension objects: {dw.web_object_count}\n"
                f"- Image objects: {dw.image_object_count}\n"
            )
            lines.append("**Recommendations:**\n")
            lines.append(_bullet_list(dw.recommendations, "None."))
            lines.append("")

    return "\n".join(lines)
