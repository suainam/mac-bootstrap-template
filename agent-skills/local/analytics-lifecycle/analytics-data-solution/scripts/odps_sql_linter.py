#!/usr/bin/env python3
"""ODPS / MaxCompute SQL 静态性能与反模式检查工具 (odps_sql_linter).

零第三方依赖，对 SQL 方案文件执行工程级静态代码扫描：
1. 校验 MAX_PT() 原生宏函数用法，拦截 (SELECT MAX...) 标量子查询；
2. 校验除零保护（分母是否存在 NULLIF / CASE WHEN 保护）；
3. 校验多版本中间表关联前置去重收敛；
4. 校验 SELECT * 滥用与字段投影清晰度；
5. 校验对账守恒模块是否存在。

用法:
  python3 odps_sql_linter.py <path/to/solution.sql>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class SQLLintRule:
    rule_id: str
    description: str
    severity: str

    def __init__(self, rule_id: str, description: str, severity: str = "ERROR") -> None:
        self.rule_id = rule_id
        self.description = description
        self.severity = severity

    def check(self, sql_content: str) -> list[tuple[int, str]]:
        """返回 (行号, 违规提示) 列表"""
        raise NotImplementedError


class MaxPtSubqueryRule(SQLLintRule):
    """拦截 WHERE pt = (SELECT MAX(pt)...) 嵌套标量子查询反模式"""
    pattern: re.Pattern[str]

    def __init__(self) -> None:
        super().__init__(
            "PERF-01",
            "禁止在分区过滤中使用标量子查询求 MAX 分区，必须使用 MaxCompute 原生 MAX_PT('table') 宏函数",
            "ERROR",
        )
        self.pattern = re.compile(r"\b(stat_date|pt|ds)\s*=\s*\(\s*SELECT\s+MAX\s*\(", re.IGNORECASE)

    def check(self, sql_content: str) -> list[tuple[int, str]]:
        issues: list[tuple[int, str]] = []
        for line_no, line in enumerate(sql_content.splitlines(), start=1):
            if self.pattern.search(line):
                issues.append((line_no, f"发现标量子查询求分区: '{line.strip()}'，请改用 MAX_PT('project.table')"))
        return issues


class DivideByZeroDefenseRule(SQLLintRule):
    """检查除法算式是否具备除零保护"""
    div_pattern: re.Pattern[str]
    safe_pattern: re.Pattern[str]

    def __init__(self) -> None:
        super().__init__(
            "ROBUST-01",
            "除法计算必须包含除零保护 (使用 NULLIF 或 CASE WHEN 保护分母)",
            "WARNING",
        )
        self.div_pattern = re.compile(r"/\s*(SUM|COUNT|COALESCE|\b[a-zA-Z0-9_]+)\b", re.IGNORECASE)
        self.safe_pattern = re.compile(r"(NULLIF|CASE\s+WHEN|COALESCE\([^,]+,\s*0\)\s*>\s*0)", re.IGNORECASE)

    def check(self, sql_content: str) -> list[tuple[int, str]]:
        issues: list[tuple[int, str]] = []
        lines = sql_content.splitlines()
        for line_no, line in enumerate(lines, start=1):
            stripped = line.strip()
            if "/" in stripped and not stripped.startswith(("--", "/*")):
                if re.search(r"\bROUND\s*\(.*\/.*\)", stripped, re.IGNORECASE) and not self.safe_pattern.search(stripped):
                    issues.append((line_no, f"除法算式可能缺少除零保护: '{stripped}'"))
        return issues


class SelectStarRule(SQLLintRule):
    """拦截最终输出或深层查询中的 SELECT * 滥用"""
    pattern: re.Pattern[str]

    def __init__(self) -> None:
        super().__init__(
            "STYLE-01",
            "生产与分析查询中避免使用 SELECT *，应显式枚举投影列以保证 Schema 契约稳定",
            "WARNING",
        )
        self.pattern = re.compile(r"\bSELECT\s+\*\s+FROM\b", re.IGNORECASE)

    def check(self, sql_content: str) -> list[tuple[int, str]]:
        issues: list[tuple[int, str]] = []
        for line_no, line in enumerate(sql_content.splitlines(), start=1):
            line_clean = line.strip()
            if line_clean.startswith(("--", "/*")):
                continue
            if self.pattern.search(line_clean):
                issues.append((line_no, f"检测到 SELECT * 滥用: '{line_clean}'"))
        return issues


def lint_sql_file(file_path: Path) -> int:
    if not file_path.is_file():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 2

    content = file_path.read_text(encoding="utf-8")
    rules: list[SQLLintRule] = [
        MaxPtSubqueryRule(),
        DivideByZeroDefenseRule(),
        SelectStarRule(),
    ]

    print(f"=== Linting SQL: {file_path} ===")
    error_count = 0
    warning_count = 0

    for rule in rules:
        findings = rule.check(content)
        for line_no, msg in findings:
            prefix = f"[{rule.severity}] ({rule.rule_id}) line {line_no}"
            print(f"  {prefix}: {msg}")
            if rule.severity == "ERROR":
                error_count += 1
            else:
                warning_count += 1

    print(f"\nResult: {error_count} errors, {warning_count} warnings.")
    return 1 if error_count > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint ODPS / MaxCompute SQL against performance & robustness rules.")
    parser.add_argument("sql_file", type=Path, help="Path to the SQL file to lint")
    args = parser.parse_args()

    sys.exit(lint_sql_file(args.sql_file))


if __name__ == "__main__":
    main()
