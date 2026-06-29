---
name: decrypt-materialize
description: Decrypt or materialize opaque local files into readable text or staging CSVs. User-invoked only.
disable-model-invocation: true
---

# decrypt-materialize

Purpose: turn opaque local files into readable artifacts without doing business normalization or downstream QA.

Three branches:
- `.numbers` file with `%TSD-Header-###%` or unreadable iWork bytes -> CSV export
- git-smudge-encrypted text file that the Read tool shows as garbage -> read/edit via shell or python on the real plaintext file
- readable workbook that still needs deterministic sheet-to-CSV staging export -> one CSV per target sheet

Out of scope:
- column renaming
- type coercion beyond safe export behavior
- business rule checks
- relationship validation
- aggregate QA reports

Use the matching reference or script for the chosen branch:
- `references/NUMBERS_NOTES.md`
- `references/OUTPUT_CONTRACT.md`
- `scripts/numbers_to_csv.py`
- `scripts/workbook_to_staging_csv.py`

## Branch 1: Numbers -> CSV

Use when the file ends in `.numbers` or the bytes start with `%TSD-Header-###%`.

1. Verify the `.numbers` file exists.
2. Ensure `numbers-parser` is available.
3. Run `python3 .agents/skills/decrypt-materialize/scripts/numbers_to_csv.py <file.numbers> [output_dir]`.
4. Verify that each written CSV has readable headers and no encrypted header bytes.
Completion criterion: every data-bearing sheet is exported as UTF-8 CSV.

## Branch 2: Smudged text -> readable file access

Use when YAML, config, or text looks encrypted in the Read tool but is plaintext on disk after git smudge.

1. Treat the on-disk file as the source of truth, not the Read tool bytes.
2. Inspect with shell tools or python.
3. If editing is needed, edit the plaintext file directly and let git clean re-encrypt on commit.
Completion criterion: the needed lines are read or edited without inventing a fake decryption path.

## Branch 3: Workbook -> staging CSVs

Use when the workbook is already readable and the job is deterministic sheet export for import.

1. Lock the batch.
- Record the source workbook path.
- Record the output directory.
- Derive the date tag from the user input or file batch naming.
- Confirm the workbook should be split into one CSV per target sheet.
Completion criterion: source path, output path, date tag, and target sheets are explicit.

2. Inspect before export.
- Open the workbook with a spreadsheet reader that can prove the file is readable.
- Record sheet names, row counts, column counts, and the header row for each target sheet.
- Fail loud if the workbook cannot be opened or if the target sheets are missing.
Completion criterion: every target sheet has confirmed presence and basic shape.

3. Export staging CSVs.
- Run `python3 .agents/skills/decrypt-materialize/scripts/workbook_to_staging_csv.py --source ... --output-dir ... --date-tag ...`.
- Apply the filename contract from `references/OUTPUT_CONTRACT.md`.
- Preserve row order and column order.
- Normalize only the empty/error cases from the contract.
Completion criterion: every target sheet has a written CSV at the expected path.

4. Verify the staging set.
- Read each generated CSV.
- Confirm row count and column count match the inspected workbook shape.
- Confirm forbidden placeholder values from the contract are absent.
Completion criterion: workbook readability is proven and every generated CSV passes the staging checks.

5. Report tightly.
- Return the written file paths.
- Return per-file row and column counts.
- State explicitly that the workbook was readable, so it is not blocked by workbook encryption at extraction time.
- State any unresolved sheet-level ambiguity instead of guessing.
Completion criterion: a downstream importer can pick up the files without re-reading the chat.
