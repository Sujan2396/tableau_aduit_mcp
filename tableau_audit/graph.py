"""
Builds an in-memory dependency graph out of a parsed Tableau workbook.

Node types:
  - field         : a plain column from a datasource
  - calculation   : a column with a <calculation> child (a calculated field)
  - group_or_set  : a column with a <groupfilter> child (Tableau stores both
                    Groups and Sets this way; we heuristically label which)
  - parameter     : a column living in the special "Parameters" datasource,
                    or carrying a param-domain-type attribute
  - worksheet
  - dashboard

Edges we track:
  - worksheet -> field/calc/group_or_set   ("worksheet uses this column")
  - calculation -> calculation             ("calc A's formula references calc B")
  - calculation/filter/action/title -> parameter ("references this parameter by name")
  - dashboard -> worksheet                 ("dashboard embeds this worksheet")

NOTE on Tableau XML variability: Tableau has changed its .twb schema across
versions (2018.x vs 2023.x vs Cloud). The heuristics below cover the common
structure but may need small tweaks for exotic workbooks (e.g. workbooks built
in very old Tableau Desktop versions, or ones with heavy custom XML from
Tableau Prep). Treat unmatched/ambiguous columns as "unknown" rather than
silently misclassifying them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from lxml import etree

FIELD_REF_RE = re.compile(r"\[([^\[\]]+)\]")  # matches [Field Name] tokens

# Matches "[Datasource].[Field]" and captures just the field part, so shelf
# text like "[Superstore].[Sales]+[Superstore].[Profit]" yields ["Sales",
# "Profit"] rather than also picking up "Superstore" as a spurious field.
QUALIFIED_FIELD_RE = re.compile(r"\[[^\[\]]+\]\.\[([^\[\]]+)\]")


def _extract_shelf_fields(text: str) -> list[str]:
    qualified = QUALIFIED_FIELD_RE.findall(text)
    if qualified:
        return qualified
    return FIELD_REF_RE.findall(text)


@dataclass
class FieldNode:
    name: str  # internal name, e.g. "[Sales]" or "[Calculation_123456]"
    caption: str  # display name shown to users
    datasource: str
    kind: str  # "field" | "calculation" | "group_or_set" | "parameter"
    formula: str | None = None
    role: str | None = None  # dimension / measure
    used_by_worksheets: set[str] = dc_field(default_factory=set)
    used_by_calcs: set[str] = dc_field(default_factory=set)


@dataclass
class WorksheetNode:
    name: str
    used_fields: set[str] = dc_field(default_factory=set)  # field internal names
    mark_type: str | None = None
    rows_shelf: list[str] = dc_field(default_factory=list)
    cols_shelf: list[str] = dc_field(default_factory=list)
    filters: list[str] = dc_field(default_factory=list)  # field names filtered on
    color_field: str | None = None
    size_field: str | None = None
    label_field: str | None = None
    on_dashboards: set[str] = dc_field(default_factory=set)


@dataclass
class DashboardNode:
    name: str
    worksheet_names: set[str] = dc_field(default_factory=set)
    zone_count: int = 0
    filter_object_count: int = 0
    action_count: int = 0
    web_object_count: int = 0
    image_object_count: int = 0


class WorkbookGraph:
    def __init__(self, root: etree._Element):
        self.root = root
        self.fields: dict[str, FieldNode] = {}       # keyed by internal name e.g. "[Sales]"
        self.worksheets: dict[str, WorksheetNode] = {}
        self.dashboards: dict[str, DashboardNode] = {}
        self._build()

    # ------------------------------------------------------------------ #
    # Building
    # ------------------------------------------------------------------ #

    def _build(self):
        self._extract_fields()
        self._extract_worksheets()
        self._extract_dashboards()
        self._link_calc_to_calc_references()
        self._link_parameter_references()

    def _extract_fields(self):
        for ds in self.root.findall(".//datasources/datasource"):
            ds_name = ds.get("name", "unknown_datasource")
            ds_caption = ds.get("caption", ds_name)
            is_params_ds = ds_name == "Parameters" or ds_caption == "Parameters"

            for col in ds.findall("./column"):
                internal_name = col.get("name")
                if not internal_name:
                    continue
                caption = col.get("caption", internal_name.strip("[]"))
                role = col.get("role")

                calc_el = col.find("./calculation")
                groupfilter_el = col.find("./groupfilter")
                has_param_domain = col.get("param-domain-type") is not None

                if is_params_ds or has_param_domain:
                    kind = "parameter"
                elif calc_el is not None:
                    kind = "calculation"
                elif groupfilter_el is not None:
                    kind = "group_or_set"
                else:
                    kind = "field"

                formula = calc_el.get("formula") if calc_el is not None else None
                # bin-type calcs (including binned "groups") reference a
                # parameter via a size-parameter attribute rather than in the
                # formula text - fold it into the formula string so our
                # generic parameter-reference scan (which looks for the
                # parameter's name/caption as a substring) still catches it.
                if calc_el is not None and calc_el.get("size-parameter"):
                    formula = f"{formula or ''} {calc_el.get('size-parameter')}"

                key = f"{ds_name}::{internal_name}"
                self.fields[key] = FieldNode(
                    name=internal_name,
                    caption=caption,
                    datasource=ds_name,
                    kind=kind,
                    formula=formula,
                    role=role,
                )

            # Dynamic sets (e.g. "Top N by ...") are stored as a top-level
            # <group> element sibling to <column>, NOT as a <column> with a
            # <groupfilter> child - a different shape from static groups/sets.
            # The <groupfilter count="[Parameters].[Parameter 1]" .../> style
            # attributes reference parameters directly, so we fold every
            # attribute value into a synthetic "formula" string too, reusing
            # the same downstream reference-scanning logic.
            for grp in ds.findall("./group"):
                internal_name = grp.get("name")
                if not internal_name:
                    continue
                caption = grp.get("caption", internal_name.strip("[]"))
                attr_values = " ".join(
                    el.get(attr, "")
                    for el in grp.iter()
                    for attr in ("count", "size-parameter", "expression")
                    if el.get(attr)
                )
                key = f"{ds_name}::{internal_name}"
                self.fields[key] = FieldNode(
                    name=internal_name,
                    caption=caption,
                    datasource=ds_name,
                    kind="group_or_set",
                    formula=attr_values or None,
                    role="dimension",
                )

    def _find_field_key_by_internal_name(self, internal_name: str) -> str | None:
        """Fields are keyed by 'datasource::internal_name'; worksheet-level
        references usually just give the internal name, so resolve loosely."""
        matches = [k for k in self.fields if k.endswith(f"::{internal_name}")]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Ambiguous across datasources - prefer non-Parameters datasource
            non_param = [k for k in matches if not k.startswith("Parameters::")]
            return non_param[0] if non_param else matches[0]
        return None

    def _extract_worksheets(self):
        for ws in self.root.findall(".//worksheets/worksheet"):
            name = ws.get("name", "unnamed_worksheet")
            node = WorksheetNode(name=name)

            # datasource-dependencies list every column actually used
            for dep_block in ws.findall(".//datasource-dependencies"):
                for col in dep_block.findall("./column"):
                    internal_name = col.get("name")
                    if not internal_name:
                        continue
                    key = self._find_field_key_by_internal_name(internal_name)
                    if key:
                        node.used_fields.add(key)
                        self.fields[key].used_by_worksheets.add(name)

            mark_el = ws.find(".//panes/pane/mark")
            if mark_el is not None:
                node.mark_type = mark_el.get("class")

            rows_el = ws.find(".//table/rows")
            if rows_el is not None and rows_el.text:
                node.rows_shelf = _extract_shelf_fields(rows_el.text)
            cols_el = ws.find(".//table/cols")
            if cols_el is not None and cols_el.text:
                node.cols_shelf = _extract_shelf_fields(cols_el.text)

            for filt in ws.findall(".//view/filter"):
                col = filt.get("column")
                if col:
                    node.filters.append(col)

            encodings = ws.find(".//panes/pane/encodings")
            if encodings is not None:
                color_el = encodings.find("./color")
                if color_el is not None:
                    node.color_field = color_el.get("column")
                size_el = encodings.find("./size")
                if size_el is not None:
                    node.size_field = size_el.get("column")
                label_el = encodings.find("./text")
                if label_el is not None:
                    node.label_field = label_el.get("column")

            self.worksheets[name] = node

    def _extract_dashboards(self):
        for db in self.root.findall(".//dashboards/dashboard"):
            name = db.get("name", "unnamed_dashboard")
            node = DashboardNode(name=name)

            zones = db.findall(".//zones//zone")
            node.zone_count = len(zones)
            for z in zones:
                ws_name = z.get("name")
                if ws_name and ws_name in self.worksheets:
                    node.worksheet_names.add(ws_name)
                    self.worksheets[ws_name].on_dashboards.add(name)

                z_type = z.get("type-v2") or z.get("type") or ""
                if z_type == "filter":
                    node.filter_object_count += 1
                elif z_type in ("web", "extension"):
                    node.web_object_count += 1
                elif z_type == "bitmap":
                    node.image_object_count += 1

            node.action_count = len(
                self.root.findall(".//actions/action")
            )  # actions are workbook-level in most schema versions; refined later if needed

            self.dashboards[name] = node

    def _link_calc_to_calc_references(self):
        """Parse each calculation's formula for [Other Field] tokens and link them,
        so we can later do a transitive 'is this calc used' check."""
        caption_lookup = {f.caption: key for key, f in self.fields.items()}
        internal_lookup = {f.name.strip("[]"): key for key, f in self.fields.items()}

        for key, f in self.fields.items():
            if f.kind != "calculation" or not f.formula:
                continue
            tokens = FIELD_REF_RE.findall(f.formula)
            for tok in tokens:
                ref_key = caption_lookup.get(tok) or internal_lookup.get(tok)
                if ref_key and ref_key != key:
                    self.fields[ref_key].used_by_calcs.add(f.name)

    def _link_parameter_references(self):
        """Parameters aren't referenced via datasource-dependencies, so scan
        calc formulas, worksheet filters, and dashboard titles/actions for the
        parameter's caption or internal name."""
        params = {k: f for k, f in self.fields.items() if f.kind == "parameter"}
        if not params:
            return

        haystacks: list[str] = []
        for f in self.fields.values():
            if f.formula:
                haystacks.append(f.formula)
        for ws in self.worksheets.values():
            haystacks.extend(ws.filters)

        # Scan dashboard zones (parameter controls, quick filters, titles,
        # actions) and worksheet titles, but deliberately EXCLUDE the
        # <datasources><datasource name="Parameters"> subtree itself -
        # otherwise every parameter's own <column> definition would
        # trivially "match" its own name and always look "used".
        for db in self.root.findall(".//dashboards/dashboard"):
            haystacks.append(etree.tostring(db, encoding="unicode"))
        for actions_block in self.root.findall(".//actions"):
            haystacks.append(etree.tostring(actions_block, encoding="unicode"))
        for ws_el in self.root.findall(".//worksheets/worksheet"):
            title_el = ws_el.find(".//title")
            if title_el is not None:
                haystacks.append(etree.tostring(title_el, encoding="unicode"))

        combined = "\n".join(haystacks)

        for key, p in params.items():
            referenced = (p.caption in combined) or (p.name in combined)
            if referenced:
                # Mark as used by tagging a synthetic worksheet reference
                # so downstream "unused" logic treats it as used.
                p.used_by_calcs.add("__referenced__")
