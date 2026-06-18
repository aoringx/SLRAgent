import argparse
import csv
import re
from pathlib import Path
from typing import Any

from output_utils import DEFAULT_OUTPUT_DIR, ensure_parent_dir, resolve_output_path
from pdf_utils import download_pdf_bytes

try:
    import fitz
except ModuleNotFoundError:
    fitz = None


def require_pymupdf() -> None:
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF is required for PDF extraction. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        )


def page_texts(doc: Any, max_pages: int = 3) -> list[str]:
    limit = min(len(doc), max_pages)
    return [doc[index].get_text("text") for index in range(limit)]


def find_section_text(
    texts: list[str],
    start_patterns: list[str],
    end_patterns: list[str],
    max_chars: int = 3500,
) -> str:
    joined = "\n".join(texts)
    start_regex = "|".join(start_patterns)
    end_regex = "|".join(end_patterns)
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:{start_regex})\s*[:.\-]?\s*\n?(.*?)(?=\n\s*(?:{end_regex})\b|\Z)",
        re.I | re.S,
    )
    match = pattern.search(joined)
    if not match:
        return ""

    section = re.sub(r"\s+", " ", match.group(1)).strip()
    return section[:max_chars].strip()


def extract_abstract_from_pdf(pdf_bytes: bytes) -> str:
    require_pymupdf()

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return find_section_text(
            page_texts(doc),
            start_patterns=["abstract"],
            end_patterns=[
                "keywords",
                "index terms",
                "1\\.?\\s+introduction",
                "i\\.?\\s+introduction",
                "introduction",
                "background",
            ],
        )


def read_rows(input_csv: Path) -> tuple[list[dict[str, str]], list[str]]:
    with input_csv.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def write_rows(output_csv: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    ensure_parent_dir(output_csv)
    with output_csv.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add PDF-extracted abstracts and extraction status to a Scholar CSV."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="CSV produced by the Scholar search program.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV filename. Defaults to the input filename under --output-dir.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated output files.",
    )
    parser.add_argument(
        "--abstract-column",
        default="abstract",
        help="Name of the CSV column to create or update.",
    )
    parser.add_argument(
        "--abstract-status-column",
        default="abstract_extraction_status",
        help="Name of the CSV column for abstract extraction status.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of CSV rows to process.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="HTTP timeout in seconds for PDF downloads.",
    )
    parser.add_argument(
        "--overwrite-abstracts",
        action="store_true",
        help="Replace existing non-empty abstract cells.",
    )
    args = parser.parse_args()

    input_csv = Path(args.input)
    output_csv = resolve_output_path(args.output or input_csv.name, args.output_dir)
    rows, fieldnames = read_rows(input_csv)

    if args.abstract_column not in fieldnames:
        fieldnames.append(args.abstract_column)
    if args.abstract_status_column not in fieldnames:
        fieldnames.append(args.abstract_status_column)

    total_to_process = len(rows) if args.limit is None else min(len(rows), args.limit)
    updated_count = 0

    for index, row in enumerate(rows):
        row.setdefault(args.abstract_column, "")
        row.setdefault(args.abstract_status_column, "")

        if args.limit is not None and index >= args.limit:
            continue

        title = row.get("title") or f"row {index + 1}"
        if row.get(args.abstract_column, "").strip() and not args.overwrite_abstracts:
            print(f"[{index + 1}/{total_to_process}] skipped existing abstract: {title}")
            row[args.abstract_status_column] = "skip"
            continue

        print(f"[{index + 1}/{total_to_process}] extracting abstract: {title}")
        pdf_bytes, download_error = download_pdf_bytes(row, args.timeout)
        if not pdf_bytes:
            print(f"  skipped: {download_error}")
            row[args.abstract_column] = ""
            row[args.abstract_status_column] = "download_failed"
            continue

        try:
            abstract = extract_abstract_from_pdf(pdf_bytes)
        except Exception as exc:
            print(f"  extraction failed: {exc}")
            row[args.abstract_column] = ""
            row[args.abstract_status_column] = "extract_failed"
            continue

        row[args.abstract_column] = abstract
        if abstract:
            updated_count += 1
            row[args.abstract_status_column] = "ok"
            print("  abstract added")
        else:
            row[args.abstract_status_column] = "not_found"
            print("  no abstract found")

    write_rows(output_csv, rows, fieldnames)
    print(f"\nSaved CSV to {output_csv}")
    print(f"Updated {updated_count} abstract cells.")


if __name__ == "__main__":
    main()
