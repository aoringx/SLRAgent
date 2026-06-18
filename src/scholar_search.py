import argparse
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from output_utils import DEFAULT_OUTPUT_DIR, ensure_parent_dir, resolve_output_path

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY")

KEYWORDS = ["autonomous driving", "constraints"]
QUERY = " + ".join(KEYWORDS)

MAX_RESULTS = 20


def parse_year(publication_info: dict) -> int | None:
    summary = publication_info.get("summary", "")

    for token in reversed(summary.replace(",", " ").split()):
        if token.isdigit() and len(token) == 4:
            year = int(token)
            if 1800 <= year <= datetime.now().year + 1:
                return year

    return None


def parse_authors(publication_info: dict) -> str:
    authors = publication_info.get("authors", [])

    if isinstance(authors, list) and authors:
        return "; ".join(
            author.get("name", "") for author in authors if author.get("name")
        )

    summary = publication_info.get("summary", "")

    if " - " in summary:
        return summary.split(" - ")[0]

    return ""


def parse_pdf_link(result: dict) -> str:
    resources = result.get("resources", [])

    for resource in resources:
        if resource.get("file_format", "").lower() == "pdf":
            return resource.get("link", "")

    return ""


def normalize_title(title: str) -> str:
    """
    Normalize titles so deduplication catches small formatting differences.
    """
    if not isinstance(title, str):
        return ""

    return (
        title.lower()
        .strip()
        .replace("[html]", "")
        .replace("[pdf]", "")
        .replace("[citation]", "")
        .replace(":", "")
        .replace("-", " ")
    )


def get_serpapi_key() -> str:
    if not SERPAPI_KEY:
        raise RuntimeError(
            "Missing SERPAPI_KEY. Put it in a .env file or environment variable."
        )
    return SERPAPI_KEY


def google_scholar_search(query: str, max_results: int = 50, sleep_seconds: float = 1.0):
    collected = []
    start = 0
    serpapi_key = get_serpapi_key()

    while len(collected) < max_results:
        params = {
            "engine": "google_scholar",
            "q": query,
            "api_key": serpapi_key,
            "start": start,
            "num": 20,
        }

        response = requests.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        results = data.get("organic_results", [])

        if not results:
            break

        for rank_on_page, result in enumerate(results, start=1):
            if len(collected) >= max_results:
                break

            publication_info = result.get("publication_info", {})
            cited_by = result.get("inline_links", {}).get("cited_by", {})

            paper = {
                "query": query,
                "title": result.get("title", ""),
                "authors": parse_authors(publication_info),
                "year": parse_year(publication_info),
                "publication_summary": publication_info.get("summary", ""),
                "snippet": result.get("snippet", ""),
                "link": result.get("link", ""),
                "pdf_link": parse_pdf_link(result),
                "cited_by_count": cited_by.get("total", ""),
                "cited_by_link": cited_by.get("link", ""),
                "result_id": result.get("result_id", ""),
                "date_collected": datetime.now().strftime("%Y-%m-%d"),
            }

            collected.append(paper)

        start += 20
        time.sleep(sleep_seconds)

    return collected


def add_citations_per_year(df: pd.DataFrame) -> pd.DataFrame:
    current_year = datetime.now().year

    def citations_per_year(row):
        try:
            year = int(row["year"])
            citations = int(row["cited_by_count"])
            age = max(current_year - year + 1, 1)
            return round(citations / age, 2)
        except Exception:
            return ""

    df["citations_per_year"] = df.apply(citations_per_year, axis=1)
    return df


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate in this order:
    1. Prefer Google Scholar result_id if available.
    2. Otherwise deduplicate by normalized title.
    3. Otherwise deduplicate by link.
    """

    df = df.copy()

    df["normalized_title"] = df["title"].apply(normalize_title)

    # Keep rows with result_id, title, and link as deduplication keys.
    # Empty strings should not accidentally collapse unrelated rows.
    df["result_id_key"] = df["result_id"].fillna("").astype(str).str.strip()
    df["link_key"] = df["link"].fillna("").astype(str).str.strip()

    # First deduplicate by result_id when it exists
    has_result_id = df[df["result_id_key"] != ""]
    no_result_id = df[df["result_id_key"] == ""]

    has_result_id = has_result_id.drop_duplicates(
        subset=["result_id_key"],
        keep="first",
    )

    # Then deduplicate remaining rows by normalized title
    no_result_id = no_result_id.drop_duplicates(
        subset=["normalized_title"],
        keep="first",
    )

    combined = pd.concat([has_result_id, no_result_id], ignore_index=True)

    # Final dedupe by link if available
    has_link = combined[combined["link_key"] != ""]
    no_link = combined[combined["link_key"] == ""]

    has_link = has_link.drop_duplicates(
        subset=["link_key"],
        keep="first",
    )

    final_df = pd.concat([has_link, no_link], ignore_index=True)

    final_df = final_df.drop(
        columns=["normalized_title", "result_id_key", "link_key"],
        errors="ignore",
    )

    final_df = final_df.reset_index(drop=True)

    return final_df


def save_results(new_papers, output_file: str | Path, mode: str):
    output_file = ensure_parent_dir(output_file)
    new_df = pd.DataFrame(new_papers)

    if new_df.empty:
        print("No new papers found.")
        return new_df

    if mode == "append" and output_file.exists():
        old_df = pd.read_csv(output_file)
        combined_df = pd.concat([old_df, new_df], ignore_index=True)
        print(f"Loaded existing CSV with {len(old_df)} rows.")
    else:
        combined_df = new_df
        if mode == "overwrite":
            print("Overwrite mode: creating a new CSV.")
        else:
            print("Append mode selected, but no existing CSV found. Creating a new CSV.")

    before_dedup = len(combined_df)

    combined_df = add_citations_per_year(combined_df)
    combined_df = deduplicate(combined_df)

    after_dedup = len(combined_df)
    duplicates_removed = before_dedup - after_dedup

    combined_df.to_csv(output_file, index=False, encoding="utf-8-sig")

    print(f"Saved {after_dedup} unique papers to {output_file}")
    print(f"Removed {duplicates_removed} duplicate rows.")

    return combined_df


def main():
    parser = argparse.ArgumentParser(
        description="Search Google Scholar and save results to CSV."
    )

    parser.add_argument(
        "--mode",
        choices=["overwrite", "append"],
        default="append",
        help="Use 'overwrite' to create a new CSV, or 'append' to add to an existing CSV and deduplicate.",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="scholar_results.csv",
        help="Output CSV filename. Relative paths are written under --output-dir.",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated output files.",
    )

    args = parser.parse_args()

    papers = google_scholar_search(
        query=QUERY,
        max_results=MAX_RESULTS,
    )

    df = save_results(
        new_papers=papers,
        output_file=resolve_output_path(args.output, args.output_dir),
        mode=args.mode,
    )

    print()
    print(f"Query: {QUERY}")
    print(f"Mode: {args.mode}")
    print(f"Max results: {MAX_RESULTS}")
    print(f"Output file: {resolve_output_path(args.output, args.output_dir)}")
    print()
    print(df[["title", "year", "cited_by_count", "citations_per_year"]].head(10))


if __name__ == "__main__":
    main()
