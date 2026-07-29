"""
Turns a WorkbookGraph into actionable findings:
  - find_unused_assets(): unused worksheets, calcs, parameters, groups/sets
  - analyze_dashboards(): per-dashboard "weight" score + recommendations
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .graph import WorkbookGraph


@dataclass
class UnusedAssetsReport:
    unused_worksheets: list[str] = dc_field(default_factory=list)
    unused_calculations: list[str] = dc_field(default_factory=list)
    unused_parameters: list[str] = dc_field(default_factory=list)
    unused_groups_or_sets: list[str] = dc_field(default_factory=list)


def _is_calc_transitively_used(key: str, graph: WorkbookGraph, visited: set[str]) -> bool:
    """A calculation counts as 'used' if a worksheet uses it directly, OR if
    it feeds into another calculation that is (transitively) used."""
    if key in visited:
        return False  # guard against circular references
    visited.add(key)

    f = graph.fields[key]
    if f.used_by_worksheets:
        return True

    for other_key, other_f in graph.fields.items():
        if other_f.kind != "calculation" or not other_f.formula:
            continue
        if f.name.strip("[]") in other_f.formula or f.caption in other_f.formula:
            if other_key == key:
                continue
            if _is_calc_transitively_used(other_key, graph, visited):
                return True
    return False


def find_unused_assets(graph: WorkbookGraph) -> UnusedAssetsReport:
    report = UnusedAssetsReport()

    for ws_name, ws in graph.worksheets.items():
        if not ws.on_dashboards:
            report.unused_worksheets.append(ws_name)

    for key, f in graph.fields.items():
        if f.kind == "calculation":
            if not _is_calc_transitively_used(key, graph, set()):
                report.unused_calculations.append(f.caption)
        elif f.kind == "parameter":
            if not f.used_by_calcs and not f.used_by_worksheets:
                report.unused_parameters.append(f.caption)
        elif f.kind == "group_or_set":
            if not f.used_by_worksheets and not f.used_by_calcs:
                report.unused_groups_or_sets.append(f.caption)

    return report


# --------------------------------------------------------------------------- #
# Dashboard weight / load-time risk scoring
# --------------------------------------------------------------------------- #

@dataclass
class DashboardWeightResult:
    name: str
    risk_level: str  # "Low" | "Medium" | "High"
    score: float
    sheet_count: int
    filter_count: int
    action_count: int
    web_object_count: int
    image_object_count: int
    recommendations: list[str] = dc_field(default_factory=list)


# Tunable thresholds - these are heuristics, not hard Tableau limits.
SHEET_COUNT_WARN = 8
SHEET_COUNT_HIGH = 15
FILTER_COUNT_WARN = 6
FILTER_COUNT_HIGH = 12
ACTION_COUNT_WARN = 8
WEB_OBJECT_WARN = 2


def analyze_dashboards(graph: WorkbookGraph) -> list[DashboardWeightResult]:
    results = []
    for name, db in graph.dashboards.items():
        recs: list[str] = []
        score = 0.0

        score += db.zone_count and len(db.worksheet_names) * 3
        if len(db.worksheet_names) >= SHEET_COUNT_HIGH:
            score += 15
            recs.append(
                f"{len(db.worksheet_names)} worksheets on one dashboard - "
                "consider splitting into multiple dashboards or a story."
            )
        elif len(db.worksheet_names) >= SHEET_COUNT_WARN:
            score += 7
            recs.append(
                f"{len(db.worksheet_names)} worksheets is on the high side - "
                "check whether all are truly necessary for this view."
            )

        score += db.filter_object_count * 2
        if db.filter_object_count >= FILTER_COUNT_HIGH:
            score += 10
            recs.append(
                f"{db.filter_object_count} filter objects detected - each quick "
                "filter re-queries the data source; consolidate where possible."
            )
        elif db.filter_object_count >= FILTER_COUNT_WARN:
            score += 5
            recs.append(
                f"{db.filter_object_count} filter objects - consider context "
                "filters or parameter-driven filters for expensive fields."
            )

        if db.action_count >= ACTION_COUNT_WARN:
            score += 5
            recs.append(
                f"{db.action_count} actions defined workbook-wide - verify "
                "none are running on unnecessary 'Filter'/'Highlight' triggers "
                "that fire on every hover."
            )

        if db.web_object_count >= WEB_OBJECT_WARN:
            score += 8
            recs.append(
                f"{db.web_object_count} web/extension objects on this dashboard - "
                "these load external resources and can dominate load time."
            )

        if db.image_object_count > 0:
            score += db.image_object_count * 1
            recs.append(
                f"{db.image_object_count} image object(s) - ensure images are "
                "compressed/optimized before embedding."
            )

        if score >= 30:
            risk = "High"
        elif score >= 15:
            risk = "Medium"
        else:
            risk = "Low"

        if not recs:
            recs.append("No obvious weight issues detected from workbook structure alone.")

        results.append(
            DashboardWeightResult(
                name=name,
                risk_level=risk,
                score=round(score, 1),
                sheet_count=len(db.worksheet_names),
                filter_count=db.filter_object_count,
                action_count=db.action_count,
                web_object_count=db.web_object_count,
                image_object_count=db.image_object_count,
                recommendations=recs,
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results


# --------------------------------------------------------------------------- #
# Compact "Workbook Health" summary (counts + two headline percentages)
# --------------------------------------------------------------------------- #

@dataclass
class WorkbookHealthSummary:
    total_worksheets: int
    used_worksheets: int
    unused_worksheets: int
    total_calculations: int
    used_calculations: int
    unused_calculations: int
    total_parameters: int
    unused_parameters: int
    total_groups_sets: int
    unused_groups_sets: int
    potential_size_reduction_pct: int
    load_time_risk: str  # "Low" | "Medium" | "High" | "N/A"
    load_time_risk_note: str


def compute_health_summary(
    graph: WorkbookGraph,
    unused: UnusedAssetsReport,
    dashboard_weights: list[DashboardWeightResult],
) -> WorkbookHealthSummary:
    """
    Rolls the detailed findings up into a compact scorecard.

    IMPORTANT - what these numbers actually are:

    Tableau does not publish a formula for "% workbook size reduction" or
    "% load time improvement" from a static asset count, and no such formula
    was found in Tableau's own performance guidance (the "Designing Efficient
    Workbooks" whitepaper explicitly states "there is no silver bullet" and
    directs you to the Performance Recorder to measure real timing). So:

    - `potential_size_reduction_pct` estimates reduction in the workbook's
      DEFINITION complexity (worksheet/calc/param/set count in the .twb XML)
      if every unused item were deleted. It is NOT a promise about total
      .twbx file size, which is usually dominated by the embedded extract -
      removing unused fields/worksheets does not shrink the extract at all.
    - `load_time_risk` is intentionally qualitative (Low/Medium/High), not a
      percentage, because unused calculated fields/worksheets have ~zero
      runtime cost (Tableau doesn't evaluate a calc unless it's on a shelf in
      an active view) - so there's no honest way to turn "unused asset count"
      into a load-time number. This rating instead reflects the *documented*
      load-time drivers (worksheet count per dashboard, filter/action counts,
      embedded extract size) via the existing dashboard-weight analysis.
      For an actual measured number, run Tableau's Performance Recorder
      (Help > Settings and Performance > Start Performance Recording) before
      and after making changes - see
      https://help.tableau.com/current/pro/desktop/en-us/performance_tips.htm
    """
    total_ws = len(graph.worksheets)
    unused_ws = len(unused.unused_worksheets)
    used_ws = total_ws - unused_ws

    total_calcs = sum(1 for f in graph.fields.values() if f.kind == "calculation")
    unused_calcs = len(unused.unused_calculations)
    used_calcs = total_calcs - unused_calcs

    total_params = sum(1 for f in graph.fields.values() if f.kind == "parameter")
    unused_params = len(unused.unused_parameters)

    total_sets = sum(1 for f in graph.fields.values() if f.kind == "group_or_set")
    unused_sets = len(unused.unused_groups_or_sets)

    def ratio(u: int, t: int) -> float:
        return (u / t) if t else 0.0

    # Structural complexity reduction: proportion of each definition-object
    # type that could be deleted. Weighted toward worksheets/calcs since each
    # worksheet embeds full view state (panes, marks, encodings, filters) and
    # is the heaviest object in the .twb XML; params/sets are lighter.
    # This is a reasonable proxy for XML/definition bloat, but is NOT the
    # same as total .twbx file size (dominated by the extract, see above).
    size_reduction_pct = round(
        100
        * (
            0.40 * ratio(unused_ws, total_ws)
            + 0.35 * ratio(unused_calcs, total_calcs)
            + 0.15 * ratio(unused_params, total_params)
            + 0.10 * ratio(unused_sets, total_sets)
        )
    )

    # Load-time risk: qualitative, derived only from the documented drivers
    # already captured in dashboard_weights (worksheet/filter/action/image
    # counts, extract size) - never from unused-asset counts.
    if not dashboard_weights:
        load_time_risk = "N/A"
        load_time_risk_note = "No dashboards found in this workbook to assess."
    else:
        risk_order = {"Low": 0, "Medium": 1, "High": 2}
        worst = max(dashboard_weights, key=lambda d: risk_order[d.risk_level])
        n_high = sum(1 for d in dashboard_weights if d.risk_level == "High")
        n_medium = sum(1 for d in dashboard_weights if d.risk_level == "Medium")
        load_time_risk = worst.risk_level
        load_time_risk_note = (
            f"{n_high} dashboard(s) High risk, {n_medium} Medium risk, out of "
            f"{len(dashboard_weights)} total. Worst: '{worst.name}' "
            f"(score {worst.score}). Run Tableau's Performance Recorder for a "
            f"measured before/after number."
        )

    return WorkbookHealthSummary(
        total_worksheets=total_ws,
        used_worksheets=used_ws,
        unused_worksheets=unused_ws,
        total_calculations=total_calcs,
        used_calculations=used_calcs,
        unused_calculations=unused_calcs,
        total_parameters=total_params,
        unused_parameters=unused_params,
        total_groups_sets=total_sets,
        unused_groups_sets=unused_sets,
        potential_size_reduction_pct=size_reduction_pct,
        load_time_risk=load_time_risk,
        load_time_risk_note=load_time_risk_note,
    )
