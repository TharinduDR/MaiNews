#!/usr/bin/env python3
"""
Selenium-based scraper - More reliable on shared Linux systems
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

BASE_URL = "https://www.ilovemithila.com"
OUTPUT_DIR = "articles"


def setup_driver():
    """Setup Chrome driver for headless operation"""
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # Try different driver paths
    driver = None
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.service import Service
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except:
        try:
            driver = webdriver.Chrome(options=options)
        except:
            print("Chrome driver not found. Installing...")
            os.system("pip install webdriver-manager")
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)

    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def scrape_articles(limit=None, output_dir=OUTPUT_DIR):
    """Main scraping function"""
    os.makedirs(output_dir, exist_ok=True)

    print("Setting up driver...")
    driver = setup_driver()

    try:
        print(f"Loading {BASE_URL}...")
        driver.get(BASE_URL)
        time.sleep(3)

        # Find article links
        print("Discovering articles...")
        article_urls = set()

        # Scroll to load more
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        # Find all links
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href")
            if href and "ilovemithila.com" in href:
                # Filter for article URLs
                if any(pattern in href for pattern in ['/20', '/news/', '/story/', '/poem/']):
                    if '?' not in href and '#comments' not in href:
                        if '/category/' not in href and '/tag/' not in href:
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
                driver.get(url)
                time.sleep(2)

                # Extract data
                article = {}
                article['url'] = url

                # Get headline
                try:
                    headline_elem = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "h1.entry-title, h1.post-title, article h1"))
                    )
                    article['headline'] = headline_elem.text.strip()
                except:
                    article['headline'] = ""

                # Get author
                try:
                    author_elem = driver.find_element(By.CSS_SELECTOR, ".author-name, .meta-author a")
                    article['author'] = author_elem.text.strip()
                except:
                    article['author'] = ""

                # Get date
                try:
                    date_elem = driver.find_element(By.CSS_SELECTOR, ".date.meta-item, time[datetime]")
                    article['date'] = date_elem.get_attribute("datetime") or date_elem.text.strip()
                except:
                    article['date'] = ""

                # Get content
                try:
                    content_elem = driver.find_element(By.CSS_SELECTOR, ".entry-content, .post-content")
                    content_html = content_elem.get_attribute('innerHTML')

                    # Clean content
                    soup = BeautifulSoup(content_html, 'lxml')

                    # Remove junk
                    junk_selectors = ['.mag-box', '.share-buttons', '#comments', 'script', 'style', 'ins']
                    for sel in junk_selectors:
                        for el in soup.select(sel):
                            el.decompose()

                    article['news_content'] = soup.get_text('\n', strip=True)
                    article['news_content'] = re.sub(r'\n{3,}', '\n\n', article['news_content'])
                except:
                    article['news_content'] = ""

                # Only save if we have content
                if article['headline'] and article['news_content']:
                    # Create filename
                    slug = re.sub(r'[^a-zA-Z0-9]', '_', article['headline'][:50])
                    filename = f"{slug}.json"
                    filepath = os.path.join(output_dir, filename)

                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(article, f, ensure_ascii=False, indent=2)

                    saved += 1
                    print(f"  ✓ Saved: {article['headline'][:50]}...")
                else:
                    failed += 1
                    print(f"  ✗ Insufficient data")

                time.sleep(1)

            except Exception as e:
                failed += 1
                print(f"  ✗ Error: {e}")
                continue

        print(f"\n✅ Completed: {saved} saved, {failed} failed")

    finally:
        driver.quit()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Number of articles to scrape')
    parser.add_argument('--out', default='articles', help='Output directory')
    args = parser.parse_args()

    scrape_articles(limit=args.limit, output_dir=args.out)