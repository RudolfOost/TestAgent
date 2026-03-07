diff --git a/web_dataset_builder.py b/web_dataset_builder.py
new file mode 100644
index 0000000000000000000000000000000000000000..7d41768ece16cc8c4cfdfc8ab6819616a906ebcf
--- /dev/null
+++ b/web_dataset_builder.py
@@ -0,0 +1,292 @@
+#!/usr/bin/env python3
+"""Desktop GUI app to crawl a website and build a clean text dataset."""
+
+from collections import deque
+import os
+import subprocess
+import sys
+from threading import Thread
+from urllib.parse import urldefrag, urljoin, urlparse
+
+from bs4 import BeautifulSoup
+from playwright.sync_api import Error as PlaywrightError
+from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
+from playwright.sync_api import sync_playwright
+import tkinter as tk
+from tkinter import messagebox
+from tkinter import ttk
+
+MAX_PAGES = 500
+REQUEST_TIMEOUT = 10
+MAX_QUEUE_SIZE = 5000
+OUTPUT_FILE = "dataset.txt"
+SEPARATOR = "\n---------------------------------------\n\n"
+SKIP_FILE_EXTENSIONS = (
+    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".rar", ".7z",
+    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".mp3", ".mp4", ".avi", ".mov",
+    ".wmv", ".mkv", ".exe", ".dmg", ".iso", ".css", ".js", ".json", ".xml", ".rss",
+)
+
+
+def normalize_url(url: str) -> str:
+    """Normalize URL by removing fragments/query and standardizing path."""
+    clean, _ = urldefrag(url)
+    parsed = urlparse(clean)
+
+    path = parsed.path or "/"
+    if path != "/" and path.endswith("/"):
+        path = path[:-1]
+
+    return parsed._replace(path=path, query="").geturl()
+
+
+def is_internal_link(link: str, domain: str) -> bool:
+    """Return True if link belongs to the same domain and uses HTTP(S)."""
+    parsed = urlparse(link)
+    return parsed.scheme in {"http", "https"} and parsed.netloc == domain
+
+
+def should_skip_url(url: str) -> bool:
+    """Return True when URL points to a likely non-HTML/static file."""
+    parsed = urlparse(url)
+    path = parsed.path.lower()
+    return path.endswith(SKIP_FILE_EXTENSIONS)
+
+
+def extract_visible_text(html: str) -> str:
+    """Extract visible text, removing non-content page sections."""
+    soup = BeautifulSoup(html, "html.parser")
+
+    for tag in soup(["script", "style", "nav", "footer", "noscript", "header", "aside", "form"]):
+        tag.decompose()
+
+    menu_keywords = ("menu", "nav", "navbar", "footer", "header", "sidebar", "breadcrumb")
+    for element in soup.find_all(attrs={"class": True}):
+        classes = " ".join(element.get("class", [])).lower()
+        if any(keyword in classes for keyword in menu_keywords):
+            element.decompose()
+
+    for element in soup.find_all(attrs={"id": True}):
+        element_id = (element.get("id") or "").lower()
+        if any(keyword in element_id for keyword in menu_keywords):
+            element.decompose()
+
+    root = soup.body or soup
+    lines = [line.strip() for line in root.stripped_strings]
+    return "\n".join(line for line in lines if line)
+
+
+def extract_internal_links(html: str, base_url: str, domain: str) -> list[str]:
+    """Extract and normalize internal links from rendered HTML."""
+    soup = BeautifulSoup(html, "html.parser")
+    links: list[str] = []
+
+    for anchor in soup.find_all("a", href=True):
+        href = anchor["href"].strip()
+        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
+            continue
+
+        absolute_url = normalize_url(urljoin(base_url, href))
+        if is_internal_link(absolute_url, domain):
+            links.append(absolute_url)
+
+    return links
+
+
+def crawl_website(start_url: str, max_pages: int = MAX_PAGES, progress_callback=None) -> list[tuple[str, str]]:
+    """Crawl internal pages with a queue and return (url, clean_text) tuples."""
+    normalized_start = normalize_url(start_url)
+    domain = urlparse(normalized_start).netloc
+
+    visited: set[str] = set()
+    queue = deque([normalized_start])
+    queued_urls: set[str] = {normalized_start}
+    dataset: list[tuple[str, str]] = []
+
+    with sync_playwright() as playwright:
+        browser = playwright.chromium.launch(headless=True)
+        page = browser.new_page()
+        page.set_default_navigation_timeout(REQUEST_TIMEOUT * 1000)
+
+        while queue and len(visited) < max_pages:
+            current_url = queue.popleft()
+
+            if current_url in visited:
+                continue
+
+            visited.add(current_url)
+            crawled_count = len(visited)
+            if progress_callback:
+                progress_callback(crawled_count, max_pages, f"Crawling {crawled_count} / {max_pages}: {current_url}")
+
+            if should_skip_url(current_url):
+                if progress_callback:
+                    progress_callback(crawled_count, max_pages, f"Skipping non-HTML URL: {current_url}")
+                continue
+
+            try:
+                response = page.goto(
+                    current_url,
+                    wait_until="networkidle",
+                    timeout=REQUEST_TIMEOUT * 1000,
+                )
+            except (PlaywrightTimeoutError, PlaywrightError) as error:
+                if progress_callback:
+                    progress_callback(crawled_count, max_pages, f"Warning: failed {current_url} ({error})")
+                continue
+
+            content_type = ""
+            if response:
+                content_type = (response.header_value("content-type") or "").lower()
+
+            if content_type and "text/html" not in content_type:
+                if progress_callback:
+                    progress_callback(crawled_count, max_pages, f"Skipping non-HTML page: {current_url}")
+                continue
+
+            rendered_html = page.content()
+            text = extract_visible_text(rendered_html)
+            if text:
+                dataset.append((current_url, text))
+
+            for discovered_url in extract_internal_links(rendered_html, current_url, domain):
+                if should_skip_url(discovered_url):
+                    continue
+
+                if discovered_url in visited or discovered_url in queued_urls:
+                    continue
+
+                if len(queue) >= MAX_QUEUE_SIZE:
+                    if progress_callback:
+                        progress_callback(
+                            crawled_count,
+                            max_pages,
+                            f"Queue limit reached ({MAX_QUEUE_SIZE}). Skipping new URLs.",
+                        )
+                    break
+
+                queue.append(discovered_url)
+                queued_urls.add(discovered_url)
+
+        browser.close()
+
+    return dataset
+
+
+def save_dataset(dataset: list[tuple[str, str]], output_file: str = OUTPUT_FILE) -> None:
+    """Save crawled text dataset to disk in requested structured TXT format."""
+    with open(output_file, "w", encoding="utf-8") as file:
+        for url, text in dataset:
+            file.write(f"URL: {url}\n\n{text}{SEPARATOR}")
+
+
+class DatasetCrawlerApp:
+    """Simple Tkinter desktop app for crawling websites into a dataset."""
+
+    def __init__(self, root: tk.Tk):
+        self.root = root
+        self.root.title("Website Text Dataset Builder")
+        self.root.geometry("760x240")
+
+        self.url_var = tk.StringVar()
+        self.status_var = tk.StringVar(value="Ready")
+        self.progress_var = tk.IntVar(value=0)
+
+        container = ttk.Frame(root, padding=14)
+        container.pack(fill="both", expand=True)
+
+        ttk.Label(container, text="Website URL:").pack(anchor="w")
+        self.url_entry = ttk.Entry(container, textvariable=self.url_var, width=96)
+        self.url_entry.pack(fill="x", pady=(4, 10))
+
+        button_row = ttk.Frame(container)
+        button_row.pack(fill="x", pady=(0, 10))
+
+        self.start_button = ttk.Button(button_row, text="Start Crawl", command=self.start_crawl)
+        self.start_button.pack(side="left")
+
+        self.open_button = ttk.Button(button_row, text="Open dataset.txt", command=self.open_dataset, state="disabled")
+        self.open_button.pack(side="left", padx=(10, 0))
+
+        self.progress_bar = ttk.Progressbar(
+            container,
+            mode="determinate",
+            maximum=MAX_PAGES,
+            variable=self.progress_var,
+        )
+        self.progress_bar.pack(fill="x", pady=(0, 10))
+
+        self.status_label = ttk.Label(container, textvariable=self.status_var, wraplength=720, justify="left")
+        self.status_label.pack(anchor="w")
+
+    def set_status(self, message: str) -> None:
+        self.root.after(0, lambda: self.status_var.set(message))
+
+    def update_progress(self, crawled: int, total: int, message: str) -> None:
+        def _update() -> None:
+            self.progress_bar.configure(maximum=total)
+            self.progress_var.set(min(crawled, total))
+            self.status_var.set(message)
+
+        self.root.after(0, _update)
+
+    def open_dataset(self) -> None:
+        if not os.path.exists(OUTPUT_FILE):
+            messagebox.showerror("Missing file", f"Could not find {OUTPUT_FILE}.")
+            return
+
+        try:
+            if sys.platform.startswith("win"):
+                os.startfile(OUTPUT_FILE)  # type: ignore[attr-defined]
+            elif sys.platform == "darwin":
+                subprocess.Popen(["open", OUTPUT_FILE])
+            else:
+                subprocess.Popen(["xdg-open", OUTPUT_FILE])
+        except Exception as error:  # noqa: BLE001
+            messagebox.showerror("Open failed", f"Could not open {OUTPUT_FILE}: {error}")
+
+    def start_crawl(self) -> None:
+        start_url = self.url_var.get().strip()
+        if not start_url:
+            messagebox.showerror("Missing URL", "Please enter a website URL.")
+            return
+
+        if not urlparse(start_url).scheme:
+            start_url = f"https://{start_url}"
+
+        self.start_button.config(state="disabled")
+        self.open_button.config(state="disabled")
+        self.progress_var.set(0)
+        self.set_status("Starting crawl...")
+
+        worker = Thread(target=self.run_crawl, args=(start_url,), daemon=True)
+        worker.start()
+
+    def run_crawl(self, start_url: str) -> None:
+        try:
+            dataset = crawl_website(start_url, max_pages=MAX_PAGES, progress_callback=self.update_progress)
+            save_dataset(dataset, output_file=OUTPUT_FILE)
+            self.root.after(0, lambda: self.status_var.set(f"Finished. Saved {len(dataset)} pages to {OUTPUT_FILE}"))
+            self.root.after(0, lambda: self.open_button.config(state="normal"))
+            self.root.after(
+                0,
+                lambda: messagebox.showinfo(
+                    "Crawl finished",
+                    f"Crawling complete. Saved {len(dataset)} pages to {OUTPUT_FILE}.",
+                ),
+            )
+        except Exception as error:  # noqa: BLE001
+            self.root.after(0, lambda: self.status_var.set(f"Error: {error}"))
+            self.root.after(0, lambda: messagebox.showerror("Crawl failed", str(error)))
+        finally:
+            self.root.after(0, lambda: self.start_button.config(state="normal"))
+
+
+def main() -> None:
+    root = tk.Tk()
+    DatasetCrawlerApp(root)
+    root.mainloop()
+
+
+if __name__ == "__main__":
+    main()
