#!/usr/bin/env python3
"""
Cloudscraper-based scraper for ilovemithila.com
No browser needed - works on HPC clusters!
"""

import json
import os
import re
import time
from pathlib import Path
from datetime import datetime

# Install cloudscraper if not available
try:
    import cloudscraper
except ImportError:
    print("Installing cloudscraper...")
    os.system("pip install --user cloudscraper")
    import cloudscraper

from bs4 import BeautifulSoup

BASE_URL = "https://www.ilovemithila.com"


def scrape_articles(limit=None, output_dir="articles"):
    """Main scraping function using cloudscraper"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper (Cloudscraper)")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print()

    # Create scraper that bypasses Cloudflare
    print("Initializing cloudscraper...")
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'linux',
            'desktop': True
        }
    )

    # Fetch homepage
    print("Fetching homepage...")
    try:
        response = scraper.get(BASE_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch homepage: {e}")
        return 0

    soup = BeautifulSoup(response.text, 'lxml')

    # Find article URLs
    print("Discovering articles...")
    urls = set()

    # Look for links in the main content area
    for link in soup.find_all('a', href=True):
        href = link['href']
        if not href.startswith('http'):
            continue

        if 'ilovemithila.com' in href:
            # Look for article patterns
            if any(p in href for p in ['/20', '/news/', '/story/', '/poem/']):
                if '?' not in href and '#comments' not in href:
                    if '/category/' not in href and '/tag/' not in href:
                        urls.add(href)

    urls = list(urls)
    print(f"Found {len(urls)} article URLs")

    if limit:
        urls = urls[:limit]

    saved = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        print(f"\n[{idx}/{len(urls)}] {url[:80]}...")

        try:
            # Fetch article
            resp = scraper.get(url, timeout=30)
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
                author = author_link.get_text(strip=True) if author_link else author_elem.get_text(strip=True)

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
                        class_=['mag-box', 'sharedaddy', 'share-buttons', 'related-posts', 'post-components']):
                    junk.decompose()
                for junk in content_elem.find_all(['script', 'style', 'ins', 'iframe']):
                    junk.decompose()

                content_text = content_elem.get_text('\n', strip=True)
                content_text = re.sub(r'\n{3,}', '\n\n', content_text)

            if headline_text and content_text:
                # Create filename
                slug = re.sub(r'[^\w\s-]', '', headline_text)
                slug = re.sub(r'[-\s]+', '-', slug)[:50]
                slug = slug or f"article_{idx}"

                article_data = {
                    'url': url,
                    'headline': headline_text,
                    'author': author,
                    'date': date,
                    'news_content': content_text,
                    'scraped_at': datetime.now().isoformat()
                }

                filepath = output_path / f"{slug}.json"
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(article_data, f, ensure_ascii=False, indent=2)

                saved += 1
                print(f"  ✓ Saved: {headline_text[:50]}...")
            else:
                failed += 1
                print(f"  ✗ No content found")

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
    parser.add_argument('--limit', type=int, help='Number of articles to scrape')
    parser.add_argument('--out', default='articles', help='Output directory')
    args = parser.parse_args()

    scrape_articles(limit=args.limit, output_dir=args.out)


if __name__ == "__main__":
    main()