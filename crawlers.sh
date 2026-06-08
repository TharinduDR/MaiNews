#!/bin/bash
#SBATCH --partition=cpu-48h
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=t.ranasinghe@lancaster.ac.uk
#SBATCH --job-name=scrape_news
#SBATCH --output=scrape_%j.out
#SBATCH --error=scrape_%j.err
#SBATCH --time=02:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=4

# Set up Chrome directory
export CHROME_DIR="${HOME}/.local/chrome"
export CHROME_BIN="${CHROME_DIR}/chrome-linux64/chrome"
export PLAYWRIGHT_BROWSERS_PATH="${HOME}/.cache/ms-playwright"

# Create directories
mkdir -p "${CHROME_DIR}"
mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}"

echo "=== Installing Chromium for Playwright ==="
echo "Chrome dir: ${CHROME_DIR}"
echo "Playwright browsers path: ${PLAYWRIGHT_BROWSERS_PATH}"

# Try multiple download sources
download_chrome() {
    echo "Attempting to download Chromium..."

    # Source 1: Google Chrome for Testing (original)
    echo "Trying Google CDN..."
    wget --timeout=30 --tries=2 -q --show-progress \
        https://storage.googleapis.com/chrome-for-testing-public/latest/linux64/chrome-linux64.zip && return 0

    # Source 2: Alternative mirror
    echo "Trying alternative mirror..."
    wget --timeout=30 --tries=2 -q --show-progress \
        https://www.googleapis.com/download/storage/v1/b/chrome-for-testing-public/o/chrome-linux64.zip\?alt=media && return 0

    # Source 3: Use Playwright's own download (might work better)
    echo "Trying Playwright's built-in download..."
    python3 -c "
import sys
sys.path.insert(0, f'{HOME}/.local/lib/python*/site-packages')
try:
    from playwright.__main__ import main
    import sys
    sys.argv = ['playwright', 'install', 'chromium']
    main()
except:
    pass
" && return 0

    return 1
}

# Download Chromium if not already present
if [ ! -f "${CHROME_BIN}" ]; then
    if download_chrome; then
        if [ -f "chrome-linux64.zip" ]; then
            echo "Extracting Chromium..."
            unzip -q chrome-linux64.zip
            rm chrome-linux64.zip
            chmod +x chrome-linux64/chrome
            echo "✓ Chromium installed at ${CHROME_BIN}"
        elif [ -d "chrome-linux64" ]; then
            echo "✓ Chromium already extracted"
        else
            echo "Download failed, trying Playwright method..."
            python3 -m playwright install chromium
        fi
    else
        echo "All download methods failed. Trying Playwright directly..."
        python3 -m playwright install chromium
    fi
else
    echo "✓ Chromium already exists"
fi

# Check if Chrome was installed
if [ -f "${CHROME_BIN}" ]; then
    echo "✓ Chrome found at ${CHROME_BIN}"
    ${CHROME_BIN} --version
else
    echo "⚠ Chrome not found. Will use Playwright's bundled browser."
    # Let Playwright use its own browser
    unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
fi

# Set environment variables
export PLAYWRIGHT_BROWSERS_PATH="${HOME}/.cache/ms-playwright"

echo "=== Installing Python packages ==="
pip install --user playwright beautifulsoup4 lxml

# Run Playwright install if needed
python3 -m playwright install chromium 2>/dev/null || true

echo "=== Starting scraper ==="
python -m crawlers.ilovemithila_scraper --out articles_ilovemithila

echo "=== Done ==="