#!/usr/bin/env python3
"""
News scraper for https://maithilijindabaad.com/  (a WordPress site).

Writes one JSON file per article:
    {"date":..., "author":..., "headline":..., "news_content":..., "url":...}

Permission status (checked before building)
-------------------------------------------
  * robots.txt is empty -> no Disallow, no AI opt-out, no content signals.
  * the REST API returns 301 (a redirect, which requests follows; NOT a block).
  * Cloudflare fronts the site but serves normal requests (no 403 challenge).
So this is ordinary, permitted access -- no circumvention. There is no
advertised crawl-delay, so the scraper defaults to a courteous 3s between
requests and sends a truthful, identifiable User-Agent.

Strategies
----------
  --method api    WordPress REST API /wp-json/wp/v2/posts  (default)
  --method html   sitemap discovery + parse `.post-content`  (fallback)

If the API redirect lands on something that isn't JSON, or returns 403,
the script falls back to the HTML method automatically.

Usage
-----
    python mjz_scraper.py --contact you@lancaster.ac.uk
    python mjz_scraper.py --limit 20 --contact you@x.edu
    python mjz_scraper.py --method html
    python mjz_scraper.py --out articles --delay 3

Dependencies:  requests, beautifulsoup4, lxml
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
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://maithilijindabaad.com"
API_POSTS = BASE + "/wp-json/wp/v2/posts"
DEFAULT_DELAY = 3.0           # no robots crawl-delay advertised; be courteous

CONTENT_SELECTORS = [".post-content", ".entry-content", "article"]
JUNK_SELECTORS = [
    ".mag-box", ".mini-posts-box", ".related-posts", ".post-bottom-meta",
    ".sharedaddy", ".addtoany_share_save_container", ".wp-block-buttons",
    ".jp-relatedposts", "script", "style", "ins", "iframe", ".code-block",
    ".heateor_sss_sharing_container", "figure.wp-block-embed", "nav", "footer",
]
NON_ARTICLE = (
    "/category/", "/tag/", "/author/", "/page/", "/wp-", "/feed", "/comments",
    "/about", "/contact", "/privacy", "/disclaimer", "#",
)


# --------------------------------------------------------------------------- #
#  Networking
# --------------------------------------------------------------------------- #
def build_user_agent(contact):
    base = "MJZ-research-collector/1.0 (academic; low-resource Maithili NLP"
    return base + (f"; contact: {contact})" if contact else ")")


def make_session(contact=None):
    s = requests.Session()
    s.headers.update({
        "User-Agent": build_user_agent(contact),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en;q=0.9,hi;q=0.8,mai;q=0.7",
    })
    return s


def read_crawl_delay(session):
    rp = RobotFileParser()
    rp.set_url(BASE + "/robots.txt")
    try:
        rp.read()
        cd = rp.crawl_delay(session.headers.get("User-Agent", "*")) or rp.crawl_delay("*")
        return float(cd) if cd else None
    except Exception:
        return None


def fetch(session, url, *, params=None, retries=3, delay=DEFAULT_DELAY, timeout=30):
    # allow_redirects defaults to True, so the API's 301 is followed.
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 502, 503) and attempt < retries:
                time.sleep(delay * attempt)
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(delay * attempt)
    if last:
        raise last
    return None


# --------------------------------------------------------------------------- #
#  Shared helpers
# --------------------------------------------------------------------------- #
def clean_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "lxml")
    for sel in JUNK_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True)).strip()


def slugify(url: str) -> str:
    parts = urlparse(url)
    path = parts.path.strip("/")
    slug = path.split("/")[-1] if path else ""
    if not slug and parts.query:                 # plain permalink ?p=NNN
        slug = re.sub(r"[^A-Za-z0-9]+", "_", parts.query)
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", slug)[:80].strip("_")
    return slug or "article"


def save_article(article: dict, out_dir: str, idx: int) -> str:
    base = slugify(article["url"]) or f"article_{idx:06d}"
    fpath = os.path.join(out_dir, base + ".json")
    n = 1
    while os.path.exists(fpath):
        fpath = os.path.join(out_dir, f"{base}_{n}.json")
        n += 1
    with open(fpath, "w", encoding="utf-8") as fh:
        json.dump(article, fh, ensure_ascii=False, indent=2)
    return fpath


def is_article_url(url: str) -> bool:
    if not url.startswith(BASE):
        return False
    if any(frag in url for frag in NON_ARTICLE):
        return False
    if url.rstrip("/") == BASE:
        return False
    return True


# --------------------------------------------------------------------------- #
#  Strategy 1 — WordPress REST API
# --------------------------------------------------------------------------- #
def scrape_via_api(session, out_dir, limit=None, delay=DEFAULT_DELAY):
    saved, page = 0, 1
    while True:
        params = {"per_page": 100, "page": page, "_embed": "1"}
        r = fetch(session, API_POSTS, params=params, delay=delay)
        if r.status_code == 400:
            break
        if r.status_code == 403:
            raise requests.HTTPError("403 from REST API", response=r)
        r.raise_for_status()

        # The 301 is followed automatically; make sure we actually got JSON.
        try:
            posts = r.json()
        except ValueError:
            raise requests.HTTPError("REST API did not return JSON "
                                     f"(landed on {r.url})", response=r)
        if not isinstance(posts, list):
            raise requests.HTTPError("Unexpected REST API payload", response=r)
        if not posts:
            break

        total_pages = r.headers.get("X-WP-TotalPages")
        for post in posts:
            article = parse_api_post(post)
            fpath = save_article(article, out_dir, saved)
            saved += 1
            print(f"[{saved}] {article['headline'][:55]!r} -> {os.path.basename(fpath)}")
            if limit and saved >= limit:
                print(f"\nReached limit of {limit}.")
                return saved
        print(f"  ...API page {page}" + (f"/{total_pages}" if total_pages else ""))
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
    emb = post.get("_embedded")
    authors = emb.get("author") if isinstance(emb, dict) else None
    if authors and isinstance(authors, list):
        author = authors[0].get("name", "") or ""
    return {
        "date": date,
        "author": html_lib.unescape(author).strip(),
        "headline": title,
        "news_content": clean_text(content_html),
        "url": post.get("link", ""),
    }


# --------------------------------------------------------------------------- #
#  Strategy 2 — Sitemap discovery + HTML parsing
# --------------------------------------------------------------------------- #
def _looks_like_xml(resp):
    if resp is None or resp.status_code != 200:
        return False
    head = resp.text[:300].lower()
    return any(t in head for t in ("<urlset", "<sitemapindex", "<?xml"))


def discover_urls(session, delay=DEFAULT_DELAY):
    candidates = []
    try:
        r = fetch(session, BASE + "/robots.txt", delay=delay)
        if r and r.status_code == 200:
            candidates += re.findall(r"(?im)^\s*Sitemap:\s*(\S+)", r.text)
    except requests.RequestException:
        pass
    candidates += [BASE + "/sitemap_index.xml", BASE + "/sitemap.xml",
                   BASE + "/wp-sitemap.xml", BASE + "/post-sitemap.xml"]

    seen, to_visit, found = set(), list(dict.fromkeys(candidates)), []
    while to_visit:
        sm = to_visit.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = fetch(session, sm, delay=delay)
        except requests.RequestException:
            continue
        if not _looks_like_xml(r):
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text):
            loc = html_lib.unescape(loc.strip())
            if loc.endswith(".xml"):
                to_visit.append(loc)
            elif is_article_url(loc):
                found.append(loc)
        time.sleep(delay)
    return list(dict.fromkeys(found))


def parse_article_html(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text, "lxml")
    headline = date = author = ""

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if isinstance(node, dict) and "Article" in str(node.get("@type", "")):
                headline = headline or node.get("headline", "")
                date = date or node.get("datePublished", "")
                a = node.get("author")
                if isinstance(a, dict):
                    author = author or a.get("name", "")
        if not author:
            for node in nodes:
                if isinstance(node, dict) and node.get("@type") == "Person":
                    author = node.get("name", "")
                    break

    if not headline:
        m = soup.find("meta", property="og:title")
        headline = m["content"] if m and m.get("content") else ""
    if not headline:
        h1 = soup.select_one("h1.entry-title") or soup.find("h1")
        headline = h1.get_text(strip=True) if h1 else ""
    if not date:
        m = soup.find("meta", property="article:published_time")
        date = m["content"] if m and m.get("content") else ""
    if not author:
        a = soup.select_one("a[rel=author], .author-name, .meta-author")
        author = a.get_text(strip=True) if a else ""

    body_el = None
    for sel in CONTENT_SELECTORS:
        body_el = soup.select_one(sel)
        if body_el:
            break

    return {
        "date": html_lib.unescape(date).strip(),
        "author": html_lib.unescape(author).strip(),
        "headline": html_lib.unescape(headline).strip(),
        "news_content": clean_text(str(body_el)) if body_el else "",
        "url": url,
    }


def scrape_via_html(session, out_dir, limit=None, delay=DEFAULT_DELAY):
    urls = discover_urls(session, delay)
    print(f"Discovered {len(urls)} candidate article URLs.\n")
    saved = 0
    for url in urls:
        try:
            r = fetch(session, url, delay=delay)
        except requests.RequestException as e:
            print(f"  ! skip {url}: {e}", file=sys.stderr)
            continue
        if r.status_code != 200:
            print(f"  ! skip {url}: HTTP {r.status_code}", file=sys.stderr)
            continue
        article = parse_article_html(r.text, url)
        if not article["news_content"]:
            continue
        fpath = save_article(article, out_dir, saved)
        saved += 1
        print(f"[{saved}] {article['headline'][:55]!r} -> {os.path.basename(fpath)}")
        if limit and saved >= limit:
            print(f"\nReached limit of {limit}.")
            break
        time.sleep(delay)
    return saved


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Scrape maithilijindabaad.com to JSON.")
    ap.add_argument("--method", choices=["api", "html"], default="api")
    ap.add_argument("--out", default="articles")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=None,
                    help="Seconds between requests (default: robots crawl-delay, else 3).")
    ap.add_argument("--contact", default=None,
                    help="Your email, added to the User-Agent (good etiquette).")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    session = make_session(contact=args.contact)

    delay = args.delay
    if delay is None:
        advertised = read_crawl_delay(session)
        delay = advertised if advertised else DEFAULT_DELAY
        if advertised:
            print(f"Honouring robots.txt crawl-delay: {delay:.0f}s")
    print(f"Method : {args.method}\nDelay  : {delay:.1f}s\nOutput : {os.path.abspath(args.out)}\n")

    if args.method == "api":
        try:
            n = scrape_via_api(session, args.out, args.limit, delay)
        except (requests.HTTPError, requests.RequestException) as e:
            print(f"\nREST API unavailable ({e}). Falling back to HTML...\n", file=sys.stderr)
            n = scrape_via_html(session, args.out, args.limit, delay)
    else:
        n = scrape_via_html(session, args.out, args.limit, delay)

    print(f"\nDone. Saved {n} article(s) to {os.path.abspath(args.out)}/")


if __name__ == "__main__":
    main()