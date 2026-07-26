import os
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

                geo_els = c.query_selector_all('a[data-name="GeoLabel"]')
                address_parts = [g.inner_text().strip() for g in geo_els if g.inner_text().strip()]
                address = ", ".join(address_parts)

                full_title = f"{title_text} — {address}" if address else title_text

                price_el = c.query_selector('[data-mark="MainPrice"]')
                price = price_el.inner_text().strip() if price_el else ""
                results.append({
                    "id": make_id("cian", url),
                    "source": "ЦИАН",
                    "title": full_title,
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

        title_pattern = re.compile(r"(\d-комнатн|Студия|комната)", re.IGNORECASE)
        links = soup.find_all("a", href=re.compile(r"subaction=detail&id=\d+"))
        print(f"[ru09] Всего ссылок на объявления (все виды): {len(links)}")

        seen_ids = set()
        for link in links:
            text = link.get_text(strip=True)
            if not title_pattern.search(text):
                continue

            href = link.get("href")
            m = re.search(r"id=(\d+)", href)
            if not m:
                continue
            item_id = m.group(1)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            full_url = href if href.startswith("http") else "https://www.tomsk.ru09.ru" + href

            price = ""
            address = ""
            block = link
            for _ in range(4):
                block = block.find_parent()
                if block is None:
                    break
                strong = block.find(["strong", "b"])
                if strong and not price:
                    digits = re.sub(r"\D", "", strong.get_text())
                    if 3 <= len(digits) <= 6:
                        price = f"{int(digits):,} тыс.руб.".replace(",", " ")
                map_link = block.find("a", href=re.compile(r"/map/#l="))
                if map_link and not address:
                    address = map_link.get_text(strip=True)
                if price and address:
                    break

            full_title = f"{text} — {address}" if address else text

            results.append({
                "id": make_id("ru09", full_url),
                "source": "RU09",
                "title": full_title,
                "price": price,
                "url": full_url,
            })

        if not results:
            print("[ru09] HTML-фрагмент для диагностики:")
            print(r.text[:1500])
    except Exception as e:
        print("[ru09] Ошибка:", e)
    print(f"[ru09] ИТОГО: {len(results)}")
    return results

# ---------- AVITO (через Playwright для обхода защиты) ----------

AVITO_URL = "https://www.avito.ru/tomsk/kvartiry/prodam/vtorichka-ASgBAgICAkSSA8YQ5geMUg?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Inh4ZWp1WjgxRkVMUjdJbEIiO30xbsfcJgAAAA&f=ASgBAQICA0SSA8YQ5geMUpC~DZauNQJAygjE_M8yilmarAGYrAGWrAGUrAGIWYZZhFmCWYBZ_ljAwQ0kvP03uv03&localPriority=0"

def parse_avito(page):
    """Парсинг Avito с использованием Playwright (для обхода антибота)"""
    results = []
    try:
        print("[Avito] Начинаю загрузку страницы...")
        
        # Переходим на страницу
        page.goto(AVITO_URL, timeout=60000, wait_until='networkidle')
        
        # Ждём подольше для загрузки
        page.wait_for_timeout(5000)
        
        # Прокручиваем страницу вниз
        for _ in range(5):
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(1000)
        
        # Пробуем разные селекторы
        selectors = [
            '[data-marker="item"]',
            '[class*="item"]',
            '[class*="Item"]',
            '[data-testid="item"]',
            'div[class*="item"]',
            'article'
        ]
        
        cards = []
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=5000)
                cards = page.query_selector_all(selector)
                if cards and len(cards) > 0:
                    print(f"[Avito] Нашёл карточки по селектору: {selector}, {len(cards)} шт.")
                    break
            except:
                continue
        
        if not cards:
            # Сохраняем HTML для диагностики
            html = page.content()
            with open("avito_debug.html", "w", encoding="utf-8") as f:
                f.write(html[:10000])
            print("[Avito] Карточки не найдены. Сохранён avito_debug.html")
            return results
        
        print("[Avito] Начинаю сбор данных...")
        
        for card in cards:
            try:
                # Название
                title = ''
                title_el = card.query_selector('[itemprop="name"]') or \
                          card.query_selector('[data-marker="item-title"]') or \
                          card.query_selector('h3')
                if title_el:
                    title = title_el.inner_text().strip()
                
                # Цена
                price = ''
                price_el = card.query_selector('[itemprop="price"]') or \
                          card.query_selector('[data-marker="item-price"]') or \
                          card.query_selector('span[class*="price"]')
                if price_el:
                    price = price_el.inner_text().strip()
                    # Если есть content, берём его
                    content = price_el.get_attribute('content')
                    if content:
                        price = content
                
                # Ссылка
                url = ''
                link_el = card.query_selector('a[data-marker="item-title"]') or \
                         card.query_selector('a[href*="/avito/"]') or \
                         card.query_selector('a[href*="/tomsk/"]') or \
                         card.query_selector('a')
                if link_el:
                    url = link_el.get_attribute('href')
                    if url and not url.startswith('http'):
                        url = 'https://www.avito.ru' + url
                
                if not url:
                    continue
                
                # Адрес
                address = ''
                addr_el = card.query_selector('[data-marker="item-address"]') or \
                         card.query_selector('[class*="address"]')
                if addr_el:
                    address = addr_el.inner_text().strip()
                
                # Формируем заголовок
                full_title = title
                if address:
                    full_title = f"{title} — {address}" if title else address
                if not full_title:
                    full_title = "Квартира"
                
                results.append({
                    "id": make_id("avito", url),
                    "source": "Avito",
                    "title": full_title,
                    "price": price or "Цена не указана",
                    "url": url,
                })
                
            except Exception as e:
                print(f"[Avito] Ошибка при парсинге карточки: {e}")
                continue
        
        print(f"[Avito] Собрано {len(results)} объявлений")
        
    except Exception as e:
        print(f"[Avito] Ошибка: {e}")
        try:
            html = page.content()
            with open("avito_debug.html", "w", encoding="utf-8") as f:
                f.write(html[:10000])
            print("[Avito] Сохранён debug-файл avito_debug.html")
        except:
            pass
    
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

            pieces = [link.get_text(" ", strip=True), link.get("title", "")]
            for img in link.find_all("img"):
                pieces.append(img.get("alt", ""))
            combined = " ".join(p for p in pieces if p)

            price_match = re.search(r"(\d{6,})\s*рубл", combined)
            if not price_match:
                continue

            seen_ids.add(item_id)
            price_num = int(price_match.group(1))
            price = f"{price_num:,} ₽".replace(",", " ")
            title_text = combined[:price_match.start()].strip()
            title_text = re.sub(r"^Продается\s*", "", title_text).strip().rstrip(",")
            if not title_text:
                title_text = "Квартира"

            full_url = href if href.startswith("http") else "https://tomsk.sibdom.ru" + href

            results.append({
                "id": make_id("sibdom", full_url),
                "source": "Сибдом",
                "title": title_text[:100],
                "price": price,
                "url": full_url,
            })

        if not results:
            print("[Sibdom] HTML-фрагмент для диагностики:")
            print(r.text[:2000])
    except Exception as e:
        print("[Sibdom] Ошибка:", e)
    print(f"[Sibdom] ИТОГО: {len(results)}")
    return results


# ---------- Дедупликация ----------

def extract_number(text, pattern):
    if not text:
        return None
    m = re.search(pattern, text.replace("\u00a0", " "))
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def dedupe(items):
    """Схлопывает объявления с одинаковой площадью и близкой ценой из разных источников."""
    seen = {}
    result = []
    for item in items:
        area = extract_number(item["title"], r"(\d+[.,]?\d*)\s*м²")
        price_num = float(re.sub(r"\D", "", item["price"])) if item["price"] else None

        if area and price_num:
            key = (round(area, 1), round(price_num / 10000))
        else:
            key = None

        if key and key in seen:
            seen[key]["also_on"] = seen[key].get("also_on", []) + [item["source"]]
            continue

        item["also_on"] = []
        if key:
            seen[key] = item
        result.append(item)
    return result

def send_telegram(new_items):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[Telegram] Токен или chat_id не заданы — пропускаю уведомления")
        return
    if not new_items:
        print("[Telegram] Новых объявлений нет — уведомление не отправляю")
        return

    for item in new_items[:10]:  # не больше 10 сообщений за раз, чтобы не спамить
        text = f"🏠 {item['source']}\n{item['title']}\n💰 {item['price']}\n{item['url']}"
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": text},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"[Telegram] Ошибка отправки: {resp.status_code} {resp.text}")
        except Exception as e:
            print("[Telegram] Ошибка запроса:", e)

    if len(new_items) > 10:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": f"...и ещё {len(new_items) - 10} новых объявлений на сайте."},
                timeout=15,
            )
        except Exception as e:
            print("[Telegram] Ошибка отправки итоговой сводки:", e)

    print(f"[Telegram] Отправлено уведомлений: {min(len(new_items), 10)}")

