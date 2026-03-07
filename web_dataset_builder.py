#!/usr/bin/env python3
"""Crawl a website and build a clean text dataset."""

from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

MAX_PAGES = 500
REQUEST_TIMEOUT = 10
OUTPUT_FILE = "dataset.txt"
SEPARATOR = "\n---------------------------------------\n\n"


def normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and standardizing path/query."""
    clean, _ = urldefrag(url)
    parsed = urlparse(clean)

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    return parsed._replace(path=path).geturl()


def is_internal_link(link: str, domain: str) -> bool:
    """Return True if link belongs to the same domain and uses HTTP(S)."""
    parsed = urlparse(link)
    return parsed.scheme in {"http", "https"} and parsed.netloc == domain


def extract_visible_text(html: str) -> str:
    """Extract visible text, removing non-content page sections."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove obvious non-content blocks.
    for tag in soup(["script", "style", "nav", "footer", "noscript", "header", "aside", "form"]):
        tag.decompose()

    # Remove likely menu/navigation blocks by class or id patterns.
    menu_keywords = ("menu", "nav", "navbar", "footer", "header", "sidebar", "breadcrumb")
    for element in soup.find_all(attrs={"class": True}):
        classes = " ".join(element.get("class", [])).lower()
        if any(keyword in classes for keyword in menu_keywords):
            element.decompose()

    for element in soup.find_all(attrs={"id": True}):
        element_id = (element.get("id") or "").lower()
        if any(keyword in element_id for keyword in menu_keywords):
            element.decompose()

    # Focus on main body text if available.
    root = soup.body or soup
    lines = [line.strip() for line in root.stripped_strings]

    return "\n".join(line for line in lines if line)


def crawl_website(start_url: str, max_pages: int = MAX_PAGES) -> list[tuple[str, str]]:
    """Crawl internal pages and return (url, clean_text) tuples."""
    normalized_start = normalize_url(start_url)
    domain = urlparse(normalized_start).netloc

    visited: set[str] = set()
    queue = deque([normalized_start])
    dataset: list[tuple[str, str]] = []

    while queue and len(visited) < max_pages:
        current_url = queue.popleft()

        if current_url in visited:
            continue

        visited.add(current_url)
        print(f"[Progress] Crawling {len(visited)}/{max_pages}: {current_url}")

        try:
            response = requests.get(current_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"[Warning] Failed to fetch {current_url}: {error}")
            continue

        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            print(f"[Info] Skipping non-HTML page: {current_url}")
            continue

        text = extract_visible_text(response.text)
        if text:
            dataset.append((current_url, text))

        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue

            absolute_url = normalize_url(urljoin(current_url, href))
            if is_internal_link(absolute_url, domain) and absolute_url not in visited:
                queue.append(absolute_url)

    return dataset


def save_dataset(dataset: list[tuple[str, str]], output_file: str = OUTPUT_FILE) -> None:
    """Save crawled text dataset to disk in requested structured TXT format."""
    with open(output_file, "w", encoding="utf-8") as file:
        for url, text in dataset:
            file.write(f"URL: {url}\n\n{text}{SEPARATOR}")



def main() -> None:
    start_url = input("Paste start URL: ").strip()
    if not start_url:
        print("[Error] No URL provided.")
        return

    if not urlparse(start_url).scheme:
        start_url = f"https://{start_url}"

    print("[Info] Starting crawl...")
    dataset = crawl_website(start_url, max_pages=MAX_PAGES)
    save_dataset(dataset, output_file=OUTPUT_FILE)
    print(f"[Done] Saved {len(dataset)} pages to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
