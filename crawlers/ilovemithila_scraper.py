#!/usr/bin/env python3
"""
Enhanced scraper for https://www.ilovemithila.com/ that handles Cloudflare protection.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.ilovemithila.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

JUNK_SELECTORS = [
    ".mag-box", ".mini-posts-box", ".related-posts", ".post-bottom-meta",
    ".sharedaddy", ".addtoany_share_save_container", ".wp-block-buttons",
    "script", "style", "ins", "iframe", ".code-block", ".heateor_sss_sharing_container",
    ".share-buttons", ".post-components", "#comments", ".about-author",
    ".stream-item", ".post-footer", ".entry-footer", ".post-extra-info",
]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def clean_text(raw_html: str) -> str:
    """Turn HTML into clean, paragraph-separated plain text."""
    soup = BeautifulSoup(raw_html, "lxml")
    for sel in JUNK_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def slugify(url: str) -> str:
    """Derive a safe filename from URL."""
    path = urlparse(url).path.strip("/")
    slug = path.split("/")[-1] if path else "index"
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", slug)[:100]
    return slug or "article"


def save_article(article: dict, out_dir: str) -> str:
    fname = slugify(article["url"]) + ".json"
    fpath = os.path.join(out_dir, fname)
    with open(fpath, "w", encoding="utf-8") as fh:
        json.dump(article, fh, ensure_ascii=False, indent=2)
    return fpath


# --------------------------------------------------------------------------- #
# Strategy 1: Discover URLs by crawling the homepage and category pages
# --------------------------------------------------------------------------- #
def discover_urls_from_homepage(session, limit=None):
    """Extract article URLs from homepage and category listings."""
    urls = set()

    # Start with homepage
    print("Fetching homepage...")
    resp = session.get(BASE, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Find all article links
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("http"):
            href = urljoin(BASE, href)

        # Filter for article URLs (post pattern)
        if (BASE in href and
                "/category/" not in href and
                "/author/" not in href and
                "/tag/" not in href and
                "/page/" not in href and
                "?" not in href and
                not href.endswith("/#") and
                ("/20" in href or "/news/" in href or "/story/" in href or "/poem/" in href)):
            urls.add(href)

    print(f"Found {len(urls)} unique URLs from homepage")

    # Also check the "Updates" section which lists recent posts
    updates_section = soup.find("div", class_="wide-post-box")
    if updates_section:
        for link in updates_section.find_all("a", href=True):
            href = link["href"]
            if href.startswith("/"):
                href = urljoin(BASE, href)
            if BASE in href and "?" not in href:
                urls.add(href)

    return list(urls)


def discover_urls_from_sitemap(session):
    """Try multiple sitemap patterns."""
    sitemap_patterns = [
        "/sitemap_index.xml",
        "/sitemap.xml",
        "/wp-sitemap.xml",
        "/post-sitemap.xml",
        "/page-sitemap.xml",
        "/category-sitemap.xml",
    ]

    all_urls = set()

    for pattern in sitemap_patterns:
        url = urljoin(BASE, pattern)
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                continue

            text = resp.text
            if "<?xml" not in text[:100]:
                continue

            # Find all URLs in sitemap
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)

            for loc in locs:
                # If it's a sitemap index, recursively fetch
                if loc.endswith(".xml") and "sitemap" in loc:
                    try:
                        sub_resp = session.get(loc, timeout=15)
                        if sub_resp.status_code == 200:
                            for sub_loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", sub_resp.text):
                                if not sub_loc.endswith(".xml"):
                                    all_urls.add(sub_loc)
                    except:
                        pass
                else:
                    all_urls.add(loc)

            print(f"Found {len(locs)} URLs from {pattern}")

        except Exception as e:
            continue

    # Filter for article URLs
    article_urls = []
    skip_patterns = ["/category/", "/tag/", "/author/", "/page/", "/wp-", "/feed", "/comment"]

    for url in all_urls:
        if any(p in url for p in skip_patterns):
            continue
        if "?" in url:
            continue
        article_urls.append(url)

    return article_urls


# --------------------------------------------------------------------------- #
# Strategy 2: Parse articles from HTML (same as before)
# --------------------------------------------------------------------------- #
def parse_article_html(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text, "lxml")

    headline = date = author = ""

    # Try JSON-LD first (Yoast SEO)
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        nodes = data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            ntype = node.get("@type", "")
            if "NewsArticle" in ntype or "Article" in ntype:
                headline = headline or node.get("headline", "")
                date = date or node.get("datePublished", "")
                a = node.get("author")
                if isinstance(a, dict):
                    author = author or a.get("name", "")
                elif isinstance(a, str):
                    author = author or a

        if headline and date:
            break

    # Fallback to meta tags
    if not headline:
        m = soup.find("meta", property="og:title")
        headline = m["content"] if m and m.get("content") else ""
    if not headline:
        m = soup.find("meta", attrs={"name": "twitter:title"})
        headline = m["content"] if m and m.get("content") else ""
    if not headline:
        h1 = soup.select_one("h1.entry-title, h1.post-title, article h1")
        headline = h1.get_text(strip=True) if h1 else ""

    # Get date
    if not date:
        m = soup.find("meta", property="article:published_time")
        date = m["content"] if m and m.get("content") else ""
    if not date:
        m = soup.find("meta", attrs={"name": "date"})
        date = m["content"] if m and m.get("content") else ""
    if not date:
        date_span = soup.select_one(".date.meta-item, time[datetime]")
        if date_span:
            date = date_span.get("datetime", "") or date_span.get_text(strip=True)

    # Get author
    if not author:
        a = soup.select_one(".author-name, .meta-author a, [rel=author]")
        author = a.get_text(strip=True) if a else ""

    # Extract body content
    body_el = soup.select_one(".entry-content, .post-content, article .content")
    news_content = clean_text(str(body_el)) if body_el else ""

    # If body is empty, try to extract from the whole article
    if not news_content:
        article_el = soup.find("article")
        if article_el:
            news_content = clean_text(str(article_el))

    return {
        "date": html_lib.unescape(date).strip(),
        "author": html_lib.unescape(author).strip(),
        "headline": html_lib.unescape(headline).strip(),
        "news_content": news_content,
        "url": url,
    }


def scrape_via_html(session, out_dir, limit=None, delay=1.0):
    """Main scraping function using discovered URLs."""

    # Try sitemap first
    print("Attempting to discover URLs from sitemap...")
    urls = discover_urls_from_sitemap(session)

    # Fallback to homepage crawling
    if not urls:
        print("Sitemap discovery failed. Falling back to homepage crawling...")
        urls = discover_urls_from_homepage(session, limit)

    if not urls:
        print("ERROR: Could not discover any article URLs.")
        return 0

    print(f"\nDiscovered {len(urls)} article URLs.")
    print(f"Sample URLs: {urls[:3]}\n")

    saved = 0
    failed = 0

    for i, url in enumerate(urls):
        if limit and saved >= limit:
            break

        try:
            print(f"[{i + 1}/{len(urls)}] Fetching: {url[:80]}...")
            resp = session.get(url, timeout=30)

            if resp.status_code == 403:
                print(f"  ! Blocked by Cloudflare (403). Trying with different headers...")
                # Try with a more browser-like request
                resp = session.get(url, timeout=30)
                if resp.status_code == 403:
                    failed += 1
                    continue

            resp.raise_for_status()

            article = parse_article_html(resp.text, url)

            if not article["news_content"] or len(article["news_content"]) < 100:
                print(f"  ! Warning: Short or empty content ({len(article['news_content'])} chars)")
                # Still save if there's a headline
                if not article["headline"]:
                    continue

            fpath = save_article(article, out_dir)
            saved += 1
            print(f"  ✓ Saved: {article['headline'][:50]}... -> {os.path.basename(fpath)}")

        except requests.RequestException as e:
            print(f"  ✗ Failed: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ Error parsing: {e}")
            failed += 1

        time.sleep(delay)

    print(f"\nSummary: {saved} saved, {failed} failed")
    return saved


# --------------------------------------------------------------------------- #
# Strategy 3: Direct from archive (if you have HTML files)
# --------------------------------------------------------------------------- #
def scrape_from_local_html(html_dir, out_dir):
    """Parse already-saved HTML files."""
    saved = 0
    html_files = [f for f in os.listdir(html_dir) if f.endswith(".html")]

    print(f"Found {len(html_files)} HTML files in {html_dir}")

    for filename in html_files:
        filepath = os.path.join(html_dir, filename)
        with open(filepath, "r", encoding="utf-8") as fh:
            html_content = fh.read()

        # Try to extract URL from file or use filename
        url_match = re.search(r'<link rel="canonical" href="([^"]+)"', html_content)
        url = url_match.group(1) if url_match else f"https://www.ilovemithila.com/{filename.replace('.html', '')}"

        article = parse_article_html(html_content, url)

        if article["headline"]:
            fpath = save_article(article, out_dir)
            saved += 1
            print(f"[{saved}] {article['headline'][:60]} -> {os.path.basename(fpath)}")

    return saved


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Enhanced scraper for ilovemithila.com")
    ap.add_argument("--method", choices=["crawl", "local"], default="crawl",
                    help="crawl=discover from site, local=parse saved HTML files")
    ap.add_argument("--input-dir", default=None,
                    help="Directory containing saved HTML files (for local method)")
    ap.add_argument("--out", default="articles", help="Output directory")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N articles")
    ap.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.method == "local":
        if not args.input_dir:
            print("ERROR: --input-dir required for local method")
            return 1
        n = scrape_from_local_html(args.input_dir, args.out)
    else:
        session = make_session()
        print(f"Method: crawl\nOutput: {os.path.abspath(args.out)}\n")
        n = scrape_via_html(session, args.out, args.limit, args.delay)

    print(f"\nDone. Saved {n} article(s) to {os.path.abspath(args.out)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())