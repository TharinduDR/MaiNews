#!/usr/bin/env python3
"""
Playwright scraper that uses pre-installed Chromium
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

# IMPORTANT: Tell Playwright NOT to download its own browser
os.environ['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '1'
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path.home() / '.cache' / 'ms-playwright')

# Path to pre-installed Chrome
CHROME_BIN = os.environ.get('CHROME_BIN', str(Path.home() / '.local/chrome/chrome-linux64/chrome'))
os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH'] = CHROME_BIN


async def setup_playwright():
    """Setup Playwright without downloading browser"""
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        print("Installing playwright...")
        os.system(f"{sys.executable} -m pip install --user playwright")
        from playwright.async_api import async_playwright
        return async_playwright


async def scrape_articles(limit=None, output_dir="articles"):
    """Main scraping function"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ilovemithila.com Article Scraper")
    print("=" * 60)
    print(f"Output: {output_path.absolute()}")
    print(f"Using Chrome: {CHROME_BIN}")
    print(f"Chrome exists: {os.path.exists(CHROME_BIN)}")
    print()

    # Setup Playwright
    playwright_module = await setup_playwright()

    async with playwright_module() as p:
        # Launch browser with pre-installed Chromium
        print("Launching browser...")

        # Check if Chrome exists
        if not os.path.exists(CHROME_BIN):
            print(f"ERROR: Chrome not found at {CHROME_BIN}")
            print("Please install Chrome first using the SLURM script")
            return 0

        browser = await p.chromium.launch(
            headless=True,
            executable_path=CHROME_BIN,  # Use pre-installed Chrome
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-extensions',
                '--disable-background-networking',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--metrics-recording-only',
                '--mute-audio',
                '--no-first-run',
                '--safebrowsing-disable-auto-update',
            ]
        )

        print("✓ Browser launched successfully!")

        try:
            # Create context with realistic viewport
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            page = await context.new_page()

            # Navigate to homepage
            print("Loading homepage...")
            await page.goto('https://www.ilovemithila.com', wait_until='networkidle', timeout=30000)

            # Scroll to load more content
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)

            # Extract article URLs
            print("Discovering articles...")
            urls = await page.evaluate('''
                () => {
                    const links = new Set();
                    const patterns = ['/20', '/news/', '/story/', '/poem/'];

                    document.querySelectorAll('a[href]').forEach(link => {
                        const href = link.href;
                        if (href && href.includes('ilovemithila.com')) {
                            let matches = false;
                            for (const p of patterns) {
                                if (href.includes(p)) {
                                    matches = true;
                                    break;
                                }
                            }
                            if (matches && !href.includes('?') && !href.includes('#comments')) {
                                if (!href.includes('/category/') && !href.includes('/tag/')) {
                                    links.add(href);
                                }
                            }
                        }
                    });
                    return Array.from(links);
                }
            ''')

            print(f"Found {len(urls)} article URLs")

            if limit:
                urls = urls[:limit]

            saved = 0
            failed = 0

            for idx, url in enumerate(urls, 1):
                print(f"\n[{idx}/{len(urls)}] {url[:80]}...")

                try:
                    # Navigate to article
                    await page.goto(url, wait_until='networkidle', timeout=30000)
                    await asyncio.sleep(1)

                    # Extract article data
                    article = await page.evaluate('''
                        () => {
                            let headline = '';
                            const h1 = document.querySelector('h1.entry-title, h1.post-title, article h1');
                            if (h1) headline = h1.innerText.trim();

                            let author = '';
                            const authorEl = document.querySelector('.author-name, .meta-author a');
                            if (authorEl) author = authorEl.innerText.trim();

                            let date = '';
                            const dateMeta = document.querySelector('meta[property="article:published_time"]');
                            if (dateMeta) date = dateMeta.content;
                            if (!date) {
                                const dateEl = document.querySelector('.date.meta-item, time');
                                if (dateEl) date = dateEl.innerText.trim();
                            }

                            let content = '';
                            const contentEl = document.querySelector('.entry-content, .post-content, article');
                            if (contentEl) {
                                const clone = contentEl.cloneNode(true);
                                const junkSelectors = ['.mag-box', '.sharedaddy', '.share-buttons', '#comments', 'script', 'style', 'ins', 'iframe'];
                                junkSelectors.forEach(sel => {
                                    clone.querySelectorAll(sel).forEach(el => el.remove());
                                });
                                content = clone.innerText.trim();
                                content = content.replace(/\\n{3,}/g, '\\n\\n');
                            }

                            return {headline, author, date, content};
                        }
                    ''')

                    if article['headline'] and article['content']:
                        # Create filename
                        slug = re.sub(r'[^\w\s-]', '', article['headline'])
                        slug = re.sub(r'[-\s]+', '-', slug)[:50]
                        slug = slug or f"article_{idx}"

                        article_data = {
                            'url': url,
                            'headline': article['headline'],
                            'author': article['author'],
                            'date': article['date'],
                            'news_content': article['content'],
                        }

                        filepath = output_path / f"{slug}.json"
                        with open(filepath, 'w', encoding='utf-8') as f:
                            json.dump(article_data, f, ensure_ascii=False, indent=2)

                        saved += 1
                        print(f"  ✓ Saved: {article['headline'][:50]}...")
                    else:
                        failed += 1
                        print(f"  ✗ No content found")

                    await asyncio.sleep(1.5)

                except Exception as e:
                    failed += 1
                    print(f"  ✗ Error: {str(e)[:100]}")
                    continue

            print(f"\n" + "=" * 60)
            print(f"✅ Complete: {saved} saved, {failed} failed")
            print(f"📁 Output: {output_path.absolute()}")

        finally:
            await browser.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Number of articles to scrape')
    parser.add_argument('--out', default='articles', help='Output directory')
    args = parser.parse_args()

    asyncio.run(scrape_articles(limit=args.limit, output_dir=args.out))


if __name__ == "__main__":
    main()