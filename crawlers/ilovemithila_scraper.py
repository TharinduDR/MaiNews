#!/usr/bin/env python3
"""
Scraper for ilovemithila.com that properly extracts all articles from archive pages
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


def extract_article_urls_from_page(soup, base_url):
    """Extract article URLs from any page (homepage, archive, category, etc.)"""
    urls = set()

    # Look for article links in various patterns
    for link in soup.find_all('a', href=True):
        href = link['href']
        if href.startswith('/'):
            href = urljoin(base_url, href)

        if base_url in href:
            # Article patterns - look for post IDs or date patterns
            if any(p in href for p in ['/20', '/news/', '/story/', '/poem/', '?p=']):
                if '?' not in href or '?p=' in href:  # Allow ?p=123 format
                    if '#comments' not in href:
                        if '/category/' not in href and '/tag/' not in href and '/author/' not in href and '/page/' not in href:
                            # Avoid archive pages themselves
                            if not href.endswith('/news/') and not href.endswith('/category/'):
                                urls.add(href)

    return urls


def discover_all_article_urls(max_pages=50):
    """Discover all article URLs by crawling archive pages"""
    all_urls = set()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    # Start with main archive pages
    archive_urls = [
        BASE_URL + "/news/",
        BASE_URL + "/story/",
        BASE_URL + "/poem/",
        BASE_URL + "/",
    ]

    # Also try category pages
    for page_num in range(1, max_pages + 1):
        archive_urls.append(BASE_URL + f"/page/{page_num}/")
        archive_urls.append(BASE_URL + f"/news/page/{page_num}/")
        archive_urls.append(BASE_URL + f"/category/news/page/{page_num}/")

    print("Crawling archive pages to discover articles...")

    for archive_url in archive_urls[:max_pages * 3]:  # Limit to reasonable number
        try:
            resp = requests.get(archive_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, 'lxml')
            urls_on_page = extract_article_urls_from_page(soup, BASE_URL)

            if urls_on_page:
                all_urls.update(urls_on_page)
                print(f"  Found {len(urls_on_page)} articles on {archive_url}")

            time.sleep(0.3)  # Be polite

        except Exception as e:
            continue

    return list(all_urls)


def get_articles_from_sitemap():
    """Get URLs from sitemap (most reliable)"""
    urls = set()

    sitemap_urls = [
        "https://www.ilovemithila.com/post-sitemap.xml",
        "https://www.ilovemithila.com/page-sitemap.xml",
        "https://www.ilovemithila.com/wp-sitemap.xml",
        "https://www.ilovemithila.com/sitemap.xml",
    ]

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for sitemap_url in sitemap_urls:
        try:
            print(f"Checking sitemap: {sitemap_url}")
            resp = requests.get(sitemap_url, headers=headers, timeout=30)

            if resp.status_code == 200:
                # Check if it's XML
                if 'xml' in resp.headers.get('content-type', '').lower() or resp.text.strip().startswith('<?xml'):
                    # Find all URLs in the sitemap
                    found_urls = re.findall(r'<loc>(.*?)</loc>', resp.text)
                    for url in found_urls:
                        # Filter for article URLs
                        if any(p in url for p in ['/20', '/news/', '/story/', '/poem/', '?p=']):
                            if '/author/' not in url and '/page/' not in url:
                                urls.add(url)

                    print(f"  Found {len(found_urls)} URLs in {sitemap_url}")

                    # If this is a sitemap index, follow sub-sitemaps
                    if 'sitemapindex' in resp.text.lower():
                        sub_sitemaps = re.findall(r'<loc>(.*?\.xml)</loc>', resp.text)
                        for sub_url in sub_sitemaps:
                            try:
                                sub_resp = requests.get(sub_url, headers=headers, timeout=30)
                                if sub_resp.status_code == 200:
                                    sub_urls = re.findall(r'<loc>(.*?)</loc>', sub_resp.text)
                                    for sub_url_found in sub_urls:
                                        if any(p in sub_url_found for p in ['/20', '/news/', '/story/', '/poem/']):
                                            urls.add(sub_url_found)
                                    print(f"    Found {len(sub_urls)} URLs in sub-sitemap")
                                time.sleep(0.3)
                            except:
                                pass
        except Exception as e:
            print(f"  Error with {sitemap_url}: {e}")

    return list(urls)


def scrape_article(url, headers):
    """Scrape a single article and return its data"""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, 'lxml')

        # Extract headline
        headline = soup.find('h1', class_='entry-title')
        if not headline:
            headline = soup.find('h1', class_='post-title')
        if not headline:
            headline = soup.find('h1')

        headline_text = headline.get_text(strip=True) if headline else ""

        # Skip if it's not an article page
        if not headline_text or len(headline_text) < 5:
            return None

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

        return {
            'headline': headline_text,
            'author': author,
            'date': date,
            'news_content': content_text if content_text else "Content extraction failed",
        }

    except Exception as e:
        return None


def scrape_articles(limit=None, output_dir="articles", max_pages=50):
    """Main scraping function"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper (Full Archive)")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print()

    # First try sitemap (most complete)
    print("Method 1: Getting URLs from sitemap...")
    urls = get_articles_from_sitemap()

    if not urls:
        print("Method 2: Crawling archive pages...")
        urls = discover_all_article_urls(max_pages)

    # Remove duplicates
    urls = list(set(urls))

    # Filter out non-article URLs
    urls = [u for u in urls if
            '/author/' not in u and '/page/' not in u and u != BASE_URL + "/news/" and u != BASE_URL + "/"]

    print(f"\n📊 Found {len(urls)} unique article URLs")

    if limit:
        urls = urls[:limit]

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    saved = 0
    failed = 0
    skipped = 0

    for idx, url in enumerate(urls, 1):
        print(f"\n[{idx}/{len(urls)}] {url[:80]}...")

        # Skip archive pages
        if url.endswith('/news/') or url.endswith('/category/') or '/page/' in url:
            print(f"  ⚠ Skipping archive page")
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
    print(f"✅ Complete: {saved} saved, {failed} failed, {skipped} skipped")
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