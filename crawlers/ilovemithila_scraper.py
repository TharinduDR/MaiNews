#!/usr/bin/env python3
"""
News scraper for https://www.ilovemithila.com/  (a WordPress site).

For every news article it produces one JSON file containing:
    {
        "date":         "<ISO publish date>",
        "author":       "<author name>",
        "headline":     "<article title>",
        "news_content": "<plain-text article body>",
        "url":          "<source url>"        # added for traceability
    }

Two collection strategies are supported:

  1. WordPress REST API  (default, fast & clean)
        GET /wp-json/wp/v2/posts?per_page=100&page=N&_embed
     Returns title, content, date and (embedded) author for every post.
     This is the most reliable way to get *all* articles.

  2. HTML scraping (fallback, --method html)
        Article URLs are discovered from the XML sitemaps, then each page
        is fetched and parsed.  Fields come from the JSON-LD block the site
        embeds (Yoast SEO), with HTML-selector fallbacks.

The HTML parsing functions were validated offline against saved pages of
the site; the REST path is preferred because it avoids per-page parsing.

Usage
-----
    python ilovemithila_scraper.py                 # REST API, all posts
    python ilovemithila_scraper.py --method html   # sitemap + HTML parse
    python ilovemithila_scraper.py --out articles   # output directory
    python ilovemithila_scraper.py --limit 20       # stop after 20 (testing)
    python ilovemithila_scraper.py --delay 1.0      # seconds between requests

Dependencies:  requests, beautifulsoup4, lxml
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.ilovemithila.com"
API_POSTS = BASE + "/wp-json/wp/v2/posts"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ilovemithila-scraper/1.0; "
        "+research) Python-requests"
    )
}

# Elements that sometimes live *inside* the article body but are not part of
# the news text (related-posts widgets, share buttons, ads, etc.).
JUNK_SELECTORS = [
    ".mag-box", ".mini-posts-box", ".related-posts", ".post-bottom-meta",
    ".sharedaddy", ".addtoany_share_save_container", ".wp-block-buttons",
    "script", "style", "ins", "iframe", ".code-block", ".heateor_sss_sharing_container",
]


# --------------------------------------------------------------------------- #
#  Shared helpers
# --------------------------------------------------------------------------- #
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def clean_text(raw_html: str) -> str:
    """Turn an HTML fragment into clean, paragraph-separated plain text."""
    soup = BeautifulSoup(raw_html, "lxml")
    for sel in JUNK_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    # Use block-level newlines, then collapse excess blank lines.
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def slugify(url: str) -> str:
    """Derive a safe filename from an article URL."""
    path = urlparse(url).path.strip("/")
    slug = path.split("/")[-1] if path else "index"
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", slug)
    return slug or "article"


def save_article(article: dict, out_dir: str) -> str:
    fname = slugify(article["url"]) + ".json"
    fpath = os.path.join(out_dir, fname)
    with open(fpath, "w", encoding="utf-8") as fh:
        json.dump(article, fh, ensure_ascii=False, indent=2)
    return fpath


# --------------------------------------------------------------------------- #
#  Strategy 1 — WordPress REST API
# --------------------------------------------------------------------------- #
def scrape_via_api(session, out_dir, limit=None, delay=0.5):
    saved = 0
    page = 1
    per_page = 100
    while True:
        params = {"per_page": per_page, "page": page, "_embed": "1"}
        resp = session.get(API_POSTS, params=params, timeout=30)

        # WordPress returns 400 once you page past the last page.
        if resp.status_code == 400:
            break
        resp.raise_for_status()

        posts = resp.json()
        if not posts:
            break

        total_pages = resp.headers.get("X-WP-TotalPages")
        for post in posts:
            article = parse_api_post(post)
            fpath = save_article(article, out_dir)
            saved += 1
            print(f"[{saved}] {article['headline'][:60]!r} -> {os.path.basename(fpath)}")
            if limit and saved >= limit:
                print(f"\nReached limit of {limit}. Stopping.")
                return saved

        print(f"  ...finished API page {page}"
              + (f" of {total_pages}" if total_pages else ""))
        if total_pages and page >= int(total_pages):
            break
        page += 1
        time.sleep(delay)

    return saved


def parse_api_post(post: dict) -> dict:
    title = html_lib.unescape(post.get("title", {}).get("rendered", "")).strip()
    content_html = post.get("content", {}).get("rendered", "")
    date = post.get("date_gmt") or post.get("date", "")

    author = ""
    embedded = post.get("_embedded", {})
    authors = embedded.get("author") if isinstance(embedded, dict) else None
    if authors and isinstance(authors, list) and authors:
        author = authors[0].get("name", "") or ""
    author = html_lib.unescape(author).strip()

    return {
        "date": date,
        "author": author,
        "headline": title,
        "news_content": clean_text(content_html),
        "url": post.get("link", ""),
    }


# --------------------------------------------------------------------------- #
#  Strategy 2 — Sitemap discovery + HTML parsing (fallback)
# --------------------------------------------------------------------------- #
def discover_urls_from_sitemap(session):
    """Collect post URLs from the site's XML sitemap index."""
    candidates = [
        BASE + "/sitemap_index.xml",
        BASE + "/sitemap.xml",
        BASE + "/wp-sitemap.xml",
    ]
    seen = set()
    urls = []

    def fetch_xml(u):
        try:
            r = session.get(u, timeout=30)
            if r.status_code == 200 and "xml" in r.headers.get("Content-Type", "") + r.text[:100]:
                return r.text
        except requests.RequestException:
            pass
        return None

    index_xml = None
    for c in candidates:
        index_xml = fetch_xml(c)
        if index_xml:
            print(f"Using sitemap: {c}")
            break
    if not index_xml:
        print("No sitemap found; cannot discover URLs via HTML method.", file=sys.stderr)
        return urls

    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", index_xml)
    # Sub-sitemaps that likely contain posts.
    sub_sitemaps = [l for l in locs if l.endswith(".xml") and
                    ("post" in l or "sitemap" in l)]
    if not sub_sitemaps:                       # flat sitemap (URLs directly)
        sub_sitemaps = []
        urls.extend(locs)

    for sm in sub_sitemaps:
        xml = fetch_xml(sm)
        if not xml:
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml):
            if loc.endswith(".xml"):
                continue
            urls.append(loc)
        time.sleep(0.3)

    # Drop obvious non-article pages and dedupe while preserving order.
    skip = ("/about", "/contact", "/disclaimer", "/privacy", "/category/",
            "/tag/", "/author/", "/page/")
    cleaned = []
    for u in urls:
        if any(s in u for s in skip):
            continue
        if u in seen:
            continue
        seen.add(u)
        cleaned.append(u)
    return cleaned


