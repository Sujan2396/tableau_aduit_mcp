# Contributing

Thanks for considering contributing to Tableau Audit MCP! This project audits
local Tableau `.twb`/`.twbx` workbooks for unused assets, duplicate
worksheets, and dashboard load-time risk, exposed as an MCP server.

## Getting started

```bash
git clone https://github.com/Sujan2396/tableau-audit-mcp.git
cd tableau-audit-mcp
pip install -e ".[dev]"
pytest tests/ -v
```

## Ways to contribute

- **Report a bug**: if the tool mis-parses a real workbook (wrong "unused"
  verdict, crash on a valid `.twb`/`.twbx`, etc.), open an issue. Please
  include the Tableau Desktop/Server version that produced the workbook if
  you know it, and — if you're able to share it — a minimal reproducing
  workbook with sensitive data stripped out. **Never attach a real workbook
  with confidential business data to a public issue.**
- **Fix a schema-drift edge case**: Tableau's `.twb` XML schema has shifted
  across versions. If you find a workbook shape `graph.py` doesn't handle
  (a new mark type, a new group/set encoding, etc.), a fix with a
  corresponding test in `tests/test_audit.py` is the most valuable
  contribution this project can get.
- **Improve the heuristics**: the dashboard-weight thresholds
  (`SHEET_COUNT_WARN`, `FILTER_COUNT_WARN`, etc. in `analysis.py`) and the
  structural-complexity-reduction weights are starting guesses, not
  calibrated against real measured data. If you have before/after load-time
  measurements (e.g. from Tableau's Performance Recorder) on real workbooks,
  contributions that ground these numbers in actual data are very welcome.
- **Add a new tool**: e.g. exporting findings to CSV, comparing two versions
  of the same workbook over time, or splitting Groups from Sets reliably
  (likely requires the Tableau Metadata API rather than raw XML).

## Development guidelines

- Every fix or feature should come with a test in `tests/test_audit.py`. If
  you're fixing a real-workbook parsing bug, add a minimal synthetic XML
  snippet reproducing the shape that broke, rather than committing the real
  workbook.
- Keep `tableau_audit/` free of any dependency on Tableau Server/Cloud
  credentials or network access — this project's value is that it works
  entirely offline from a local file. Server/Cloud API integration belongs
  in a separate optional module if it's ever added.
- Run `pytest tests/ -v` before opening a PR. All tests should pass.
- Be honest in docstrings and output text about what's a measured fact vs.
  a heuristic estimate — this project deliberately avoids implying more
  precision than it has (see the "Known limitations" section of the README).

## Code of conduct

Be respectful. Assume good faith. This is a small utility project, not a
place for anything else.

## License

By contributing, you agree your contributions will be licensed under this
project's MIT License (see `LICENSE`).
