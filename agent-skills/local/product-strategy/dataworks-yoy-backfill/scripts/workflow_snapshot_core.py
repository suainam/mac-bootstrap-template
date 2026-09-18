"""Pure functions for DataWorks workflow snapshot parsing and rendering.

No I/O, no SDK imports — fully unit-testable. All node keys are STRINGS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ${dsl_xxx} or literal dsl_xxx project-qualified table names
_QUALIFIED_TABLE = r"((?:\$\{dsl_\w+\}|dsl_\w+)\.[A-Za-z0-9_]+)"


def strip_sql_comments(sql: str) -> str:
    """Remove SQL comments and neutralize string literals to prevent false matches.

    Tokenizes single/double quoted strings, block comments, and line comments.
    String contents are neutralized to '' so embedded SQL keywords don't match.
    """
    pattern = r"""
        ( '(?:[^'\\]|\\.|'')*' )     # single-quoted string
      | ( "(?:[^"\\]|\\.|"")*" )     # double-quoted string
      | ( /\*[\s\S]*?\*/ )           # block comment
      | ( --[^\r\n]* )               # line comment
    """
    def replacer(match: re.Match) -> str:
        if match.group(1) or match.group(2):
            return " '' "
        return " "
    return re.sub(pattern, replacer, sql, flags=re.VERBOSE)

def _resolve(table: str) -> str:
    """${dsl_ads}.foo -> dsl_ads.foo"""
    return re.sub(r"\$\{(dsl_\w+)\}", r"\1", table.strip())


def extract_insert_targets(code: str) -> set[str]:
    """Tables a node writes via INSERT OVERWRITE / INTO."""
    clean_code = strip_sql_comments(code)
    found: set[str] = set()
    for m in re.finditer(
        rf"(?im)\binsert\s+(?:overwrite|into)\s+(?:table\s+)?{_QUALIFIED_TABLE}",
        clean_code,
    ):
        found.add(_resolve(m.group(1)))
    return found


def extract_create_targets(code: str) -> set[str]:
    """Tables a node creates via CREATE TABLE [IF NOT EXISTS]."""
    clean_code = strip_sql_comments(code)
    found: set[str] = set()
    for m in re.finditer(
        rf"(?im)\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?{_QUALIFIED_TABLE}",
        clean_code,
    ):
        found.add(_resolve(m.group(1)))
    return found


def extract_written_targets(code: str) -> set[str]:
    """Tables a node writes into: union of INSERT and CREATE TABLE ... AS."""
    return extract_insert_targets(code) | extract_create_targets(code)


def extract_drop_tables(code: str) -> set[str]:
    clean_code = strip_sql_comments(code)
    found: set[str] = set()
    for m in re.finditer(
        rf"(?im)\bdrop\s+table\s+(?:if\s+exists\s+)?{_QUALIFIED_TABLE}", clean_code
    ):
        found.add(_resolve(m.group(1)))
    return found


def extract_sources(code: str) -> set[str]:
    """Tables a node reads: FROM / JOIN references."""
    clean_code = strip_sql_comments(code)
    found: set[str] = set()
    for m in re.finditer(
        rf"(?im)(?:\bfrom\b|\bjoin\b)\s+{_QUALIFIED_TABLE}", clean_code
    ):
        found.add(_resolve(m.group(1)))
    return found


@dataclass
class NodeTableAnalysis:
    """Per-node classification of table references."""

    written_targets: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    external_sources: set[str] = field(default_factory=set)


def analyze_node(code: str, owned_all: set[str] | None = None) -> NodeTableAnalysis:
    """Classify one node's SQL."""
    written = extract_written_targets(code)
    sources = extract_sources(code)
    external = sources - written
    if owned_all is not None:
        external = {s for s in external if s not in owned_all}
    return NodeTableAnalysis(
        written_targets=written,
        sources=sources,
        external_sources=external,
    )


# ---------------------------------------------------------------------------
# DDL assembly (Standard MaxCompute syntax with escaping)
# ---------------------------------------------------------------------------

