import mimetypes
from urllib.parse import urlparse

import requests


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


def is_probably_pdf(response: requests.Response, url: str) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    path = urlparse(response.url or url).path.lower()
    return (
        "application/pdf" in content_type
        or path.endswith(".pdf")
        or response.content.startswith(b"%PDF")
    )


def candidate_pdf_urls(row: dict[str, str]) -> list[str]:
    urls = []
    for key in ("pdf_link", "link"):
        value = (row.get(key) or "").strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def download_pdf_bytes(row: dict[str, str], timeout: int) -> tuple[bytes | None, str | None]:
    headers = {"User-Agent": USER_AGENT}
    errors = []

    for url in candidate_pdf_urls(row):
        try:
            response = requests.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=timeout,
            )
            response.raise_for_status()

            if not is_probably_pdf(response, url):
                guessed_type = mimetypes.guess_type(response.url or url)[0]
                errors.append(
                    f"{url} did not look like a PDF"
                    + (f" ({guessed_type})" if guessed_type else "")
                )
                continue

            return response.content, None
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")

    if not errors:
        errors.append("no pdf_link or link found")

    return None, "; ".join(errors)

