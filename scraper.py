import json
import hashlib
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

AVITO_URL = "https://www.avito.ru/tomsk/kvartiry/prodam/ipoteka-ASgBAgICAkSSA8YQ5usOAg?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6IjFrSFpCb0xLUTFSWEE2Q2YiO30YGu8eJgAAAA&f=ASgBAQICA0SSA8YQkL4Nlq415usOAgJAygjE_M8yilmarAGYrAGWrAGUrAGIWYZZhFmCWYBZ_ljAwQ0kvP03uv03"
CIAN_URL = "https://tomsk.cian.ru/cat.php?deal_type=sale&engine_version=2&offer_type=flat&region=5016&totime=-2"

DATA_FILE = "data.json"


def load_existing():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save(items):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def make_id(source, url):
    return hashlib.md5(f"{source}:{url}".encode()).hexdigest()


def parse_avito(page):
    results = []
    try:
        page.goto(AVITO_URL, timeout=60000)
        page.wait_for_timeout(5000)
        cards = page.query_selector_all('[data-marker="item"]')
        for c in cards:
            try:
                link_el = c.query_selector('a[data-marker="item-title"]')
                if not link_el:
                    continue
                href = link_el.get_attribute("href")
                url = "https://www.avito.ru" + href if href.startswith("/") else href
                title = link_el.inner_text().strip()
                price_el = c.query_selector('[itemprop="price"]') or c.query_selector('[data-marker="item-price"]')
                price = price_el.inner_text().strip() if price_el else ""
                results.append({
                    "id": make_id("avito", url),
                    "source": "Avito",
                    "title": title,
                    "price": price,
                    "url": url,
                })
            except Exception as e:
                print("Avito card error:", e)
    except Exception as e:
        print("Avito page error:", e)
    return results


def parse_cian(page):
    results = []
    try:
        page.goto(CIAN_URL, timeout=60000)
        page.wait_for_timeout(5000)
        cards = page.query_selector_all('[data-name="CardComponent"]')
        for c in cards:
            try:
                link_el = c.query_selector('a[data-name="CardComponentLink"] , a[href*="cian.ru/sale/flat"]')
                if not link_el:
                    continue
                url = link_el.get_attribute("href")
                title_el = c.query_selector('[data-mark="OfferTitle"]')
                title = title_el.inner_text().strip() if title_el else link_el.inner_text().strip()
                price_el = c.query_selector('[data-mark="MainPrice"]')
                price = price_el.inner_text().strip() if price_el else ""
                results.append({
                    "id": make_id("cian", url),
                    "source": "ЦИАН",
                    "title": title,
                    "price": price,
                    "url": url,
                })
            except Exception as e:
                print("Cian card error:", e)
    except Exception as e:
        print("Cian page error:", e)
    return results


def main():
    existing = load_existing()
    existing_ids = {item["id"] for item in existing}
    existing_by_id = {item["id"]: item for item in existing}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )

        fresh = parse_avito(page) + parse_cian(page)
        browser.close()

    now = datetime.now(timezone.utc).isoformat()
    merged = []
    for item in fresh:
        if item["id"] in existing_by_id:
            old = existing_by_id[item["id"]]
            item["first_seen"] = old.get("first_seen", now)
        else:
            item["first_seen"] = now
        merged.append(item)

    merged.sort(key=lambda x: x["first_seen"], reverse=True)
    save(merged)
    print(f"Всего объявлений: {len(merged)}, новых за этот запуск: {sum(1 for i in merged if i['id'] not in existing_ids)}")


if __name__ == "__main__":
    main()
