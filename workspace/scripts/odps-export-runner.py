#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from vendor.config import ODPSConfig
from vendor.odps_connector import ODPSConnector

EXCEL_MAX_ROWS_PER_SHEET = int(os.environ.get("ODPS_EXPORT_MAX_ROWS_PER_SHEET", "1048576"))
PARQUET_BATCH_SIZE = int(os.environ.get("ODPS_EXPORT_PARQUET_BATCH_SIZE", "20000"))
EXCEL_BATCH_SIZE = int(os.environ.get("ODPS_EXPORT_EXCEL_BATCH_SIZE", "20000"))


def _load_config(config_path: Path) -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("odps_export_config", config_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load config: {config_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    exports = getattr(module, "EXPORTS", None)
    if not isinstance(exports, list) or not exports:
        raise ValueError("EXPORTS must be a non-empty list")
    return exports


def _build_sql(spec: dict[str, Any]) -> str:
    sql = spec.get("sql")
    if sql:
        return str(sql).strip().rstrip(";")
    raise ValueError("each export must define sql")


def _header_row(ws, headers: list[str]) -> None:
    cells = []
    for header in headers:
        cell = WriteOnlyCell(ws, value=header)
        cell.font = Font(bold=True)
        cells.append(cell)
    ws.append(cells)


def _normalize_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _stage_parquet_path(output: Path, spec: dict[str, Any]) -> Path:
    if parquet_output := spec.get("parquet_output"):
        return Path(parquet_output)
    if output.suffix.lower() == ".parquet":
        return output
    return output.with_suffix(".parquet")


def _parquet_to_xlsx(parquet_path: Path, output: Path, base_sheet_name: str, rename_map: dict[str, str]) -> int:
    parquet_file = pq.ParquetFile(parquet_path)
    workbook = Workbook(write_only=True)
    total_rows = 0
    sheet_index = 1
    ws = None
    rows_in_sheet = 0
    for batch in parquet_file.iter_batches(batch_size=EXCEL_BATCH_SIZE):
        batch_table = pa.Table.from_batches([batch])
        columns = batch_table.column_names
        headers = [rename_map.get(col, col) for col in columns]
        if ws is None:
            ws = workbook.create_sheet(title=(base_sheet_name or "Sheet1")[:31])
            _header_row(ws, headers)
            rows_in_sheet = 1
        column_values = [batch_table.column(col).to_pylist() for col in columns]
        for row in zip(*column_values):
            if rows_in_sheet >= EXCEL_MAX_ROWS_PER_SHEET:
                sheet_index += 1
                title = f"{base_sheet_name}_{sheet_index}"[:31]
                ws = workbook.create_sheet(title=title)
                _header_row(ws, headers)
                rows_in_sheet = 1
            ws.append(row)
            total_rows += 1
            rows_in_sheet += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    workbook.close()
    return total_rows


def _fetch_query_to_parquet(sql: str, output: Path) -> tuple[int, list[str]]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        connector = ODPSConnector(ODPSConfig())
        stack.callback(connector.close)
        odps_client = connector.connect()
        instance = odps_client.execute_sql(sql)
        reader = stack.enter_context(instance.open_reader())

        columns = [col.name for col in reader._schema.columns]
        batch_columns = {col: [] for col in columns}
        total_rows = 0
        schema = pa.schema([pa.field(col, pa.string()) for col in columns])

        def make_table(column_batches: dict[str, list[str]]) -> pa.Table:
            return pa.Table.from_pydict(
                {
                    col: pa.array(column_batches[col], type=pa.string())
                    for col in columns
                },
                schema=schema,
            )

        def append_record(record: Any) -> None:
            if isinstance(record, dict):
                for col in columns:
                    batch_columns[col].append(_normalize_value(record.get(col)))
                return
            for col in columns:
                batch_columns[col].append(_normalize_value(record[col]))

        def flush_batch(writer: pq.ParquetWriter | None) -> pq.ParquetWriter | None:
            if not batch_columns[columns[0]]:
                return writer
            table = make_table(batch_columns)
            if writer is None:
                writer = stack.enter_context(pq.ParquetWriter(output, schema))
            writer.write_table(table)
            for col in columns:
                batch_columns[col] = []
            return writer

        first_row = next(iter(reader), None)
        if first_row is None:
            empty_table = pa.Table.from_pydict(
                {col: pa.array([], type=pa.string()) for col in columns},
                schema=schema,
            )
            with pq.ParquetWriter(output, empty_table.schema) as writer:
                writer.write_table(empty_table)
            return 0, columns

        append_record(first_row)
        total_rows += 1

        writer = None
        for record in reader:
            append_record(record)
            total_rows += 1
            if len(batch_columns[columns[0]]) >= PARQUET_BATCH_SIZE:
                writer = flush_batch(writer)

        writer = flush_batch(writer)

        return total_rows, columns


def _run_export(spec: dict[str, Any], dry_run: bool, mode: str, reuse_parquet: bool) -> None:
    name = str(spec.get("name") or "export")
    output = Path(spec.get("output") or f"exports/{name}.xlsx")
    sheet_name = str(spec.get("sheet_name") or name[:31] or "Sheet1")
    sql = _build_sql(spec)
    parquet_path = _stage_parquet_path(output, spec)

    print(f"[odps-export] {name}")
    print(sql)

    if dry_run:
        return

    rename_map = spec.get("rename") or {}
    if mode in {"all", "parquet"}:
        if reuse_parquet and parquet_path.exists():
            print(f"[odps-export] reuse parquet {parquet_path}")
        else:
            print("[odps-export] query start")
            total_rows, _ = _fetch_query_to_parquet(sql, parquet_path)
            print(f"[odps-export] staged {parquet_path} ({total_rows} rows)")

    if mode == "parquet" or output.suffix.lower() == ".parquet":
        return

    if not parquet_path.exists():
        raise FileNotFoundError(f"missing parquet stage: {parquet_path}")

    print("[odps-export] excel start")
    total_rows = _parquet_to_xlsx(parquet_path, output, sheet_name, rename_map)
    print(f"[odps-export] wrote {output} ({total_rows} rows)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export ODPS data to local Excel files")
    parser.add_argument(
        "--config",
        default=os.environ.get("ODPS_EXPORT_CONFIG", "/workspace/odps_export_config.py"),
        help="path to a project-local export config",
    )
    parser.add_argument("--dry-run", action="store_true", help="print SQL only")
    parser.add_argument(
        "--mode",
        choices=["all", "parquet", "excel"],
        default="all",
        help="run full export, only stage parquet, or only convert parquet to Excel",
    )
    parser.add_argument(
        "--reuse-parquet",
        action="store_true",
        help="skip ODPS fetch when the staged parquet file already exists",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    exports = _load_config(config_path)
    for spec in exports:
        _run_export(spec, args.dry_run, args.mode, args.reuse_parquet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