def _escape_comment(c: str) -> str:
    """Escape MaxCompute DDL string comment."""
    return c.replace("\\", "\\\\").replace("'", "\\'")


def _format_table_identifier(table_name: str) -> str:
    parts = table_name.split(".")
    if len(parts) == 2:
        return f"`{parts[0]}`.`{parts[1]}`"
    return f"`{table_name}`"


def build_table_ddl(
    table_name: str,
    comment: str,
    columns: list[dict[str, str]],
    partitions: list[dict[str, str]],
) -> str:
    """Assemble MaxCompute CREATE TABLE DDL from schema parts."""
    if not columns:
        return f"-- CREATE TABLE {_format_table_identifier(table_name)}: no columns defined"

    def col_line(c: dict[str, str], last: bool) -> str:
        col_name = c["name"]
        col_type = c["type"]
        line = f"  `{col_name}` {col_type}"
        if c.get("comment"):
            line += f" COMMENT '{_escape_comment(c['comment'])}'"
        if not last:
            line += ","
        return line

    body: list[str] = []
    for i, c in enumerate(columns):
        body.append(col_line(c, last=(i == len(columns) - 1)))

    header = f"CREATE TABLE IF NOT EXISTS {_format_table_identifier(table_name)} (\n" + "\n".join(body) + "\n)"
    if comment:
        header += f"\nCOMMENT '{_escape_comment(comment)}'"
    if partitions:
        part_lines = [
            f"  `{p['name']}` {p['type']} COMMENT '{_escape_comment(p.get('comment') or '')}'"
            for p in partitions
        ]
        header += "\nPARTITIONED BY (\n" + ",\n".join(part_lines) + "\n)"
    header += ";"
    return header


# ---------------------------------------------------------------------------
# Mermaid rendering: Subgraph by Node
# ---------------------------------------------------------------------------

def _mid(name: str) -> str:
    return re.sub(r"\W", "_", name)


def _escape_label(label: str) -> str:
    return label.replace('"', "'").replace("\n", " ").strip()


def render_mermaid_topology(
    node_ids: list[int],
    analyses: dict[str, NodeTableAnalysis],
    node_labels: dict[str, str],
) -> list[str]:
    """Render node-by-node subgraphs showing external sources, internal outputs,
    and downstream cross-node dependencies."""
    lines = ["flowchart TD"]

    # 1. Output subgraphs for each node
    for nid in node_ids:
        key = str(nid)
        a = analyses[key]
        nlabel = _escape_label(node_labels.get(key, key).split(".")[0])
        lines.append(f'    subgraph sg_{nid} ["节点 {nid}: {nlabel}"]')
        if a.written_targets:
            for tgt in sorted(a.written_targets):
                lines.append(f'        {_mid(tgt)}["{tgt}"]')
        else:
            lines.append(f'        entry_{nid}["(无产出表)"]')
        lines.append("    end")

    # 2. External sources -> Target node subgraph
    for nid in node_ids:
        key = str(nid)
        a = analyses[key]
        for src in sorted(a.external_sources):
            lines.append(f"    {_mid(src)}[/{src}/] --> sg_{nid}")

    # 3. Cross-node dependencies: Node A's written table -> Node B's subgraph
    for nid in node_ids:
        key = str(nid)
        a = analyses[key]
        for tgt in sorted(a.written_targets):
            for other_nid in node_ids:
                if other_nid == nid:
                    continue
                other_analysis = analyses[str(other_nid)]
                if tgt in other_analysis.sources:
                    lines.append(f"    {_mid(tgt)} ==> sg_{other_nid}")

    return lines


def sort_owned_by_node(
    node_ids: list[int], owned: dict[str, set[str]]
) -> list[tuple[str, list[str]]]:
    """(node_id_str, sorted tables) strictly preserving node order, then table asc."""
    out: list[tuple[str, list[str]]] = []
    for nid in node_ids:
        key = str(nid)
        tables = sorted(owned.get(key, set()))
        if tables:
            out.append((key, tables))
    return out
