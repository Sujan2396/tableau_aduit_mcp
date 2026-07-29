"""
Tableau Workbook Audit - MCP Server

Exposes tools that let an MCP client (Claude, or any other MCP-compatible
agent) audit a local .twb/.twbx file for:
  - unused worksheets, calculations, parameters, groups, and sets
  - near-duplicate worksheets (similarity scoring)
  - dashboard weight / likely load-time risk

Run with:
    python server.py

Then point your MCP client config at this script, e.g. in Claude Desktop's
claude_desktop_config.json:

{
  "mcpServers": {
    "tableau-audit": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from tableau_audit import (
    load_workbook,
    WorkbookGraph,
    find_unused_assets,
    analyze_dashboards,
    compute_health_summary,
    find_duplicate_worksheets,
    render_markdown_report,
    render_health_summary,
)

mcp = FastMCP("tableau-audit")

# Simple in-memory cache so a client can load once, then call several tools
# against the same workbook without re-parsing each time.
_CACHE: dict[str, WorkbookGraph] = {}
_EXTRACT_MB: dict[str, float] = {}


def _get_graph(workbook_path: str) -> WorkbookGraph:
    if workbook_path not in _CACHE:
        loaded = load_workbook(workbook_path)
        _CACHE[workbook_path] = WorkbookGraph(loaded.root)
        _EXTRACT_MB[workbook_path] = loaded.total_extract_bytes / (1024 * 1024)
    return _CACHE[workbook_path]


@mcp.tool()
def load_tableau_workbook(workbook_path: str) -> str:
    """
    Parse a local .twb or .twbx file and cache it for subsequent audit calls.

    Args:
        workbook_path: Absolute path to a .twb or .twbx file on disk.

    Returns a short summary of what was found (counts of worksheets,
    dashboards, calculated fields, parameters, groups/sets).
    """
    graph = _get_graph(workbook_path)
    n_calcs = sum(1 for f in graph.fields.values() if f.kind == "calculation")
    n_params = sum(1 for f in graph.fields.values() if f.kind == "parameter")
    n_groups_sets = sum(1 for f in graph.fields.values() if f.kind == "group_or_set")

    return (
        f"Loaded '{workbook_path}':\n"
        f"- Worksheets: {len(graph.worksheets)}\n"
        f"- Dashboards: {len(graph.dashboards)}\n"
        f"- Calculated fields: {n_calcs}\n"
        f"- Parameters: {n_params}\n"
        f"- Groups/Sets: {n_groups_sets}\n"
        f"- Embedded extract size: {_EXTRACT_MB.get(workbook_path, 0):.1f} MB"
    )


@mcp.tool()
def list_unused_assets(workbook_path: str) -> str:
    """
    List worksheets, calculated fields, parameters, and groups/sets that
    appear unused in the workbook (not embedded on any dashboard, or not
    referenced by anything else).

    Args:
        workbook_path: Absolute path to a .twb or .twbx file on disk.
    """
    graph = _get_graph(workbook_path)
    unused = find_unused_assets(graph)

    parts = ["## Unused Assets\n"]
    parts.append(f"**Unused worksheets ({len(unused.unused_worksheets)}):** "
                  f"{', '.join(unused.unused_worksheets) or 'none'}")
    parts.append(f"**Unused calculations ({len(unused.unused_calculations)}):** "
                  f"{', '.join(unused.unused_calculations) or 'none'}")
    parts.append(f"**Unused parameters ({len(unused.unused_parameters)}):** "
                  f"{', '.join(unused.unused_parameters) or 'none'}")
    parts.append(f"**Unused groups/sets ({len(unused.unused_groups_or_sets)}):** "
                  f"{', '.join(unused.unused_groups_or_sets) or 'none'}")
    return "\n\n".join(parts)


@mcp.tool()
def find_duplicate_sheets(workbook_path: str, threshold: float = 0.85) -> str:
    """
    Find pairs of worksheets that are likely duplicates of each other, based
    on a weighted similarity score (shared fields, mark type, filter overlap).

    Args:
        workbook_path: Absolute path to a .twb or .twbx file on disk.
        threshold: Similarity score (0.0-1.0) above which a pair is flagged.
                   Default 0.85. Lower it to surface looser near-duplicates.
    """
    graph = _get_graph(workbook_path)
    pairs = find_duplicate_worksheets(graph, threshold=threshold)

    if not pairs:
        return f"No worksheet pairs found above similarity threshold {threshold:.0%}."

    lines = [f"Found {len(pairs)} likely-duplicate pair(s):\n"]
    for p in pairs:
        lines.append(
            f"- **{p.sheet_a}** ↔ **{p.sheet_b}**: {p.similarity:.0%} similar "
            f"(mark match: {'yes' if p.mark_match else 'no'}; "
            f"shared fields: {', '.join(p.shared_fields) or 'none'})"
        )
    return "\n".join(lines)


@mcp.tool()
def analyze_dashboard_performance(workbook_path: str) -> str:
    """
    Score every dashboard in the workbook for likely load-time risk based on
    worksheet count, filter/action/web-object counts, and give specific
    recommendations to reduce dashboard weight.

    Args:
        workbook_path: Absolute path to a .twb or .twbx file on disk.
    """
    graph = _get_graph(workbook_path)
    results = analyze_dashboards(graph)

    if not results:
        return "No dashboards found in this workbook."

    lines = []
    for r in results:
        lines.append(f"### {r.name} — Risk: {r.risk_level} (score {r.score})")
        lines.append(
            f"Sheets: {r.sheet_count} | Filters: {r.filter_count} | "
            f"Actions: {r.action_count} | Web objects: {r.web_object_count} | "
            f"Images: {r.image_object_count}"
        )
        for rec in r.recommendations:
            lines.append(f"  - {rec}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_workbook_health_summary(workbook_path: str) -> str:
    """
    Return a compact 'Workbook Health' scorecard: used/unused counts for
    worksheets, calculated fields, parameters, and groups/sets, plus a
    structural-complexity-reduction percentage and a qualitative dashboard
    load-time risk rating (Low/Medium/High - not a percentage, since Tableau
    publishes no formula for converting unused-asset counts into a load-time
    number; use Tableau's Performance Recorder for a measured value). Use
    this when a short, high-level summary is wanted instead of the full
    itemized report.

    Args:
        workbook_path: Absolute path to a .twb or .twbx file on disk.
    """
    graph = _get_graph(workbook_path)
    unused = find_unused_assets(graph)
    dashboard_weights = analyze_dashboards(graph)
    summary = compute_health_summary(graph, unused, dashboard_weights)
    return render_health_summary(summary)


@mcp.tool()
def generate_cleanup_report(workbook_path: str, duplicate_threshold: float = 0.85) -> str:
    """
    Generate the full audit as a single Markdown report combining unused
    assets, duplicate worksheets, and dashboard weight/risk scoring.
    This is the recommended "one call does it all" tool.

    Args:
        workbook_path: Absolute path to a .twb or .twbx file on disk.
        duplicate_threshold: Similarity threshold (0.0-1.0) for flagging
                              duplicate worksheets. Default 0.85.
    """
    graph = _get_graph(workbook_path)
    unused = find_unused_assets(graph)
    duplicates = find_duplicate_worksheets(graph, threshold=duplicate_threshold)
    dashboard_weights = analyze_dashboards(graph)
    extract_mb = _EXTRACT_MB.get(workbook_path)

    return render_markdown_report(
        workbook_name=workbook_path,
        unused=unused,
        duplicates=duplicates,
        dashboard_weights=dashboard_weights,
        total_extract_mb=extract_mb,
    )


def main():
    """Entry point for the `tableau-audit-mcp` console script (see pyproject.toml)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
