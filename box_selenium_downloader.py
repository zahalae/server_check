#!/usr/bin/env python3
"""
box_selenium_downloader_singlepage.py

Usage:
  python3 box_selenium_downloader_singlepage.py --share "https://.../folder/..." --out ./downloads [--headless]

"""

import os
import time
import argparse
import re
import logging
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# webdriver_manager fallback (optional)
try:
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    WDM = True
except Exception:
    WDM = False


# ---------- logger ----------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_stream_h = logging.StreamHandler()
_stream_h.setFormatter(_formatter)
logger.addHandler(_stream_h)


# ---------- utilities ----------
def sanitize(name: str) -> str:
    """Replace filesystem-unfriendly characters in filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def setup_driver(download_dir, headless=False):
    """Create a Chrome WebDriver with download directory configured."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    prefs = {
        "download.default_directory": os.path.abspath(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)

    try:
        return webdriver.Chrome(options=opts)
    except Exception:
        if WDM:
            svc = ChromeService(ChromeDriverManager().install())
            return webdriver.Chrome(service=svc, options=opts)
        raise


# ---------- collect links ----------
def collect_links_on_page(driver, file_map):
    """Collect file links on the current page and store in file_map."""

    # Try to scroll inside the main file list container
    try:
        scrollable = driver.find_element(By.XPATH, "//div[contains(@class, 'scroll')]")
    except Exception:
        scrollable = driver.find_element(By.TAG_NAME, "body")

    last_height = driver.execute_script("return arguments[0].scrollHeight", scrollable)
    while True:
        driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable)
        time.sleep(0.5)
        new_height = driver.execute_script("return arguments[0].scrollHeight", scrollable)
        if new_height == last_height:
            break
        last_height = new_height

    base = driver.current_url
    anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        href = urljoin(base, href)
        key = href.split("?")[0]
        if key in file_map:
            continue
        name = a.text.strip() or a.get_attribute("aria-label") or os.path.basename(urlparse(href).path)
        name = sanitize(name)
        file_map[key] = (href, name)


# ---------- download ----------
def click_download_in_viewer(driver):
    """Click the Download button in Box file viewer."""
    xpaths = [
        "//button[contains(normalize-space(.), 'Download')]",
        "//a[contains(normalize-space(.), 'Download')]",
        "//button[@aria-label='Download']",
        "//a[@aria-label='Download']",
    ]
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].scrollIntoView(true);", el)
            time.sleep(0.08)
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            continue
    return False


def wait_for_download(out_path, timeout=600):
    """Wait until Chrome finishes downloading a file."""
    download_tmp = out_path + ".crdownload"
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(out_path) and not os.path.exists(download_tmp):
            return True
        time.sleep(1)
    return False


def download_via_browser(driver, links_map, out_dir):
    """Iterate over collected file links and download them."""
    os.makedirs(out_dir, exist_ok=True)

    MAX_ATTEMPTS = 3
    ATTEMPT_TIMEOUT = 60
    DOWNLOAD_TIMEOUT = 600

    success_count = 0
    skip_count = 0
    fail_count = 0
    failed_files = []

    for key, (href, name) in links_map.items():
        out_path = os.path.join(out_dir, name)
        tmp_file = out_path + ".crdownload"

        if os.path.exists(out_path):
            logger.info("[skip] exists: %s", name)
            skip_count += 1
            continue

        logger.info("[download] %s", name)
        downloaded = False

        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(" -> attempt %d", attempt)
            try:
                driver.get(href)
            except Exception:
                logger.exception("Failed to open href: %s", href)
                continue

            clicked = click_download_in_viewer(driver)
            if not clicked:
                logger.warning(" -> download button not found, refreshing page")
                driver.refresh()
                time.sleep(2)
                continue

            start_time = time.time()
            started = False
            while time.time() - start_time < ATTEMPT_TIMEOUT:
                if os.path.exists(out_path) or os.path.exists(tmp_file):
                    started = True
                    break
                time.sleep(1)

            if not started:
                logger.warning(" -> no download started within %d sec, retrying...", ATTEMPT_TIMEOUT)
                driver.refresh()
                time.sleep(2)
                continue

            ok = wait_for_download(out_path, timeout=DOWNLOAD_TIMEOUT)
            if ok:
                logger.info(" -> done: %s", name)
                success_count += 1
                downloaded = True
                break
            else:
                logger.warning(" -> timeout, retrying after refresh: %s", name)
                driver.refresh()
                time.sleep(2)

        if not downloaded:
            fail_count += 1
            failed_files.append(name)
            logger.error(" -> failed after %d attempts: %s", MAX_ATTEMPTS, name)

    logger.info("=" * 55)
    logger.info("SUMMARY")
    logger.info("Total files found: %d", len(links_map))
    logger.info("Downloaded: %d", success_count)
    logger.info("Skipped (already exist): %d", skip_count)
    logger.info("Failed: %d", fail_count)
    if failed_files:
        logger.info("Failed files: %s", failed_files)
    logger.info("=" * 55)


# ---------- main ----------
def download_one_page(share_url, out_dir, headless=False):
    logger.info("Starting single-page test; share_url=%s out_dir=%s headless=%s", share_url, out_dir, headless)
    driver = setup_driver(out_dir, headless=headless)
    try:
        driver.get(share_url)
        WebDriverWait(driver, 15).until(lambda d: d.find_elements(By.XPATH, "//a[contains(@href, '/file/')]"))

        file_map = {}
        logger.info("[single page] collecting links on %s", driver.current_url)
        collect_links_on_page(driver, file_map)
        logger.info(" -> collected: %d files", len(file_map))

        download_via_browser(driver, file_map, out_dir)
        logger.info("Done (single page mode).")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ---------- CLI ----------
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--share", required=True, help="Box shared folder URL")
    p.add_argument("--out", default="./downloads", help="Output directory")
    p.add_argument("--headless", action="store_true", help="Run headless")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, "downloader.log")
    file_h = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_h.setFormatter(_formatter)
    logger.addHandler(file_h)

    try:
        download_one_page(args.share, args.out, headless=args.headless)
    except Exception:
        logger.exception("Fatal error during execution")
