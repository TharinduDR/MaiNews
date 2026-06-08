#!/usr/bin/env python3
"""
Scraper for ilovemithila.com - Crawls archive pages to find all articles
"""

import json
import re
import time
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BASE_URL = "https://www.ilovemithila.com"


def extract_articles_from_archive_page(url, headers):
    """Extract all article links from an archive page"""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, 'lxml')
        articles = []

        # Look for article links in the main content
        # Method 1: Look for h2/h3 with links (common pattern)
        for heading in soup.find_all(['h2', 'h3']):
            link = heading.find('a')
            if link and link.get('href'):
                href = link['href']
                if href.startswith('/'):
                    href = urljoin(BASE_URL, href)
                if BASE_URL in href and '/page/' not in href:
                    articles.append(href)

        # Method 2: Look for post class divs
        for post in soup.find_all(['article', 'div'], class_=re.compile(r'post|article|entry')):
            link = post.find('a', href=True)
            if link:
                href = link['href']
                if href.startswith('/'):
                    href = urljoin(BASE_URL, href)
                if BASE_URL in href and '/page/' not in href:
                    articles.append(href)

        # Method 3: Direct link search (fallback)
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.startswith('/'):
                href = urljoin(BASE_URL, href)

            # Check if it looks like an article URL
            if BASE_URL in href:
                if any(p in href for p in ['/20', '?p=', '/news/', '/story/', '/poem/']):
                    if '/page/' not in href and '/tag/' not in href and '/category/' not in href:
                        articles.append(href)

        return list(set(articles))

    except Exception as e:
        print(f"  Error parsing {url}: {e}")
        return []


def discover_all_articles(max_pages=50):
    """Discover all articles by crawling the site structure"""
    all_articles = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    # Start with main archive pages
    start_urls = [
        BASE_URL,  # Homepage
        BASE_URL + "/news/",
        BASE_URL + "/story/",
        BASE_URL + "/poem/",
    ]

    # Add pagination pages
    for page_num in range(2, max_pages + 1):
        start_urls.append(BASE_URL + f"/page/{page_num}/")
        start_urls.append(BASE_URL + f"/news/page/{page_num}/")
        start_urls.append(BASE_URL + f"/story/page/{page_num}/")
        start_urls.append(BASE_URL + f"/poem/page/{page_num}/")

    print(f"Checking {len(start_urls)} archive pages...")

    for url in start_urls:
        print(f"  Crawling: {url}")
        articles = extract_articles_from_archive_page(url, headers)
        if articles:
            all_articles.update(articles)
            print(f"    Found {len(articles)} articles")
        time.sleep(0.3)

    return list(all_articles)


def scrape_article(url, headers):
    """Scrape a single article page"""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, 'lxml')

        # Get headline
        headline = soup.find('h1', class_='entry-title')
        if not headline:
            headline = soup.find('h1', class_='post-title')
        if not headline:
            headline = soup.find('h1')

        headline_text = headline.get_text(strip=True) if headline else ""

        if not headline_text:
            return None

        # Get author
        author = ""
        author_elem = soup.find(class_='author-name')
        if not author_elem:
            author_elem = soup.find(class_='meta-author')
        if author_elem:
            author_link = author_elem.find('a')
            author = author_link.get_text(strip=True) if author_link else author_elem.get_text(strip=True)

        # Get date
        date = ""
        date_meta = soup.find('meta', property='article:published_time')
        if date_meta:
            date = date_meta.get('content', '')
        if not date:
            date_elem = soup.find(class_='date')
            if date_elem:
                date = date_elem.get_text(strip=True)

        # Get content
        content_elem = soup.find('div', class_='entry-content')
        if not content_elem:
            content_elem = soup.find('div', class_='post-content')
        if not content_elem:
            content_elem = soup.find('article')

        content_text = ""
        if content_elem:
            # Clean content
            for junk in content_elem.find_all(class_=['mag-box', 'share-buttons', 'related-posts', 'post-components']):
                junk.decompose()
            for junk in content_elem.find_all(['script', 'style', 'ins', 'iframe']):
                junk.decompose()

            content_text = content_elem.get_text('\n', strip=True)
            content_text = re.sub(r'\n{3,}', '\n\n', content_text)

        return {
            'headline': headline_text,
            'author': author,
            'date': date,
            'news_content': content_text if content_text else "Content extraction failed",
        }

    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return None


def scrape_articles(limit=None, output_dir="articles", max_pages=30):
    """Main scraping function"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print()

    # Discover all article URLs
    print("Discovering articles by crawling archive pages...")
    urls = discover_all_articles(max_pages)

    print(f"\n📊 Found {len(urls)} unique article URLs")

    # Show sample URLs for verification
    if urls:
        print("\nSample URLs found:")
        for url in urls[:5]:
            print(f"  - {url}")

    if not urls:
        print("No articles found! Trying direct homepage extraction...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        urls = extract_articles_from_archive_page(BASE_URL, headers)
        print(f"Found {len(urls)} from homepage")

    if limit:
        urls = urls[:limit]

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    saved = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        print(f"\n[{idx}/{len(urls)}] {url[:80]}...")

        # Skip archive pages
        if any(skip in url for skip in ['/page/', '/tag/', '/category/', '/author/']):
            print(f"  ⚠ Skipping archive/tag page")
            continue

        article_data = scrape_article(url, headers)

        if article_data and article_data['headline']:
            # Create filename
            slug = re.sub(r'[^\w\s-]', '', article_data['headline'])
            slug = re.sub(r'[-\s]+', '-', slug)[:50]
            slug = slug or f"article_{idx}"

            full_article = {
                'url': url,
                'headline': article_data['headline'],
                'author': article_data['author'],
                'date': article_data['date'],
                'news_content': article_data['news_content'],
                'scraped_at': datetime.now().isoformat()
            }

            filepath = output_path / f"{slug}.json"
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(full_article, f, ensure_ascii=False, indent=2)

            saved += 1
            print(f"  ✓ Saved: {article_data['headline'][:50]}...")
        else:
            failed += 1
            print(f"  ✗ Failed to extract article")

        time.sleep(0.5)

    print(f"\n" + "=" * 60)
    print(f"✅ Complete: {saved} saved, {failed} failed")
    print(f"📁 Output: {output_path.absolute()}")
    return saved


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='Number of articles to scrape')
    parser.add_argument('--out', default='articles', help='Output directory')
    parser.add_argument('--max-pages', type=int, default=30, help='Max pagination pages to check')
    args = parser.parse_args()

    scrape_articles(limit=args.limit, output_dir=args.out, max_pages=args.max_pages)


if __name__ == "__main__":
    main()