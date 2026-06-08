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

# Download Chromium if not already present
if [ ! -f "${CHROME_BIN}" ]; then
    echo "Downloading Chromium..."
    cd "${CHROME_DIR}" || exit

    # Download Chromium
    wget -q --show-progress https://storage.googleapis.com/chrome-for-testing-public/latest/linux64/chrome-linux64.zip

    if [ -f "chrome-linux64.zip" ]; then
        echo "Extracting Chromium..."
        unzip -q chrome-linux64.zip
        rm chrome-linux64.zip
        chmod +x chrome-linux64/chrome
        echo "✓ Chromium installed at ${CHROME_BIN}"
    else
        echo "Failed to download Chromium"
        exit 1
    fi
else
    echo "✓ Chromium already exists"
fi

# Download ChromeDriver
if [ ! -f "${CHROME_DIR}/chromedriver-linux64/chromedriver" ]; then
    echo "Downloading ChromeDriver..."
    cd "${CHROME_DIR}" || exit
    wget -q --show-progress https://storage.googleapis.com/chrome-for-testing-public/latest/linux64/chromedriver-linux64.zip
    unzip -q chromedriver-linux64.zip
    rm chromedriver-linux64.zip
    chmod +x chromedriver-linux64/chromedriver
    echo "✓ ChromeDriver installed"
fi

# Set environment variables for Playwright to use system Chrome
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="${CHROME_BIN}"
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

echo "=== Environment ==="
echo "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH: ${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH}"
echo "PLAYWRIGHT_BROWSERS_PATH: ${PLAYWRIGHT_BROWSERS_PATH}"

# Verify Chrome works
echo "=== Testing Chrome ==="
${CHROME_BIN} --version || echo "Chrome binary not found at ${CHROME_BIN}"

# Install playwright without downloading browser
echo "=== Installing Python packages ==="
pip install --user playwright beautifulsoup4 lxml

# Now run your Python script
echo "=== Starting scraper ==="
python -m crawlers.ilovemithila_scraper --out articles_ilovemithila

echo "=== Done ==="