def parse_article_html(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text, "lxml")

    headline = date = author = ""

    # --- Preferred: Yoast JSON-LD graph ---------------------------------- #
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
            if "Article" in str(ntype):
                headline = headline or node.get("headline", "")
                date = date or node.get("datePublished", "")
                a = node.get("author")
                if isinstance(a, dict):
                    author = author or a.get("name", "")
        # Resolve author reference held in a Person node, if needed.
        if not author:
            for node in nodes:
                if isinstance(node, dict) and node.get("@type") == "Person":
                    author = node.get("name", "")
                    break
        if headline and date and author:
            break

    # --- Fallbacks via meta tags / DOM ----------------------------------- #
    if not headline:
        m = soup.find("meta", property="og:title")
        headline = (m["content"] if m and m.get("content") else "")
    if not headline:
        h1 = soup.select_one("h1.entry-title") or soup.find("h1")
        headline = h1.get_text(strip=True) if h1 else ""

    if not date:
        m = soup.find("meta", property="article:published_time")
        date = (m["content"] if m and m.get("content") else "")

    if not author:
        a = soup.select_one("a[rel=author], .author-name, .meta-author")
        author = a.get_text(strip=True) if a else ""

    # --- Body ------------------------------------------------------------ #
    body_el = soup.select_one(".entry-content")
    news_content = clean_text(str(body_el)) if body_el else ""

    return {
        "date": html_lib.unescape(date).strip(),
        "author": html_lib.unescape(author).strip(),
        "headline": html_lib.unescape(headline).strip(),
        "news_content": news_content,
        "url": url,
    }


def scrape_via_html(session, out_dir, limit=None, delay=0.5):
    urls = discover_urls_from_sitemap(session)
    print(f"Discovered {len(urls)} candidate article URLs.\n")
    saved = 0
    for url in urls:
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  ! skip {url}: {e}", file=sys.stderr)
            continue
        article = parse_article_html(r.text, url)
        if not article["news_content"]:
            continue  # not an article page (no body text)
        fpath = save_article(article, out_dir)
        saved += 1
        print(f"[{saved}] {article['headline'][:60]!r} -> {os.path.basename(fpath)}")
        if limit and saved >= limit:
            print(f"\nReached limit of {limit}. Stopping.")
            break
        time.sleep(delay)
    return saved


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Scrape ilovemithila.com news articles to JSON.")
    ap.add_argument("--method", choices=["api", "html"], default="api",
                    help="Collection strategy (default: api).")
    ap.add_argument("--out", default="articles", help="Output directory.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop after N articles (for testing).")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="Seconds to wait between requests (be polite).")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    session = make_session()

    print(f"Method : {args.method}\nOutput : {os.path.abspath(args.out)}\n")
    if args.method == "api":
        try:
            n = scrape_via_api(session, args.out, args.limit, args.delay)
        except requests.RequestException as e:
            print(f"\nREST API failed ({e}). Falling back to HTML scraping...\n",
                  file=sys.stderr)
            n = scrape_via_html(session, args.out, args.limit, args.delay)
    else:
        n = scrape_via_html(session, args.out, args.limit, args.delay)

    print(f"\nDone. Saved {n} article(s) to {os.path.abspath(args.out)}/")


if __name__ == "__main__":
    main()