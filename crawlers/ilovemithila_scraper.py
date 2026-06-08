#!/usr/bin/env python3
"""
Scraper for ilovemithila.com with pagination support
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


def get_page_urls(base_url, max_pages=50):
    """Get article URLs from multiple pages"""
    all_urls = set()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    # Try different pagination patterns
    pagination_patterns = [
        '/page/{}/',
        '/news/page/{}/',
        '/category/news/page/{}/',
        '?paged={}',
    ]

    for page_num in range(1, max_pages + 1):
        found_any = False

        for pattern in pagination_patterns:
            if '?' in pattern:
                page_url = BASE_URL + pattern.format(page_num)
            else:
                page_url = BASE_URL + pattern.format(page_num)

            try:
                print(f"Checking: {page_url}")
                resp = requests.get(page_url, headers=headers, timeout=30)

                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'lxml')

                    # Look for article links
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if href.startswith('/'):
                            href = BASE_URL + href

                        if BASE_URL in href:
                            # Article patterns
                            if any(p in href for p in ['/20', '/news/', '/story/', '/poem/']):
                                if '?' not in href and '#comments' not in href:
                                    if '/category/' not in href and '/tag/' not in href and '/author/' not in href:
                                        all_urls.add(href)
                                        found_any = True

                    # Check if there's a "next" button - if not, we might be at the end
                    next_button = soup.find('a', class_='next')
                    if not next_button:
                        if found_any and page_num > 3:
                            # If no next button and we found articles, break after this page
                            print(f"No 'next' button found at page {page_num}, continuing anyway...")

            except Exception as e:
                continue

        if not found_any and page_num > 5:
            # After 5 pages with no results, stop
            print(f"No articles found on page {page_num}, stopping...")
            break

        time.sleep(0.5)  # Be polite

    return list(all_urls)


def get_articles_from_sitemap():
    """Alternative: Get URLs from sitemap"""
    urls = set()

    sitemap_urls = [
        "https://www.ilovemithila.com/post-sitemap.xml",
        "https://www.ilovemithila.com/page-sitemap.xml",
        "https://www.ilovemithila.com/wp-sitemap.xml",
    ]

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for sitemap_url in sitemap_urls:
        try:
            resp = requests.get(sitemap_url, headers=headers, timeout=30)
            if resp.status_code == 200 and 'xml' in resp.headers.get('content-type', ''):
                # Find all URLs in the sitemap
                urls_in_sitemap = re.findall(r'<loc>(.*?)</loc>', resp.text)
                for url in urls_in_sitemap:
                    if any(p in url for p in ['/20', '/news/', '/story/', '/poem/']):
                        if '/author/' not in url:
                            urls.add(url)
                print(f"Found {len(urls_in_sitemap)} URLs in {sitemap_url}")
        except Exception as e:
            print(f"Could not fetch {sitemap_url}: {e}")

    return list(urls)


def scrape_articles(limit=None, output_dir="articles", max_pages=20):
    """Main scraping function with pagination"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper (with Pagination)")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print()

    # Try sitemap first (more complete)
    print("Trying to get URLs from sitemap...")
    urls = get_articles_from_sitemap()

    if not urls:
        print("Sitemap didn't work, trying pagination...")
        urls = get_page_urls(BASE_URL, max_pages)

    if not urls:
        print("No URLs found!")
        return 0

    print(f"\nFound {len(urls)} total article URLs")

    # Filter out author pages and other non-article pages
    urls = [u for u in urls if '/author/' not in u and '/page/' not in u]
    print(f"After filtering: {len(urls)} article URLs")

    if limit:
        urls = urls[:limit]

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    saved = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        print(f"\n[{idx}/{len(urls)}] {url[:80]}...")

        # Skip author pages
        if '/author/' in url:
            print(f"  ⚠ Skipping author page")
            continue

        try:
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

            # Skip if no headline or it looks like an author page
            if not headline_text or 'author' in url.lower():
                print(f"  ⚠ Not an article page")
                continue

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

            time.sleep(0.5)  # Be polite

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
    parser.add_argument('--max-pages', type=int, default=50, help='Maximum pages to check')
    args = parser.parse_args()

    scrape_articles(limit=args.limit, output_dir=args.out, max_pages=args.max_pages)


if __name__ == "__main__":
    main()