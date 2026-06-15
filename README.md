# SLR Agent

SLR Agent collects Google Scholar paper metadata through SerpAPI, stores it in a CSV, enriches that CSV with abstracts, and can separately extract richer paper context into structured files.

The main workflow is intentionally simple:

1. Search Google Scholar with SerpAPI.
2. Save the paper metadata to a CSV.
3. Add abstracts and abstract extraction status to the CSV.
4. Optionally extract full paper context into per-paper folders.

## Repository Structure

```text
.
├── README.md
├── requirements.txt
├── scholar_search.py
├── abstract_extractor.py
└── full_paper_extractor.py
```

`scholar_search.py`
: Searches Google Scholar through SerpAPI and writes a deduplicated CSV. The default output is `scholar_results.csv`.

`abstract_extractor.py`
: Reads the Scholar CSV, fetches PDFs from `pdf_link` or `link`, extracts abstracts with PyMuPDF, and writes `abstract` plus `abstract_extraction_status` columns back to the CSV.

`full_paper_extractor.py`
: Reads the Scholar CSV, fetches PDFs, and writes richer paper context into per-paper folders with JSON, Markdown, full text, TEI XML, and source metadata. If the CSV has no abstract for a row, it extracts one from the PDF and records the status in `paper.json`.

`requirements.txt`
: Python dependencies for search, CSV handling, and PDF text extraction.

Generated/local files are ignored by git:

```text
.env
.venv/
*.pdf
__pycache__/
test_extraction_output/
processed_papers/
```

## Setup

Create and activate a local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a `.env` file with your SerpAPI key:

```bash
SERPAPI_KEY=your_serpapi_key_here
```

## Workflow

### 1. Collect Scholar Metadata

Run the Scholar search:

```bash
python scholar_search.py --output scholar_results.csv --mode append
```

Useful options:

```bash
python scholar_search.py --mode overwrite --output scholar_results.csv
```

The query keywords are controlled by `KEYWORDS` near the top of `scholar_search.py`. Keywords are joined with ` + `. The number of results is controlled by `MAX_RESULTS`.

The CSV includes fields such as:

```text
query
title
authors
year
publication_summary
snippet
link
pdf_link
cited_by_count
cited_by_link
result_id
date_collected
citations_per_year
```

### 2. Add Abstracts To The CSV

Run the abstract extractor:

```bash
python abstract_extractor.py --input scholar_results.csv
```

By default, this updates `scholar_results.csv` in place and adds or updates two columns:

```text
abstract
abstract_extraction_status
```

To preserve the original CSV:

```bash
python abstract_extractor.py \
  --input scholar_results.csv \
  --output scholar_results_with_abstracts.csv
```

To process only the first few rows:

```bash
python abstract_extractor.py --input scholar_results.csv --limit 5
```

To replace existing abstract cells:

```bash
python abstract_extractor.py --input scholar_results.csv --overwrite-abstracts
```

Current CSV extraction path:

```text
CSV row
→ pdf_link, falling back to link
→ PDF downloaded in memory
→ PyMuPDF text extraction
→ regex Abstract-to-Introduction fallback
→ abstract column written to CSV
```

The CSV workflow does not save PDFs, figures, tables, JSON, or extra columns.

The `abstract_extraction_status` column records what happened for each row:

```text
ok
skip
download_failed
extract_failed
not_found
```

### 3. Extract Full Paper Context

Run the full paper extractor:

```bash
python full_paper_extractor.py --input scholar_results.csv --output-dir processed_papers
```

To process only the first few rows:

```bash
python full_paper_extractor.py --input scholar_results.csv --output-dir processed_papers --limit 5
```

This program does not modify the Scholar CSV. It creates one folder per paper:

```text
processed_papers/
├── manifest.json
└── <paper_id>/
    ├── paper.json
    ├── paper.md
    ├── paper.pdf
    ├── paper.tei.xml
    ├── source_metadata.json
    └── fulltext.txt
```

`paper.json` is the canonical structured output for each paper. It includes source metadata fields, abstract text and status, GROBID-derived introduction/conclusion sections, output paths, and extraction errors.

For abstracts, the full extractor checks the CSV first:

```text
CSV abstract populated
→ use that value
→ abstract_extraction_status = csv

CSV abstract empty
→ extract abstract from the downloaded PDF with GROBID
→ abstract_extraction_status = grobid
```

Full extractor abstract status values are:

```text
csv
grobid
grobid_failed
not_found
```

## GROBID

GROBID is a separate service for parsing scholarly PDFs into structured TEI XML. It is not started by this Python project automatically.

In this project, GROBID is used by the full paper extractor for missing abstracts and richer context. The abstract CSV updater still uses the lighter PyMuPDF path. GROBID helpers can extract:

```text
PDF
→ GROBID /api/processFulltextDocument
→ TEI XML
→ abstract when the CSV value is empty
→ introduction/conclusion sections
```

The abstract CSV updater does not use GROBID. The full paper extractor uses GROBID for missing abstracts and sections.

### Run GROBID With Docker

For most local CPU testing, use the lightweight CRF image:

```bash
docker pull grobid/grobid:0.9.0-crf
docker run --rm --init --ulimit core=0 -p 8070:8070 grobid/grobid:0.9.0-crf
```

For the full image:

```bash
docker pull grobid/grobid:0.9.0-full
docker run --rm --init --ulimit core=0 -p 8070:8070 grobid/grobid:0.9.0-full
```

If you have a Linux GPU setup and want Docker to expose it:

```bash
docker run --rm --gpus all --init --ulimit core=0 -p 8070:8070 grobid/grobid:0.9.0-full
```

GROBID will be available at:

```text
http://localhost:8070
```

The endpoint used by this project is:

```text
http://localhost:8070/api/processFulltextDocument
```

Official docs:

- GROBID repository: https://github.com/grobidOrg/grobid
- Docker instructions: https://grobid.readthedocs.io/en/latest/Grobid-docker/
- REST API docs: https://grobid.readthedocs.io/en/latest/Grobid-service/

## Common Issues

### Missing `SERPAPI_KEY`

Create `.env`:

```bash
SERPAPI_KEY=your_serpapi_key_here
```

### GROBID Connection Error

If you see a connection error for `localhost:8070`, GROBID is not reachable. Start Docker first:

```bash
docker run --rm --init --ulimit core=0 -p 8070:8070 grobid/grobid:0.9.0-crf
```

### No PDF Link

SerpAPI does not always return a `pdf_link`. The extractor tries `pdf_link` first and then tries `link`, but some links point to HTML pages, paywalls, or publisher landing pages instead of PDFs.

### No Abstract Found

For the abstract CSV updater, PDF text order can be messy because it uses a PyMuPDF regex search. For the full paper extractor, missing CSV abstracts require GROBID to be reachable.
