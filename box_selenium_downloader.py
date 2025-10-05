#!/usr/bin/env python3
"""
test_box_link_reader.py

This minimal script checks whether all file links are detected
on a Box shared folder page when running in headless mode (server).

Usage (local or GitHub Actions):
  python3 test_box_link_reader.py --share "https://.../folder/..."
"""

import argparse
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


def setup_driver(headless=True):
    """Set up Chrome WebDriver for server/headless environment."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=opts)
    return driver


def collect_all_links(driver, url):
    """Collect all file links from a Box folder page, waiting until DOM stabilizes."""
    driver.get(url)

    # Wait for at least one link to appear
    for _ in range(30):
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
        if anchors:
            break
        time.sleep(0.5)

    # --- Wait for DOM to stabilize (link count stops changing) ---
    last_count = 0
    stable_rounds = 0
    for _ in range(40):  # ~8 seconds max
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
        if len(anchors) == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = len(anchors)
        if stable_rounds >= 3:
            break
        time.sleep(0.2)
    # -------------------------------------------------------------

    # Optionally scroll to ensure lazy-loaded elements appear
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(8):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
    links = [a.get_attribute("href") for a in anchors if a.get_attribute("href")]
    return links


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--share", required=True, help="Box shared folder URL")
    args = p.parse_args()

    driver = setup_driver(headless=True)
    try:
        links = collect_all_links(driver, args.share)
        print(f"✅ Found {len(links)} file links on the page.")
        for i, link in enumerate(links, 1):
            print(f"{i:02d}: {link}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
