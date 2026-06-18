# SLR Agent

SLR Agent is a small Python workflow for collecting Google Scholar metadata with
SerpAPI, enriching the CSV with abstracts, and optionally extracting fuller paper
context with GROBID.

## Project Structure

```text
.
├── README.md
├── requirements.txt
├── outputs/
│   └── .gitkeep
└── src/
    ├── scholar_search.py
    ├── abstract_extractor.py
    ├── full_paper_extractor.py
    ├── output_utils.py
    └── pdf_utils.py
```

- `src/scholar_search.py` searches Google Scholar through SerpAPI and writes a
  deduplicated CSV.
- `src/abstract_extractor.py` reads a Scholar CSV, downloads PDFs from
  `pdf_link` or `link`, extracts abstracts with PyMuPDF, and writes abstract
  columns back to the CSV.
- `src/full_paper_extractor.py` reads a Scholar CSV and writes richer per-paper
  files such as JSON, Markdown, PDF, TEI XML, and full text.
- `src/output_utils.py` centralizes the default `outputs/` path handling.
- `src/pdf_utils.py` contains shared PDF URL selection and download helpers used
  by both extractors.

Generated files are written under `outputs/` by default. The directory is kept
in git with `outputs/.gitkeep`, while generated content inside it is ignored.

## Setup

Create a virtual environment and install dependencies:

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

### 1. Search Google Scholar

Edit the search settings near the top of `src/scholar_search.py`:

```python
KEYWORDS = ["autonomous driving", "constraints"]
MAX_RESULTS = 60
```

Then run:

```bash
python src/scholar_search.py --mode append
```

Use overwrite mode when you want a fresh CSV:

```bash
python src/scholar_search.py --mode overwrite
```

By default this writes:

```text
outputs/scholar_results.csv
```

The search output includes fields such as `query`, `title`, `authors`, `year`,
`publication_summary`, `snippet`, `link`, `pdf_link`, `cited_by_count`,
`cited_by_link`, `result_id`, `date_collected`, and `citations_per_year`.

### 2. Add Abstracts To The CSV

Update the CSV in place:

```bash
python src/abstract_extractor.py --input outputs/scholar_results.csv
```

Write to a separate CSV instead:

```bash
python src/abstract_extractor.py \
  --input outputs/scholar_results.csv \
  --output scholar_results_with_abstracts.csv
```

Process only a few rows while testing:

```bash
python src/abstract_extractor.py --input outputs/scholar_results.csv --limit 5
```

Relative output filenames are written under `outputs/`, so the example above
writes `outputs/scholar_results_with_abstracts.csv`.

The abstract updater adds or updates:

```text
abstract
abstract_extraction_status
```

Status values are:

```text
ok
skip
download_failed
extract_failed
not_found
```

This CSV-only path does not save PDFs, figures, tables, JSON, or extra output
folders.

### 3. Extract Full Paper Context

Run the full extractor:

```bash
python src/full_paper_extractor.py \
  --input outputs/scholar_results.csv
```

Process only a few rows while testing:

```bash
python src/full_paper_extractor.py \
  --input outputs/scholar_results.csv \
  --limit 5
```

This command does not modify the Scholar CSV. It creates one folder per paper:

```text
outputs/processed_papers/
├── manifest.json
└── <paper_id>/
    ├── paper.json
    ├── paper.md
    ├── paper.pdf
    ├── paper.tei.xml
    ├── source_metadata.json
    └── fulltext.txt
```

For abstracts, the full extractor checks the CSV first. If the CSV abstract is
empty, it tries to extract one from GROBID output.

Full extractor abstract status values are:

```text
csv
grobid
grobid_failed
not_found
```

## GROBID

GROBID is a separate service used by `src/full_paper_extractor.py` for missing
abstracts and introduction/conclusion sections. It is not started by this
project automatically.

For local CPU testing, start the lightweight CRF image:

```bash
docker pull grobid/grobid:0.9.0-crf
docker run --rm --init --ulimit core=0 -p 8070:8070 grobid/grobid:0.9.0-crf
```

The endpoint used by this project is:

```text
http://localhost:8070/api/processFulltextDocument
```

You can override it:

```bash
python src/full_paper_extractor.py \
  --input outputs/scholar_results.csv \
  --grobid-url http://localhost:8070/api/processFulltextDocument
```

## Common Issues

### Missing `SERPAPI_KEY`

Create `.env` in the project root:

```bash
SERPAPI_KEY=your_serpapi_key_here
```

### GROBID Connection Error

If the full extractor cannot connect to `localhost:8070`, start GROBID first:

```bash
docker run --rm --init --ulimit core=0 -p 8070:8070 grobid/grobid:0.9.0-crf
```

### No PDF Link

SerpAPI does not always return a `pdf_link`. The extractors try `pdf_link`
first and then `link`, but some links point to HTML pages, paywalls, or
publisher landing pages instead of PDFs.

### No Abstract Found

The abstract CSV updater uses PyMuPDF and a heading-based text search, so messy
PDF text order can prevent extraction. The full paper extractor needs GROBID to
be reachable when the CSV abstract is empty.
