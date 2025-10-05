#!/usr/bin/env python3
"""
box_selenium_downloader.py

A headless Selenium-based downloader for public Box shared folders.
It can be executed locally or inside GitHub Actions CI.

Usage:
  python3 box_selenium_downloader.py --share "https://.../folder/..." --out ./downloads [--headless]
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

# Optional webdriver_manager fallback (only if local ChromeDriver is unavailable)
try:
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    WDM = True
except Exception:
    WDM = False


# ---------- LOGGER SETUP ----------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_stream_h = logging.StreamHandler()
_stream_h.setFormatter(_formatter)
logger.addHandler(_stream_h)


# ---------- UTILITIES ----------
def sanitize(name: str) -> str:
    """Replace filesystem-unfriendly characters in filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def setup_driver(download_dir, headless=False):
    """Create a Chrome WebDriver configured for headless file downloads."""
    opts = Options()

    if headless:
        opts.add_argument("--headless=new")  # new headless mode (Chrome >= 109)

    # These flags are necessary for stable execution in CI servers
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")

    # Configure Chrome's download behavior
    prefs = {
        "download.default_directory": os.path.abspath(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)

    # Try to launch Chrome, fallback to webdriver_manager if needed
    try:
        return webdriver.Chrome(options=opts)
    except Exception:
        if WDM:
            svc = ChromeService(ChromeDriverManager().install())
            return webdriver.Chrome(service=svc, options=opts)
        raise


# ---------- COLLECT LINKS ----------
def collect_links_on_page(driver, file_map):
    """Collect up to 20 file links from the current Box folder page."""
    base = driver.current_url
    anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
    for a in anchors[:20]:
        href = a.get_attribute("href")
        if not href:
            continue
        href = urljoin(base, href)
        key = href.split("?")[0]
        if key in file_map:
            continue
        name = a.text.strip() or a.get_attribute("aria-label") or os.path.basename(urlparse(href).path)
        file_map[key] = (href, sanitize(name))


# ---------- PAGINATION ----------
def click_next_page_aria(driver):
    """Try to click the 'Next page' button (handles multiple aria-label variants)."""
    xpaths = [
        "//button[@aria-label='Next page']",
        "//button[@aria-label='Next Page']",
        "//a[@aria-label='Next page']",
        "//a[@aria-label='Next Page']",
        "//button[contains(@aria-label, 'Next')]",
        "//a[contains(@aria-label, 'Next')]",
    ]
    for xp in xpaths:
        try:
            el = driver.find_element(By.XPATH, xp)
            if el.is_displayed() and el.is_enabled():
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", el)
                return True
        except Exception:
            continue
    return False


def wait_for_new_page(driver, prev_first_href, timeout=15):
    """Wait until the first file link changes (indicating a new page loaded)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
            if anchors:
                cur_first = anchors[0].get_attribute("href")
                if prev_first_href and cur_first != prev_first_href:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# ---------- FILE DOWNLOAD ----------
def click_download_in_viewer(driver):
    """Click the 'Download' button inside the Box file viewer."""
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
            time.sleep(0.1)
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            continue
    return False


def wait_for_download(out_path, timeout=600):
    """Wait until Chrome finishes downloading the file."""
    tmp = out_path + ".crdownload"
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(out_path) and not os.path.exists(tmp):
            return True
        time.sleep(1)
    return False


def download_via_browser(driver, links_map, out_dir):
    """Open each file link, click 'Download', and wait until the download completes."""
    os.makedirs(out_dir, exist_ok=True)

    success, skipped, failed = 0, 0, []

    for key, (href, name) in links_map.items():
        out_path = os.path.join(out_dir, name)

        if os.path.exists(out_path):
            logger.info("[skip] %s", name)
            skipped += 1
            continue

        logger.info("[download] %s", name)

        for attempt in range(3):
            try:
                driver.get(href)
                if click_download_in_viewer(driver):
                    if wait_for_download(out_path, timeout=600):
                        logger.info(" -> done: %s", name)
                        success += 1
                        break
                logger.warning(" -> retrying %s", name)
                time.sleep(2)
            except Exception as e:
                logger.warning(" -> error: %s", e)
                time.sleep(2)
        else:
            failed.append(name)
            logger.error(" -> failed: %s", name)

    logger.info("=" * 50)
    logger.info("Total: %d | Downloaded: %d | Skipped: %d | Failed: %d",
                len(links_map), success, skipped, len(failed))
    if failed:
        logger.info("Failed files: %s", failed)
    logger.info("=" * 50)


# ---------- MAIN EXECUTION ----------
def download_shared_folder_with_aria(share_url, out_dir, headless=False):
    """Navigate through all folder pages and download each file."""
    logger.info("Starting download from %s", share_url)
    driver = setup_driver(out_dir, headless=headless)

    try:
        driver.get(share_url)
        WebDriverWait(driver, 15).until(lambda d: d.find_elements(By.XPATH, "//a[contains(@href, '/file/')]"))

        file_map = {}
        page_idx = 1

        while True:
            logger.info("[page %d] collecting links...", page_idx)
            collect_links_on_page(driver, file_map)
            logger.info(" -> total collected: %d", len(file_map))

            try:
                first = driver.find_element(By.XPATH, "//a[contains(@href, '/file/')]")
                first_href = first.get_attribute("href")
            except Exception:
                first_href = None

            if not click_next_page_aria(driver):
                logger.info(" -> no Next button found — end of pages.")
                break

            if not wait_for_new_page(driver, first_href):
                logger.warning(" -> page didn't update; stopping.")
                break

            page_idx += 1
            time.sleep(1)

        logger.info("[collected] %d files total; starting downloads...", len(file_map))
        download_via_browser(driver, file_map, out_dir)
        logger.info("Done.")

    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ---------- CLI ENTRY POINT ----------
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--share", required=True, help="Box shared folder URL")
    p.add_argument("--out", default="./downloads", help="Output directory")
    p.add_argument("--headless", action="store_true", help="Run in headless mode (for servers)")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, "downloader.log")
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(_formatter)
    logger.addHandler(fh)

    try:
        download_shared_folder_with_aria(args.share, args.out, headless=args.headless)
    except Exception:
        logger.exception("Fatal error during execution")
