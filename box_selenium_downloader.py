"""
box_selenium_downloader_aria_test_one.py

Minimal single-page verifier: prints how many file links were detected on the first page.
Usage:
  python3 box_selenium_downloader_aria_test_one.py --share "https://.../folder/..." [--headless]
"""
import os
import argparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from urllib.parse import urljoin, urlparse
import re
import time

def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def setup_driver(headless=False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    return webdriver.Chrome(options=opts)

def collect_links_on_page(driver):
    base = driver.current_url

    target_count = 20
    last_count = -1
    stable_ticks = 0
    start = time.time()
    while time.time() - start < 10:
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]")
        count = len(anchors)
        if count >= target_count:
            break
        if count == last_count:
            stable_ticks += 1
        else:
            stable_ticks = 0
            last_count = count

        try:
            driver.execute_script("window.scrollBy(0, Math.max(500, Math.floor(window.innerHeight*0.9)));")
        except Exception:
            pass
        try:
            driver.execute_script("""
                (function(){
                  var els = document.querySelectorAll('*');
                  for (var i=0;i<els.length;i++){
                    var e = els[i];
                    var ch = e.clientHeight || 0;
                    var sh = e.scrollHeight || 0;
                    if (ch > 0 && sh > ch + 10) e.scrollTop = sh;
                  }
                })();
            """)
        except Exception:
            pass
        try:
            if count > 0:
                for a in anchors[max(0, count-3):]:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", a)
        except Exception:
            pass

        time.sleep(0.2 if stable_ticks < 3 else 0.35)
        if stable_ticks >= 5:
            break

    result = []
    for a in driver.find_elements(By.XPATH, "//a[contains(@href, '/file/')]"):
        href = a.get_attribute("href")
        if not href:
            continue
        href = urljoin(base, href)
        name = a.text.strip() or a.get_attribute("aria-label") or os.path.basename(urlparse(href).path)
        result.append((href, sanitize(name)))
    return result

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", required=True)
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    d = setup_driver(headless=args.headless)
    try:
        d.get(args.share)
        WebDriverWait(d, 15).until(lambda drv: drv.find_elements(By.XPATH, "//a[contains(@href, '/file/')]"))
        links = collect_links_on_page(d)
        print(f"Detected links: {len(links)}")
        for i, (_, name) in enumerate(links, 1):
            print(f"{i:02d}. {name}")
    finally:
        try:
            d.quit()
        except Exception:
            pass
