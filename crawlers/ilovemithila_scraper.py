#!/usr/bin/env python3
"""
Scrape ilovemithila.com using RSS feed (bypasses Cloudflare)
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

BASE_URL = "https://www.ilovemithila.com"
RSS_FEED = "https://www.ilovemithila.com/feed/"


def scrape_via_rss(limit=None, output_dir="articles"):
    """Scrape articles using RSS feed"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper (via RSS)")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    # Fetch RSS feed
    print(f"Fetching RSS feed: {RSS_FEED}")
    try:
        resp = requests.get(RSS_FEED, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        return 0

    # Parse RSS
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        print("Failed to parse RSS XML")
        return 0

    # Find all items
    items = root.findall('.//item')
    print(f"Found {len(items)} items in RSS feed")

    if limit:
        items = items[:limit]

    saved = 0
    failed = 0

    for idx, item in enumerate(items, 1):
        # Extract basic info from RSS
        title_elem = item.find('title')
        title = title_elem.text if title_elem is not None else ""

        link_elem = item.find('link')
        url = link_elem.text if link_elem is not None else ""

        pubdate_elem = item.find('pubDate')
        pubdate = pubdate_elem.text if pubdate_elem is not None else ""

        description_elem = item.find('description')
        description = description_elem.text if description_elem is not None else ""

        print(f"\n[{idx}/{len(items)}] {title[:60]}...")
        print(f"  URL: {url}")

        # Try to fetch the full article
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'lxml')

                # Extract full content
                content = soup.find('div', class_='entry-content')
                if not content:
                    content = soup.find('div', class_='post-content')
                if not content:
                    content = soup.find('article')

                if content:
                    # Clean content
                    for junk in content.find_all(['script', 'style', 'ins', 'iframe']):
                        junk.decompose()
                    for junk in content.find_all(class_=['mag-box', 'share-buttons', 'related-posts']):
                        junk.decompose()

                    full_text = content.get_text('\n', strip=True)
                    full_text = re.sub(r'\n{3,}', '\n\n', full_text)
                else:
                    full_text = description

                # Extract author
                author = ""
                author_elem = soup.find(class_='author-name')
                if author_elem:
                    author = author_elem.get_text(strip=True)

                # Save article
                slug = re.sub(r'[^\w\s-]', '', title)[:50].replace(' ', '_')
                filename = f"{output_path}/{slug}.json"

                article = {
                    'url': url,
                    'headline': title,
                    'author': author,
                    'date': pubdate,
                    'news_content': full_text,
                    'scraped_at': datetime.now().isoformat()
                }

                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(article, f, ensure_ascii=False, indent=2)

                saved += 1
                print(f"  ✓ Saved")
            else:
                # Save RSS description as fallback
                slug = re.sub(r'[^\w\s-]', '', title)[:50].replace(' ', '_')
                filename = f"{output_path}/{slug}.json"

                article = {
                    'url': url,
                    'headline': title,
                    'author': '',
                    'date': pubdate,
                    'news_content': description,
                    'scraped_at': datetime.now().isoformat(),
                    'note': 'From RSS feed (full article not fetched)'
                }

                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(article, f, ensure_ascii=False, indent=2)

                saved += 1
                print(f"  ✓ Saved (from RSS)")

        except Exception as e:
            failed += 1
            print(f"  ✗ Error: {e}")

        time.sleep(1)

    print(f"\n✅ Complete: {saved} saved, {failed} failed")
    return saved


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=100, help='Number of articles')
    parser.add_argument('--out', default='articles', help='Output directory')
    args = parser.parse_args()

    scrape_via_rss(limit=args.limit, output_dir=args.out)


if __name__ == "__main__":
    main()