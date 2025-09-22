#!/usr/bin/env python3
"""
box_selenium_downloader_aria.py

Usage:
  python3 box_selenium_downloader_aria.py --share "https://.../folder/..." --out ./data [--headless]

Notes:
- For debugging run without --headless so you can see clicks.
- Requires: selenium, webdriver-manager (optional, used if chromedriver not in PATH).
"""

import os
import time
import argparse
import re
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


# ---------- aria-only pagination ----------
def click_next_page_aria(driver):
    """Try clicking the aria-label='Next page' element."""
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
                time.sleep(0.08)
                driver.execute_script("arguments[0].click();", el)
                return True
        except Exception:
            continue
    return False


def wait_for_new_page(driver, prev_first_href, timeout=12):
    """Wait until the first file link changes (page switched)."""
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
        time.sleep(0.4)
    return False


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
    """
    Wait until Chrome finishes downloading a file.
    Chrome creates .crdownload temporary files while downloading.
    """
    download_tmp = out_path + ".crdownload"
    start = time.time()
    while time.time() - start < timeout:
        # if final file exists and no .crdownload → done
        if os.path.exists(out_path) and not os.path.exists(download_tmp):
            return True
        time.sleep(1)
    return False


def download_via_browser(driver, links_map, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for key, (href, name) in links_map.items():
        out_path = os.path.join(out_dir, name)
        if os.path.exists(out_path):
            print(f"[skip] exists: {name}")
            continue

        print(f"[download] {name}")
        driver.get(href)
        clicked = click_download_in_viewer(driver)
        if clicked:
            print(" -> waiting for file to finish...")
            ok = wait_for_download(out_path, timeout=600)
            if ok:
                print(f" -> done: {name}")
            else:
                print(f" -> timeout, file not fully downloaded: {name}")
        else:
            print(" -> download button not found")


# ---------- main ----------
def download_shared_folder_with_aria(share_url, out_dir, headless=False):
    driver = setup_driver(out_dir, headless=headless)
    try:
        driver.get(share_url)
        WebDriverWait(driver, 15).until(lambda d: d.find_elements(By.XPATH, "//a[contains(@href, '/file/')]"))
        file_map = {}
        page_idx = 1
        while True:
            print(f"[page {page_idx}] collecting links on {driver.current_url}")
            collect_links_on_page(driver, file_map)
            print(f" -> total collected: {len(file_map)}")

            # remember first href to detect change
            try:
                first = driver.find_element(By.XPATH, "//a[contains(@href, '/file/')]")
                first_href = first.get_attribute("href")
            except Exception:
                first_href = None

            clicked = click_next_page_aria(driver)
            if not clicked:
                print(" -> aria Next not found — assuming last page.")
                break

            changed = wait_for_new_page(driver, first_href, timeout=12)
            if not changed:
                print(" -> clicked aria but page didn't update within timeout; waiting and continuing.")
                time.sleep(2)
            page_idx += 1
            time.sleep(0.6)

        print(f"[collected] {len(file_map)} files total; starting downloads...")
        download_via_browser(driver, file_map, out_dir)
        print("Done.")
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

    download_shared_folder_with_aria(args.share, args.out, headless=args.headless)