def main():
    existing = load_existing()
    existing_ids = {item["id"] for item in existing}
    existing_by_id = {item["id"]: item for item in existing}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        page = browser.new_page(
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            viewport={'width': 1920, 'height': 1080}
        )
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        
        cian_items = parse_cian(page)
        
        avito_page = browser.new_page(
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            viewport={'width': 1920, 'height': 1080}
        )
        avito_page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        avito_items = parse_avito(avito_page)
        
        browser.close()

    ru09_items = parse_ru09()
    sibdom_items = parse_sibdom()

    fresh = cian_items + ru09_items + sibdom_items + avito_items
    print(f"[Статистика] ЦИАН: {len(cian_items)}, RU09: {len(ru09_items)}, Сибдом: {len(sibdom_items)}, Avito: {len(avito_items)}")
    now = datetime.now(timezone.utc).isoformat()
    merged = []
    for item in fresh:
        if item["id"] in existing_by_id:
            old = existing_by_id[item["id"]]
            item["first_seen"] = old.get("first_seen", now)
        else:
            item["first_seen"] = now
        merged.append(item)

    merged = dedupe(merged)
    merged.sort(key=lambda x: x["first_seen"], reverse=True)
    save(merged)
    new_items = [i for i in merged if i['id'] not in existing_ids]
    print(f"ВСЕГО объявлений сохранено: {len(merged)}, новых за этот запуск: {len(new_items)}")
    send_telegram(new_items)


if __name__ == "__main__":
    main()
