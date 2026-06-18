import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests

from output_utils import DEFAULT_OUTPUT_DIR
from pdf_utils import download_pdf_bytes

try:
    import fitz
except ModuleNotFoundError:
    fitz = None

GROBID_PROCESS_FULLTEXT_URL = "http://localhost:8070/api/processFulltextDocument"
INTRO_HEADINGS = {
    "introduction",
    "1 introduction",
    "background",
}
CONCLUSION_HEADINGS = {
    "conclusion",
    "conclusions",
    "discussion and conclusion",
    "conclusion and future work",
    "limitations and conclusion",
}


def require_pymupdf() -> None:
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF is required for PDF extraction. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        )


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:90] or fallback


def stable_paper_id(row: dict[str, str], index: int) -> str:
    raw = (
        row.get("result_id")
        or row.get("pdf_link")
        or row.get("link")
        or row.get("title")
        or str(index)
    )
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{slugify(row.get('title', ''), f'paper-{index + 1}')}-{digest}"


def normalize_heading(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"^[\divx]+\s*[.)-]?\s+", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*\s*[.)-]?\s+", "", value)
    return value


def read_rows(input_csv: Path) -> list[dict[str, str]]:
    with input_csv.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def grobid_process_fulltext_document(
    pdf_bytes: bytes,
    grobid_url: str = GROBID_PROCESS_FULLTEXT_URL,
    timeout: int = 90,
) -> tuple[str | None, str | None]:
    files = {"input": ("paper.pdf", pdf_bytes, "application/pdf")}
    data = {
        "consolidateHeader": "1",
        "consolidateCitations": "0",
        "includeRawCitations": "0",
        "includeRawAffiliations": "0",
    }

    try:
        response = requests.post(grobid_url, files=files, data=data, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, str(exc)

    tei_xml = response.text.strip()
    if not tei_xml:
        return None, "GROBID returned an empty response"

    return tei_xml, None


def parse_tei(tei_xml: str) -> ElementTree.Element:
    return ElementTree.fromstring(tei_xml)


def tei_text(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    return clean_text(" ".join(element.itertext()))


def tei_findall(root: ElementTree.Element, path: str) -> list[ElementTree.Element]:
    return root.findall(path, namespaces={"tei": "http://www.tei-c.org/ns/1.0"})


def extract_title_from_tei(tei_xml: str) -> str:
    root = parse_tei(tei_xml)
    title_candidates = tei_findall(root, ".//tei:titleStmt/tei:title")
    if not title_candidates:
        title_candidates = tei_findall(root, ".//tei:title")
    return tei_text(title_candidates[0]) if title_candidates else ""


def extract_abstract_from_tei(tei_xml: str) -> str:
    root = parse_tei(tei_xml)
    abstract_candidates = tei_findall(root, ".//tei:profileDesc/tei:abstract")
    if not abstract_candidates:
        abstract_candidates = tei_findall(root, ".//tei:abstract")
    return tei_text(abstract_candidates[0]) if abstract_candidates else ""


def extract_sections_from_tei(tei_xml: str) -> list[dict[str, str]]:
    root = parse_tei(tei_xml)
    sections = []

    for div in tei_findall(root, ".//tei:text/tei:body//tei:div"):
        head = div.find("tei:head", namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
        heading = tei_text(head)
        normalized = normalize_heading(heading)

        if normalized in INTRO_HEADINGS:
            section_type = "introduction"
        elif normalized in CONCLUSION_HEADINGS:
            section_type = "conclusion"
        else:
            continue

        paragraphs = tei_findall(div, ".//tei:p")
        text = clean_text(" ".join(tei_text(paragraph) for paragraph in paragraphs))
        sections.append(
            {
                "heading": heading,
                "text": text,
                "section_type": section_type,
            }
        )

    return sections


def extract_grobid_context(
    pdf_bytes: bytes,
    grobid_url: str = GROBID_PROCESS_FULLTEXT_URL,
    timeout: int = 90,
) -> dict[str, Any]:
    tei_xml, error = grobid_process_fulltext_document(pdf_bytes, grobid_url, timeout)
    if not tei_xml:
        return {
            "title": "",
            "abstract": "",
            "sections": [],
            "tei_xml": "",
            "grobid_error": error,
        }

    return {
        "title": extract_title_from_tei(tei_xml),
        "abstract": extract_abstract_from_tei(tei_xml),
        "sections": extract_sections_from_tei(tei_xml),
        "tei_xml": tei_xml,
        "grobid_error": None,
    }


def extract_full_text_with_pymupdf(pdf_path: Path) -> str:
    require_pymupdf()

    with fitz.open(pdf_path) as doc:
        return "\n\n".join(page.get_text("text") for page in doc)


def build_markdown(paper: dict[str, Any]) -> str:
    lines = [f"# {paper.get('title') or paper.get('source_title') or paper['paper_id']}"]

    if paper.get("abstract"):
        lines.extend(["", "## Abstract", "", paper["abstract"]])

    sections = paper.get("sections", [])
    if sections:
        for section in sections:
            lines.extend(["", f"## {section['heading']}", "", section["text"]])

    return "\n".join(lines).strip() + "\n"


def process_paper(
    row: dict[str, str],
    index: int,
    output_dir: Path,
    download_timeout: int,
    grobid_url: str,
    grobid_timeout: int,
    overwrite: bool,
) -> dict[str, Any]:
    paper_id = stable_paper_id(row, index)
    paper_dir = output_dir / paper_id
    paper_json_path = paper_dir / "paper.json"

    if paper_json_path.exists() and not overwrite:
        return {
            "paper_id": paper_id,
            "source_title": row.get("title", ""),
            "status": "skipped_existing_output",
            "paper_json_path": str(paper_json_path),
        }

    paper_dir.mkdir(parents=True, exist_ok=True)
    write_json(paper_dir / "source_metadata.json", row)

    pdf_bytes, download_error = download_pdf_bytes(row, download_timeout)
    if not pdf_bytes:
        result = {
            "paper_id": paper_id,
            "source_title": row.get("title", ""),
            "status": "failed_download",
            "error": download_error,
        }
        write_json(paper_json_path, result)
        return result

    pdf_path = paper_dir / "paper.pdf"
    pdf_path.write_bytes(pdf_bytes)

    grobid_context = extract_grobid_context(pdf_bytes, grobid_url, grobid_timeout)
    if grobid_context.get("tei_xml"):
        write_text(paper_dir / "paper.tei.xml", grobid_context["tei_xml"])

    abstract = clean_text(row.get("abstract", ""))
    if abstract:
        abstract_source = "csv"
        abstract_status = "csv"
        abstract_error = None
    else:
        abstract = clean_text(grobid_context.get("abstract", ""))
        if abstract:
            abstract_source = "grobid"
            abstract_status = "grobid"
            abstract_error = None
        elif grobid_context.get("grobid_error"):
            abstract_source = ""
            abstract_status = "grobid_failed"
            abstract_error = grobid_context["grobid_error"]
        else:
            abstract_source = ""
            abstract_status = "not_found"
            abstract_error = None

    full_text_path = paper_dir / "fulltext.txt"
    try:
        full_text = extract_full_text_with_pymupdf(pdf_path)
        write_text(full_text_path, full_text)
        full_text_error = None
    except Exception as exc:
        full_text_path = None
        full_text_error = str(exc)

    paper = {
        "paper_id": paper_id,
        "source_title": row.get("title", ""),
        "title": grobid_context.get("title") or row.get("title", ""),
        "authors": row.get("authors", ""),
        "year": row.get("year", ""),
        "abstract": abstract,
        "abstract_source": abstract_source,
        "abstract_extraction_status": abstract_status,
        "pdf_link": row.get("pdf_link", ""),
        "link": row.get("link", ""),
        "pdf_path": str(pdf_path),
        "full_text_path": str(full_text_path) if full_text_path else "",
        "markdown_path": str(paper_dir / "paper.md"),
        "sections": grobid_context.get("sections", []),
        "status": "success",
        "errors": {
            "abstract": abstract_error,
            "grobid": grobid_context.get("grobid_error"),
            "full_text": full_text_error,
        },
    }
    write_json(paper_json_path, paper)
    write_text(paper_dir / "paper.md", build_markdown(paper))
    return paper


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract full paper context into per-paper files."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="CSV produced by the Scholar search program.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR / "processed_papers"),
        help="Directory for per-paper folders and manifest.json.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of CSV rows to process.",
    )
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=45,
        help="HTTP timeout in seconds for PDF downloads.",
    )
    parser.add_argument(
        "--grobid-url",
        default=GROBID_PROCESS_FULLTEXT_URL,
        help="GROBID processFulltextDocument URL.",
    )
    parser.add_argument(
        "--grobid-timeout",
        type=int,
        default=90,
        help="HTTP timeout in seconds for GROBID requests.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reprocess papers even when paper.json already exists.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_rows(Path(args.input))
    if args.limit is not None:
        rows = rows[: args.limit]

    manifest = []
    for index, row in enumerate(rows):
        title = row.get("title") or f"row {index + 1}"
        print(f"[{index + 1}/{len(rows)}] processing context: {title}")
        result = process_paper(
            row=row,
            index=index,
            output_dir=output_dir,
            download_timeout=args.download_timeout,
            grobid_url=args.grobid_url,
            grobid_timeout=args.grobid_timeout,
            overwrite=args.overwrite,
        )
        manifest.append(
            {
                "paper_id": result["paper_id"],
                "source_title": result.get("source_title", ""),
                "status": result.get("status", ""),
                "paper_json_path": str(output_dir / result["paper_id"] / "paper.json"),
            }
        )
        print(f"  {result.get('status', 'unknown')}")

    write_json(output_dir / "manifest.json", manifest)
    print(f"\nSaved manifest to {output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
