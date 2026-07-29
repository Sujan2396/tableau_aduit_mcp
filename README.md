# Tableau Workbook Audit MCP Server

[![Tests](https://github.com/Sujan2396/tableau-audit-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/Sujan2396/tableau-audit-mcp/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

An MCP server that audits local Tableau workbooks (`.twb` / `.twbx`) for:

1. **Unused assets** — worksheets never embedded on a dashboard, calculated
   fields nothing depends on (directly or transitively), parameters never
   referenced, and groups/sets never used.
2. **Duplicate worksheets** — near-identical sheets flagged via a weighted
   similarity score (shared fields, mark type, filter overlap), so you know
   what to consolidate.
3. **Dashboard weight** — a load-time risk score per dashboard (worksheet
   count, filter/action/web-object counts, embedded extract size) with
   concrete recommendations.

No Tableau Server/Cloud connection required — it works entirely from the
workbook file on disk.

## Install

```bash
git clone https://github.com/Sujan2396/tableau-audit-mcp.git
cd tableau-audit-mcp
pip install -e .
```

Or, once published, directly from PyPI:

```bash
pip install tableau-audit-mcp
```

## Run standalone (for testing)

```bash
python3 -c "
from tableau_audit import load_workbook, WorkbookGraph, find_unused_assets, analyze_dashboards, find_duplicate_worksheets, render_markdown_report

loaded = load_workbook('/path/to/your/workbook.twbx')
graph = WorkbookGraph(loaded.root)

unused = find_unused_assets(graph)
dups = find_duplicate_worksheets(graph)
dws = analyze_dashboards(graph)

print(render_markdown_report('your_workbook.twbx', unused, dups, dws, loaded.total_extract_bytes / (1024*1024)))
"
```

## Run as an MCP server

```bash
python3 server.py
# or, after `pip install -e .` / `pip install tableau-audit-mcp`:
tableau-audit-mcp
```

### Register with Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tableau-audit": {
      "command": "python3",
      "args": ["/absolute/path/to/tableau-audit-mcp/server.py"]
    }
  }
}
```

## Tools exposed

| Tool | Purpose |
|---|---|
| `load_tableau_workbook(workbook_path)` | Parse + cache a workbook, return a summary |
| `list_unused_assets(workbook_path)` | Unused worksheets/calcs/parameters/groups+sets |
| `find_duplicate_sheets(workbook_path, threshold=0.85)` | Near-duplicate worksheet pairs |
| `analyze_dashboard_performance(workbook_path)` | Per-dashboard weight/risk score + recommendations |
| `get_workbook_health_summary(workbook_path)` | Compact scorecard: counts + structural-complexity % + load-time risk rating |
| `generate_cleanup_report(workbook_path, duplicate_threshold=0.85)` | Full combined Markdown report (recommended default) |

## How the analysis works

- **Field usage**: each `<worksheet>` in the `.twb` XML lists exactly which
  columns it uses via `<datasource-dependencies>`. A field/calc/group/set with
  zero worksheet references (and, for calcs, no other *used* calc depending on
  it) is flagged unused.
- **Parameters**: unlike other fields, parameters aren't referenced via
  dependencies — they're used by name inside formulas, filters, actions, and
  titles. We scan those specifically for the parameter's name (and exclude the
  parameter's own definition, to avoid a trivial self-match).
- **Groups vs. Sets**: both are stored in Tableau's XML as a `<column>` with a
  `<groupfilter>` child, so we track them together as `group_or_set`. Reliably
  telling groups apart from sets from the XML alone is a known limitation
  (see below).
- **Duplicate sheets**: `0.7 × Jaccard(field usage) + 0.15 × (mark type match)
  + 0.15 × Jaccard(filters)`. Tune the threshold per tool call — lower it to
  catch looser near-duplicates.
- **Dashboard weight**: a heuristic score from worksheet count, filter/action/
  web-object counts on the dashboard, plus overall embedded extract size (for
  `.twbx` files). Thresholds are tunable in `tableau_audit/analysis.py`.

## Known limitations / next steps

- **Tableau version drift**: the `.twb` schema has shifted across Desktop
  versions (2018.x vs. 2023.x vs. Cloud). The XPath heuristics here cover the
  common structure; workbooks with heavy custom XML (Tableau Prep flows,
  very old Desktop versions) may need small adjustments in `graph.py`.
- **Group vs. Set disambiguation** is currently a placeholder — both show up
  as `group_or_set`. Both static groups/sets (a `<column>` with a
  `<groupfilter>` child) and dynamic sets like "Top N by..." (a separate
  top-level `<group>` element with a different attribute shape — validated
  against a real workbook) are parsed and tracked for usage, including
  parameters referenced via `count`/`size-parameter` attributes rather than
  formula text. They just aren't labeled apart from each other. If you need
  Groups split from Sets specifically, the most reliable path is
  cross-referencing against the Tableau Metadata API rather than the raw XML.
- **Dashboard action counts** are currently workbook-level (Tableau doesn't
  always scope `<action>` elements per-dashboard in older schema versions) —
  treat this figure as "actions in the workbook that *could* fire from this
  dashboard" rather than a strict per-dashboard count.
- **Extract size** is only available for `.twbx` (packaged) workbooks, since
  `.twb` files reference external `.hyper`/`.tde` files rather than embedding
  them.
- The automated suite in `tests/test_audit.py` covers the synthetic sample
  workbook plus regression cases found while validating against real Tableau
  Public workbooks. It's not exhaustive — if you hit a workbook shape that
  breaks parsing, please open an issue (see CONTRIBUTING.md) with a minimal
  reproducing snippet.
- The two "Workbook Health" headline numbers are intentionally scoped
  honestly: **structural complexity reduction %** is a heuristic (documented
  in `compute_health_summary`'s docstring) based on unused-asset ratios, not
  a calibrated file-size prediction. **Dashboard load-time risk** is a
  qualitative Low/Medium/High rating rather than a percentage, because
  Tableau publishes no formula for converting static asset counts into a
  load-time number — for a measured value, use Tableau's own
  [Performance Recorder](https://help.tableau.com/current/pro/desktop/en-us/performance_tips.htm).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup
instructions, what kinds of contributions are most valuable, and development
guidelines.

## License

[MIT](LICENSE) — free to use, modify, and redistribute.
