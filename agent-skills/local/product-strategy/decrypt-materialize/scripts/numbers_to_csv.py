#!/usr/bin/env python3
"""Convert Apple Numbers files to UTF-8 CSV."""

import csv
import os
import shutil
import sys

try:
    import numbers_parser
except ImportError:
    print(
        'ERROR: numbers-parser not installed. Run: pip3 install "numbers-parser==4.18.5"',
        file=sys.stderr,
    )
    raise SystemExit(1)


def cell_to_str(cell):
    try:
        value = cell.value
    except Exception:
        return ""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return ""
        return str(int(value)) if value == int(value) else str(value)
    return str(value)


def has_data(table):
    check_rows = min(3, table.num_rows)
    for row in table.iter_rows(min_row=0, max_row=check_rows - 1):
        for cell in row:
            if cell_to_str(cell):
                return True
    return False


def export_table(table, path):
    row_count = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in table.iter_rows():
            writer.writerow([cell_to_str(cell) for cell in row])
            row_count += 1
    return row_count


def convert(input_path, output_dir=None):
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(input_path))

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    document = numbers_parser.Document(input_path)
    sheets_with_data = [
        sheet for sheet in document.sheets if sheet.tables and has_data(sheet.tables[0])
    ]

    if not sheets_with_data:
        print("No sheets with data found.", file=sys.stderr)
        raise SystemExit(1)

    if len(sheets_with_data) == 1:
        output_path = os.path.join(output_dir, f"{base_name}.csv")
        if os.path.isdir(output_path):
            shutil.rmtree(output_path)
        rows = export_table(sheets_with_data[0].tables[0], output_path)
        size = os.path.getsize(output_path)
        print(f"Saved: {output_path} ({size:,} bytes, {rows:,} rows)")
        return

    for sheet in sheets_with_data:
        safe_name = sheet.name.replace("/", "_").replace("\\", "_")
        output_path = os.path.join(output_dir, f"{base_name}_{safe_name}.csv")
        rows = export_table(sheet.tables[0], output_path)
        print(f"Saved: {output_path} ({rows:,} rows)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 numbers_to_csv.py <file.numbers> [output_dir]")
        raise SystemExit(1)
    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}", file=sys.stderr)
        raise SystemExit(1)
    convert(input_file, output_dir)
