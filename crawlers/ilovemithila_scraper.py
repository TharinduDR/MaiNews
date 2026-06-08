#!/usr/bin/env python3
"""
Simple requests-based scraper - No browser needed!
"""

import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime

BASE_URL = "https://www.ilovemithila.com"
OUTPUT_DIR = "articles"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}


def get_article_urls():
    """Extract article URLs from homepage"""
    print(f"Fetching {BASE_URL}...")
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'lxml')
    urls = set()

    # Find all article links
    for link in soup.find_all('a', href=True):
        href = link['href']
        if not href.startswith('http'):
            href = urljoin(BASE_URL, href)

        if 'ilovemithila.com' in href:
            # Filter for article patterns
            if any(pattern in href for pattern in ['/20', '/news/', '/story/', '/poem/']):
                if '?' not in href and '#comments' not in href:
                    if '/category/' not in href and '/tag/' not in href:
                        urls.add(href)

    print(f"Found {len(urls)} article URLs")
    return list(urls)


def extract_article(url):
    """Extract article data from URL"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Failed to fetch: {e}")
        return None

    soup = BeautifulSoup(resp.text, 'lxml')

    article = {'url': url, 'scraped_at': datetime.now().isoformat()}

    # Get headline
    headline = soup.find('h1', class_='entry-title') or soup.find('h1', class_='post-title')
    if not headline:
        headline = soup.find('h1')
    article['headline'] = headline.get_text(strip=True) if headline else ''

    # Get author
    author = soup.find(class_='author-name') or soup.find(class_='meta-author')
    if author:
        author_link = author.find('a')
        article['author'] = author_link.get_text(strip=True) if author_link else author.get_text(strip=True)
    else:
        article['author'] = ''

    # Get date
    date_meta = soup.find('meta', property='article:published_time')
    if date_meta:
        article['date'] = date_meta.get('content', '')
    else:
        date_elem = soup.find(class_='date')
        article['date'] = date_elem.get_text(strip=True) if date_elem else ''

    # Get content
    content = soup.find(class_='entry-content') or soup.find(class_='post-content')
    if not content:
        content = soup.find('article')

    if content:
        # Remove junk
        for junk in content.find_all(class_=['mag-box', 'sharedaddy', 'share-buttons', 'related-posts']):
            junk.decompose()
        for junk in content.find_all(['script', 'style', 'ins', 'iframe']):
            junk.decompose()

        article['news_content'] = content.get_text('\n', strip=True)
        # Clean up excessive newlines
        article['news_content'] = re.sub(r'\n{3,}', '\n\n', article['news_content'])
    else:
        article['news_content'] = ''

    return article


def save_article(article, output_dir):
    """Save article to JSON file"""
    if not article['headline'] or not article['news_content']:
        return False

    # Create filename
    slug = re.sub(r'[^\w\s-]', '', article['headline'])
    slug = re.sub(r'[-\s]+', '-', slug)[:50]
    filename = f"{slug}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(article, f, ensure_ascii=False, indent=2)

    return True


def scrape_articles(limit=None, output_dir=OUTPUT_DIR):
    """Main scraping function"""
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper (No Browser Needed)")
    print("=" * 60)

    # Get URLs
    urls = get_article_urls()
    if not urls:
        print("No URLs found!")
        return

    if limit:
        urls = urls[:limit]

    saved = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        print(f"\n[{idx}/{len(urls)}] {url[:80]}...")

        article = extract_article(url)

        if article and save_article(article, output_dir):
            saved += 1
            print(f"  ✓ Saved: {article['headline'][:50]}...")
        else:
            failed += 1
            print(f"  ✗ Failed")

        time.sleep(1)  # Be polite

    print(f"\n✅ Done: {saved} saved, {failed} failed")
    print(f"📁 Output: {os.path.abspath(output_dir)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Number of articles')
    parser.add_argument('--out', default='articles', help='Output directory')
    parser.add_argument('--delay', type=float, default=1, help='Delay between requests')
    args = parser.parse_args()

    scrape_articles(limit=args.limit, output_dir=args.out)