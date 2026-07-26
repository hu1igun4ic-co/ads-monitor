import json
import re
import hashlib
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

CIAN_URL = "https://tomsk.cian.ru/cat.php?deal_type=sale&engine_version=2&offer_type=flat&region=5016&totime=-2"
RU09_URL = "https://www.tomsk.ru09.ru/realty/?otype=1&type=1"
SIBDOM_URL = "https://tomsk.sibdom.ru/kvartiry/prodam_tomsk_ot-sobstvennika/"

DATA_FILE = "data.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


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


# ---------- ЦИАН (нужен JS, используем Playwright) ----------

def parse_cian(page):
    results = []
    try:
        page.goto(CIAN_URL, timeout=60000)
        page.wait_for_timeout(6000)
        title = page.title()
        print(f"[Циан] Заголовок страницы: {title}")

        cards = page.query_selector_all('[data-name="CardComponent"]')
        print(f"[Циан] Найдено карточек: {len(cards)}")

        for c in cards:
            try:
                link_el = c.query_selector('a[data-name="CardComponentLink"]') or c.query_selector('a[href*="cian.ru/sale/flat"]')
                if not link_el:
                    continue
                url = link_el.get_attribute("href")
                title_el = c.query_selector('[data-mark="OfferTitle"]')
                title_text = title_el.inner_text().strip() if title_el else link_el.inner_text().strip()
                price_el = c.query_selector('[data-mark="MainPrice"]')
                price = price_el.inner_text().strip() if price_el else ""
                results.append({
                    "id": make_id("cian", url),
                    "source": "ЦИАН",
                    "title": title_text,
                    "price": price,
                    "url": url,
                })
            except Exception as e:
                print("[Циан] Ошибка карточки:", e)
    except Exception as e:
        print("[Циан] Ошибка страницы:", e)
    print(f"[Циан] ИТОГО: {len(results)}")
    return results


# ---------- ru09.ru (обычный HTML, requests хватает) ----------

def parse_ru09():
    results = []
    try:
        r = requests.get(RU09_URL, headers=HEADERS, timeout=30)
        print(f"[ru09] Статус ответа: {r.status_code}")
        r.encoding = "windows-1251"
        soup = BeautifulSoup(r.text, "html.parser")

        links = soup.find_all("a", href=re.compile(r"subaction=detail&id=\d+"))
        print(f"[ru09] Найдено ссылок на объявления: {len(links)}")

        seen_ids = set()
        for link in links:
            href = link.get("href")
            m = re.search(r"id=(\d+)", href)
            if not m:
                continue
            item_id = m.group(1)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            full_url = href if href.startswith("http") else "https://www.tomsk.ru09.ru" + href
            title_text = link.get_text(strip=True)
            if not title_text:
                continue

            # Цена — ищем рядом в родительском блоке
            price = ""
            parent = link.find_parent()
            if parent:
                price_match = re.search(r"[\d\s]{4,}\s*т\.р\.|[\d\s]{4,}\s*руб", parent.get_text())
                if price_match:
                    price = price_match.group(0).strip()

            results.append({
                "id": make_id("ru09", full_url),
                "source": "RU09",
                "title": title_text,
                "price": price,
                "url": full_url,
            })

        if len(links) == 0:
            print("[ru09] HTML-фрагмент для диагностики:")
            print(r.text[:1500])
    except Exception as e:
        print("[ru09] Ошибка:", e)
    print(f"[ru09] ИТОГО: {len(results)}")
    return results


# ---------- sibdom.ru (обычный HTML, requests хватает) ----------

def parse_sibdom():
    results = []
    try:
        r = requests.get(SIBDOM_URL, headers=HEADERS, timeout=30)
        print(f"[Sibdom] Статус ответа: {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")

        links = soup.find_all("a", href=re.compile(r"/stickers/view/\d+"))
        print(f"[Sibdom] Найдено ссылок на объявления: {len(links)}")

        seen_ids = set()
        for link in links:
            href = link.get("href")
            m = re.search(r"/stickers/view/(\d+)", href)
            if not m:
                continue
            item_id = m.group(1)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            full_url = href if href.startswith("http") else "https://tomsk.sibdom.ru" + href
            full_text = link.get_text(strip=True)
            if not full_text:
                continue

            price_match = re.search(r"[\d\s]{5,}\s*₽", full_text)
            price = price_match.group(0).strip() if price_match else ""

            title_match = re.match(r"^(.*?квартира[^0-9]*\d[.,]?\d*\s*м²)", full_text)
            title_text = title_match.group(1).strip() if title_match else full_text[:80]

            results.append({
                "id": make_id("sibdom", full_url),
                "source": "Сибдом",
                "title": title_text,
                "price": price,
                "url": full_url,
            })

        if len(links) == 0:
            print("[Sibdom] HTML-фрагмент для диагностики:")
            print(r.text[:1500])
    except Exception as e:
        print("[Sibdom] Ошибка:", e)
    print(f"[Sibdom] ИТОГО: {len(results)}")
    return results


def main():
    existing = load_existing()
    existing_ids = {item["id"] for item in existing}
    existing_by_id = {item["id"]: item for item in existing}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="ru-RU")
        cian_items = parse_cian(page)
        browser.close()

    ru09_items = parse_ru09()
    sibdom_items = parse_sibdom()

    fresh = cian_items + ru09_items + sibdom_items

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
    print(f"ВСЕГО объявлений сохранено: {len(merged)}, новых за этот запуск: {sum(1 for i in merged if i['id'] not in existing_ids)}")


if __name__ == "__main__":
    main()
