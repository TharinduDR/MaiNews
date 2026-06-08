#!/usr/bin/env python3
"""
Scraper for ilovemithila.com that works with their feed format
Based on the actual feed content we can see
"""

import json
import re
import time
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

BASE_URL = "https://www.ilovemithila.com"


def scrape_from_feed(limit=None, output_dir="articles"):
    """Scrape articles by parsing the feed content directly"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    # First, get the homepage to extract article URLs
    print("Fetching homepage to discover article URLs...")
    try:
        resp = requests.get(BASE_URL, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch homepage: {e}")
        return 0

    soup = BeautifulSoup(resp.text, 'lxml')

    # Find article URLs - look for links that go to articles
    article_urls = set()

    # Method 1: Look for links in the main content area
    for link in soup.find_all('a', href=True):
        href = link['href']
        if href.startswith('/'):
            href = BASE_URL + href

        if BASE_URL in href:
            # Article URL patterns
            if any(pattern in href for pattern in ['/20', '/news/', '/story/', '/poem/']):
                if '?' not in href and '#comments' not in href:
                    if '/category/' not in href and '/tag/' not in href:
                        article_urls.add(href)

    # Method 2: Look specifically in the "Updates" section
    updates_section = soup.find('div', class_='wide-post-box')
    if updates_section:
        for link in updates_section.find_all('a', href=True):
            href = link['href']
            if href.startswith('/'):
                href = BASE_URL + href
            if BASE_URL in href:
                article_urls.add(href)

    article_urls = list(article_urls)
    print(f"Found {len(article_urls)} article URLs")

    if limit:
        article_urls = article_urls[:limit]

    saved = 0
    failed = 0

    for idx, url in enumerate(article_urls, 1):
        print(f"\n[{idx}/{len(article_urls)}] {url[:80]}...")

        try:
            # Fetch the article
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                print(f"  ✗ HTTP {resp.status_code}")
                failed += 1
                continue

            soup = BeautifulSoup(resp.text, 'lxml')

            # Extract headline
            headline = soup.find('h1', class_='entry-title')
            if not headline:
                headline = soup.find('h1', class_='post-title')
            if not headline:
                headline = soup.find('h1')

            headline_text = headline.get_text(strip=True) if headline else ""

            # Extract author
            author = ""
            author_elem = soup.find(class_='author-name')
            if not author_elem:
                author_elem = soup.find(class_='meta-author')
            if author_elem:
                author_link = author_elem.find('a')
                if author_link:
                    author = author_link.get_text(strip=True)
                else:
                    author = author_elem.get_text(strip=True)

            # Extract date
            date = ""
            date_meta = soup.find('meta', property='article:published_time')
            if date_meta:
                date = date_meta.get('content', '')
            if not date:
                date_elem = soup.find(class_='date')
                if date_elem:
                    date = date_elem.get_text(strip=True)

            # Extract content
            content_elem = soup.find('div', class_='entry-content')
            if not content_elem:
                content_elem = soup.find('div', class_='post-content')
            if not content_elem:
                content_elem = soup.find('article')

            content_text = ""
            if content_elem:
                # Remove junk elements
                for junk in content_elem.find_all(
                        class_=['mag-box', 'sharedaddy', 'share-buttons', 'related-posts', 'post-components',
                                'about-author']):
                    junk.decompose()
                for junk in content_elem.find_all(['script', 'style', 'ins', 'iframe']):
                    junk.decompose()

                content_text = content_elem.get_text('\n', strip=True)
                content_text = re.sub(r'\n{3,}', '\n\n', content_text)

            if headline_text:
                # Create filename
                slug = re.sub(r'[^\w\s-]', '', headline_text)
                slug = re.sub(r'[-\s]+', '-', slug)[:50]
                slug = slug or f"article_{idx}"

                article_data = {
                    'url': url,
                    'headline': headline_text,
                    'author': author,
                    'date': date,
                    'news_content': content_text if content_text else "Content extraction failed",
                    'scraped_at': datetime.now().isoformat()
                }

                filepath = output_path / f"{slug}.json"
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(article_data, f, ensure_ascii=False, indent=2)

                saved += 1
                print(f"  ✓ Saved: {headline_text[:50]}...")
            else:
                failed += 1
                print(f"  ✗ No headline found")

            time.sleep(1)  # Be polite

        except Exception as e:
            failed += 1
            print(f"  ✗ Error: {str(e)[:100]}")

    print(f"\n" + "=" * 60)
    print(f"✅ Complete: {saved} saved, {failed} failed")
    print(f"📁 Output: {output_path.absolute()}")
    return saved


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='Number of articles to scrape')
    parser.add_argument('--out', default='articles', help='Output directory')
    args = parser.parse_args()

    scrape_from_feed(limit=args.limit, output_dir=args.out)


if __name__ == "__main__":
    main()