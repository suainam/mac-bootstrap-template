# Output Contract

## Naming

Use one output file per exported sheet.

Filename pattern:

`<english_sheet_name>_<YYYYMMDD>.csv`

Rules:
- use lowercase snake_case for the English sheet name
- keep one date tag across the batch
- write into the caller-specified output directory
- never overwrite the source workbook

## Normalization

Write these values as empty strings:
- true empty cells
- Excel error cells such as `#N/A`, `#REF!`, `#VALUE!`, `#DIV/0!`, `#NAME?`, `#NUM!`, `#NULL!`
- placeholder strings `NULL`, `null`, `None`, `none`, `NaN`, `nan` after trim

Preserve:
- ordinary strings
- numeric values
- original row order
- original column order

## Verification

For each generated CSV, verify:
- file exists
- header exists
- row count matches the source sheet row count
- column count matches the source sheet column count
- forbidden placeholder values are absent

## Scope guard

This stage is extraction only.
Do not rename columns, infer business meaning, deduplicate rows, or rewrite categories unless the user explicitly expands scope.
