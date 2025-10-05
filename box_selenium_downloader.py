
#!/usr/bin/env python3
import argparse
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def setup_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=opts)

def collect_all_links(driver, url):
    driver.get(url)

    for _ in range(30):
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
        if anchors:
            break
        time.sleep(0.5)

    last_count = 0
    stable_rounds = 0
    for _ in range(40):
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
        if len(anchors) == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = len(anchors)
        if stable_rounds >= 3:
            break
        time.sleep(0.2)

    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(8):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
    return [a.get_attribute("href") for a in anchors if a.get_attribute("href")]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--share", required=True)
    p.add_argument("--out", default="./downloads")     # ← added dummy argument
    p.add_argument("--headless", action="store_true")  # ← added dummy argument
    args = p.parse_args()

    driver = setup_driver(headless=args.headless)
    try:
        links = collect_all_links(driver, args.share)
        print(f"✅ Found {len(links)} file links on the page.")
        for i, link in enumerate(links, 1):
            print(f"{i:02d}: {link}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
