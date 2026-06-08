#!/usr/bin/env python3
"""
Scraper for esamaad.com - Maithili E-Paper
"""

import json
import re
import time
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BASE_URL = "https://esamaad.com"


def extract_article_urls_from_page(soup, base_url):
    """Extract article URLs from any page"""
    urls = set()

    # Look for article links - common patterns on this site
    for link in soup.find_all('a', href=True):
        href = link['href']
        if href.startswith('/'):
            href = urljoin(base_url, href)

        if base_url in href:
            # Article patterns - look for date patterns or common article slugs
            if any(p in href for p in ['/202', '/20', '/article/', '/news/', '/story/', '/post/']):
                if '?' not in href and '#comments' not in href:
                    if '/category/' not in href and '/tag/' not in href and '/page/' not in href:
                        urls.add(href)

    return urls


def discover_articles(max_pages=30):
    """Discover all articles by crawling homepage and archive pages"""
    all_urls = set()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    print("Discovering articles from esamaad.com...")

    # Start with homepage
    start_urls = [
        BASE_URL,
        BASE_URL + "/news/",
        BASE_URL + "/category/news/",
    ]

    # Add pagination pages
    for page_num in range(2, max_pages + 1):
        start_urls.append(BASE_URL + f"/page/{page_num}/")
        start_urls.append(BASE_URL + f"/news/page/{page_num}/")

    for url in start_urls:
        try:
            print(f"  Checking: {url}")
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, 'lxml')

            # Extract article links
            urls_on_page = extract_article_urls_from_page(soup, BASE_URL)

            if urls_on_page:
                all_urls.update(urls_on_page)
                print(f"    Found {len(urls_on_page)} article links")

            # Also look specifically in breaking news section
            breaking_section = soup.find('div', class_=re.compile(r'breaking|headline|featured'))
            if breaking_section:
                for link in breaking_section.find_all('a', href=True):
                    href = link['href']
                    if href.startswith('/'):
                        href = urljoin(BASE_URL, href)
                    if BASE_URL in href and '/page/' not in href:
                        all_urls.add(href)

            time.sleep(0.5)

        except Exception as e:
            print(f"  Error with {url}: {e}")
            continue

    # Filter URLs
    all_urls = [u for u in all_urls if not any(skip in u for skip in ['/category/', '/tag/', '/author/', '/page/'])]

    return list(all_urls)


def scrape_article(url, headers):
    """Scrape a single article from esamaad.com"""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, 'lxml')

        # Get headline - try multiple possible selectors
        headline = None
        for selector in [
            'h1.entry-title', 'h1.post-title', 'h1.title',
            'article h1', '.entry-header h1', '.post-header h1'
        ]:
            headline = soup.select_one(selector)
            if headline:
                break

        if not headline:
            headline = soup.find('h1')

        headline_text = headline.get_text(strip=True) if headline else ""

        if not headline_text:
            return None

        # Get author - if available
        author = ""
        for selector in ['.author', '.byline', '.post-author', '.meta-author']:
            author_elem = soup.select_one(selector)
            if author_elem:
                author = author_elem.get_text(strip=True)
                # Clean up "By" prefix if present
                author = re.sub(r'^By\s+|^बिहारी:\s+', '', author)
                break

        # Get date
        date = ""
        for selector in ['.date', '.post-date', '.published', '.meta-date', 'time']:
            date_elem = soup.select_one(selector)
            if date_elem:
                date = date_elem.get('datetime', '') or date_elem.get_text(strip=True)
                break

        # Get content
        content_elem = None
        for selector in ['.entry-content', '.post-content', '.article-content', '.story-content', 'article']:
            content_elem = soup.select_one(selector)
            if content_elem:
                break

        content_text = ""
        if content_elem:
            # Remove junk elements
            for junk in content_elem.find_all(class_=['share-buttons', 'social-share', 'related-posts', 'comments']):
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
    """Main scraping function for esamaad.com"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("esamaad.com Article Scraper")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print()

    # Discover article URLs
    urls = discover_articles(max_pages)

    print(f"\n📊 Found {len(urls)} unique article URLs")

    # Show sample URLs for verification
    if urls:
        print("\nSample URLs found:")
        for url in urls[:5]:
            print(f"  - {url}")
    else:
        print("No article URLs found! Trying to extract from homepage directly...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(BASE_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'lxml')
            # Look for any links that might be articles
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.startswith('/') and len(href) > 1 and href != '/' and '/page/' not in href:
                    if not any(skip in href for skip in ['/category/', '/tag/', '/wp-']):
                        urls.append(urljoin(BASE_URL, href))
            urls = list(set(urls))
            print(f"Found {len(urls)} potential article URLs from homepage")

    if limit:
        urls = urls[:limit]

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    saved = 0
    failed = 0
    skipped = 0

    for idx, url in enumerate(urls, 1):
        print(f"\n[{idx}/{len(urls)}] {url[:80]}...")

        # Skip non-article pages
        if any(skip in url for skip in ['/page/', '/category/', '/tag/', '/author/', '/wp-']):
            print(f"  ⚠ Skipping non-article page")
            skipped += 1
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
                'scraped_at': datetime.now().isoformat(),
                'source': 'esamaad.com'
            }

            filepath = output_path / f"esamaad_{slug}.json"
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(full_article, f, ensure_ascii=False, indent=2)

            saved += 1
            print(f"  ✓ Saved: {article_data['headline'][:50]}...")
        else:
            failed += 1
            print(f"  ✗ Failed to extract article")

        time.sleep(1)  # Be polite to the server

    print(f"\n" + "=" * 60)
    print(f"✅ Complete: {saved} saved, {failed} failed, {skipped} skipped")
    print(f"📁 Output: {output_path.absolute()}")
    return saved


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Scraper for esamaad.com - Maithili E-Paper')
    parser.add_argument('--limit', type=int, default=None, help='Number of articles to scrape')
    parser.add_argument('--out', default='articles', help='Output directory')
    parser.add_argument('--max-pages', type=int, default=30, help='Max pagination pages to check')
    args = parser.parse_args()

    scrape_articles(limit=args.limit, output_dir=args.out, max_pages=args.max_pages)


if __name__ == "__main__":
    main()
    main()