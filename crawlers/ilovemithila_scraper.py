#!/usr/bin/env python3
"""
Complete article scraper for ilovemithila.com
Saves articles as structured JSON files with metadata.

Usage:
    python scraper.py                    # Scrape all articles
    python scraper.py --limit 50         # Scrape only 50 articles
    python scraper.py --out my_articles  # Custom output directory
    python scraper.py --delay 2          # 2 seconds between requests
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Browser, Page
from bs4 import BeautifulSoup
import argparse

# Configuration
BASE_URL = "https://www.ilovemithila.com"
OUTPUT_DIR = "articles"
REQUEST_DELAY = 1.5  # Seconds between requests
MAX_RETRIES = 3
TIMEOUT = 30000  # milliseconds

# Selectors for extracting data
SELECTORS = {
    'headline': [
        'h1.entry-title',
        'h1.post-title',
        'article h1',
        '.entry-header h1',
        'h1[class*="title"]'
    ],
    'author': [
        '.author-name',
        '.meta-author a',
        'a[rel="author"]',
        '.post-meta .author-name',
        '[itemprop="author"]'
    ],
    'date': [
        '.date.meta-item',
        '.post-meta .date',
        'time[datetime]',
        '[itemprop="datePublished"]',
        'meta[property="article:published_time"]'
    ],
    'content': [
        '.entry-content',
        '.post-content',
        'article .content',
        '.single-post-content',
        '#the-post .entry-content'
    ]
}

# Elements to remove from content
JUNK_SELECTORS = [
    '.mag-box', '.mini-posts-box', '.related-posts', '.post-bottom-meta',
    '.sharedaddy', '.addtoany_share_save_container', '.wp-block-buttons',
    'script', 'style', 'ins', 'iframe', '.code-block',
    '.heateor_sss_sharing_container', '.share-buttons', '.post-components',
    '#comments', '.about-author', '.stream-item', '.post-footer',
    '.entry-footer', '.post-extra-info', '#share-buttons-top',
    '#share-buttons-bottom', '.post-navigation', '.author-box'
]


class ArticleScraper:
    def __init__(self, output_dir: str = OUTPUT_DIR, delay: float = REQUEST_DELAY):
        self.output_dir = Path(output_dir)
        self.delay = delay
        self.seen_urls: Set[str] = set()
        self.saved_count = 0
        self.failed_count = 0

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def slugify(self, text: str, max_length: int = 100) -> str:
        """Create a safe filename from text."""
        # Remove special characters
        slug = re.sub(r'[^\w\s-]', '', text)
        # Replace spaces and underscores with hyphens
        slug = re.sub(r'[-\s]+', '-', slug)
        # Remove non-ASCII characters
        slug = slug.encode('ascii', 'ignore').decode('ascii')
        # Limit length
        if len(slug) > max_length:
            slug = slug[:max_length]
        # Remove trailing hyphens
        slug = slug.strip('-')
        return slug or 'article'

    def extract_json_ld(self, page: Page) -> Optional[Dict]:
        """Extract structured data from JSON-LD scripts."""
        try:
            result = page.evaluate('''
                () => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    for (const script of scripts) {
                        try {
                            const data = JSON.parse(script.textContent);
                            if (data && (data['@type'] === 'NewsArticle' || data['@type'] === 'Article')) {
                                return data;
                            }
                            if (data['@graph']) {
                                for (const item of data['@graph']) {
                                    if (item['@type'] === 'NewsArticle' || item['@type'] === 'Article') {
                                        return item;
                                    }
                                }
                            }
                        } catch(e) {}
                    }
                    return null;
                }
            ''')
            return result
        except Exception:
            return None

    async def extract_article_data(self, page: Page, url: str) -> Dict:
        """Extract all article data from the page."""
        article = {
            'url': url,
            'headline': '',
            'author': '',
            'date': '',
            'news_content': '',
            'scraped_at': datetime.now().isoformat()
        }

        # Try JSON-LD first (most reliable)
        json_ld = self.extract_json_ld(page)
        if json_ld:
            article['headline'] = json_ld.get('headline', '')
            article['date'] = json_ld.get('datePublished', '')
            author = json_ld.get('author', {})
            if isinstance(author, dict):
                article['author'] = author.get('name', '')
            elif isinstance(author, str):
                article['author'] = author

        # Fallback to DOM selectors if JSON-LD didn't provide data
        if not article['headline']:
            for selector in SELECTORS['headline']:
                try:
                    elem = await page.query_selector(selector)
                    if elem:
                        article['headline'] = (await elem.text_content()).strip()
                        break
                except:
                    continue

        if not article['author']:
            for selector in SELECTORS['author']:
                try:
                    elem = await page.query_selector(selector)
                    if elem:
                        article['author'] = (await elem.text_content()).strip()
                        break
                except:
                    continue

        if not article['date']:
            # Try meta tags first
            date_meta = await page.query_selector('meta[property="article:published_time"]')
            if date_meta:
                article['date'] = await date_meta.get_attribute('content')

            if not article['date']:
                for selector in SELECTORS['date']:
                    try:
                        elem = await page.query_selector(selector)
                        if elem:
                            # Check for datetime attribute
                            date_attr = await elem.get_attribute('datetime')
                            if date_attr:
                                article['date'] = date_attr
                            else:
                                article['date'] = (await elem.text_content()).strip()
                            break
                    except:
                        continue

        # Extract content
        content_html = ''
        for selector in SELECTORS['content']:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    content_html = await elem.inner_html()
                    break
            except:
                continue

        # Clean the content
        if content_html:
            article['news_content'] = self.clean_content(content_html)

        return article

    def clean_content(self, html_content: str) -> str:
        """Clean HTML content to readable plain text."""
        if not html_content:
            return ''

        soup = BeautifulSoup(html_content, 'lxml')

        # Remove junk elements
        for selector in JUNK_SELECTORS:
            for element in soup.select(selector):
                element.decompose()

        # Remove empty paragraphs
        for p in soup.find_all('p'):
            if not p.get_text(strip=True):
                p.decompose()

        # Get text with proper paragraph separation
        text = soup.get_text('\n', strip=True)

        # Clean up excessive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Remove duplicate spaces
        text = re.sub(r'[ \t]+', ' ', text)

        return text.strip()

    async def discover_article_urls(self, page: Page, limit: Optional[int] = None) -> List[str]:
        """Discover article URLs from the homepage and category pages."""
        urls = set()

        print("Discovering article URLs from homepage...")
        await page.goto(BASE_URL, wait_until='networkidle', timeout=TIMEOUT)

        # Scroll to load more content
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await asyncio.sleep(2)

        # Find all article links
        article_links = await page.eval_on_selector_all(
            'a[href*="/20"], a[href*="/news/"], a[href*="/story/"], a[href*="/poem/"]',
            '''(elements) => elements.map(el => el.href).filter(href => 
                href && href.includes('ilovemithila.com') && 
                !href.includes('?') && 
                !href.includes('#comments') &&
                !href.includes('/category/') &&
                !href.includes('/tag/') &&
                !href.includes('/author/')
            )'''
        )

        urls.update(article_links)
        print(f"Found {len(urls)} URLs from homepage")

        # Also check the main content area for more links
        content_links = await page.eval_on_selector_all(
            '.main-content a, .mag-box a, .posts-items a',
            '''(elements) => elements.map(el => el.href).filter(href => 
                href && href.includes('ilovemithila.com') && 
                href.match(/\\/\\d{4}\\/\\d{2}\\//) &&  # Has date pattern
                !href.includes('?')
            )'''
        )

        urls.update(content_links)

        # Convert to list and sort by recency (if possible)
        url_list = list(urls)
        print(f"Total unique URLs discovered: {len(url_list)}")

        return url_list[:limit] if limit else url_list

    async def save_article(self, article: Dict) -> Optional[str]:
        """Save article to JSON file."""
        if not article.get('headline'):
            print(f"  ⚠ Skipping article without headline: {article['url']}")
            return None

        # Create filename from URL
        url_path = urlparse(article['url']).path.strip('/')
        if url_path:
            slug = self.slugify(url_path.split('/')[-1])
        else:
            slug = self.slugify(article['headline'])

        # Add date prefix for sorting
        if article.get('date'):
            date_prefix = article['date'][:10].replace('-', '')
            filename = f"{date_prefix}_{slug}.json"
        else:
            filename = f"{slug}.json"

        filepath = self.output_dir / filename

        # Save with nice formatting
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(article, f, ensure_ascii=False, indent=2)

        return str(filepath)

    async def scrape_article(self, browser: Browser, url: str) -> Optional[Dict]:
        """Scrape a single article."""
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        page = await context.new_page()

        try:
            # Navigate to article
            await page.goto(url, wait_until='networkidle', timeout=TIMEOUT)

            # Wait for content to load
            await page.wait_for_selector('.entry-content, .post-content, article', timeout=10000)

            # Extract data
            article_data = await self.extract_article_data(page, url)

            return article_data

        except Exception as e:
            print(f"  ✗ Error scraping {url}: {e}")
            return None
        finally:
            await page.close()
            await context.close()

    async def scrape_all(self, limit: Optional[int] = None):
        """Main scraping function."""
        print("=" * 60)
        print("ilovemithila.com Article Scraper")
        print("=" * 60)
        print(f"Output directory: {self.output_dir.absolute()}")
        print(f"Delay between requests: {self.delay}s")
        print(f"Article limit: {limit if limit else 'No limit'}")
        print()

        async with async_playwright() as p:
            # Launch browser
            print("Launching browser...")
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-gpu',
                    '--disable-software-rasterizer'
                ]
            )

            try:
                # Create temporary page for discovery
                temp_page = await browser.new_page()

                # Discover article URLs
                urls = await self.discover_article_urls(temp_page, limit)

                await temp_page.close()

                if not urls:
                    print("❌ No article URLs found!")
                    return

                print(f"\n📝 Starting to scrape {len(urls)} articles...\n")

                # Scrape each article
                for idx, url in enumerate(urls, 1):
                    if url in self.seen_urls:
                        continue

                    self.seen_urls.add(url)

                    print(f"[{idx}/{len(urls)}] {url[:80]}...")

                    # Scrape with retries
                    article_data = None
                    for retry in range(MAX_RETRIES):
                        article_data = await self.scrape_article(browser, url)
                        if article_data:
                            break
                        if retry < MAX_RETRIES - 1:
                            print(f"  Retry {retry + 1}/{MAX_RETRIES}...")
                            await asyncio.sleep(2)

                    if article_data:
                        saved_path = await self.save_article(article_data)
                        if saved_path:
                            self.saved_count += 1
                            headline_preview = article_data['headline'][:50]
                            print(f"  ✓ Saved: {headline_preview}...")
                            print(f"    → {saved_path}")
                        else:
                            self.failed_count += 1
                    else:
                        self.failed_count += 1
                        print(f"  ✗ Failed after {MAX_RETRIES} retries")

                    # Be polite
                    await asyncio.sleep(self.delay)

            finally:
                await browser.close()

        # Print summary
        print("\n" + "=" * 60)
        print("SCRAPING COMPLETE")
        print("=" * 60)
        print(f"✅ Successfully saved: {self.saved_count} articles")
        print(f"❌ Failed: {self.failed_count} articles")
        print(f"📁 Output directory: {self.output_dir.absolute()}")
        print("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description='Scrape articles from ilovemithila.com')
    parser.add_argument('--limit', type=int, default=None,
                        help='Maximum number of articles to scrape')
    parser.add_argument('--out', type=str, default=OUTPUT_DIR,
                        help=f'Output directory (default: {OUTPUT_DIR})')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY,
                        help=f'Delay between requests in seconds (default: {REQUEST_DELAY})')

    args = parser.parse_args()

    scraper = ArticleScraper(
        output_dir=args.out,
        delay=args.delay
    )

    await scraper.scrape_all(limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())