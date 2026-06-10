import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from playwright.async_api import async_playwright

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

SKIP_NAMES = {
    "menu", "featured items", "popular", "see all", "skip to content",
    "get it delivered to your door.", "log in for saved address",
    "savings and more", "offers", "delivery", "pickup", "group order",
    "info", "rating and reviews", "show more", "other fees",
    "explore all deals", "many in stock", "you might also like",
    "our entrees", "our daily specials", "our homemade empanadas",
    "our sandwiches", "our homemade soup", "our sides and salads",
    "our beverages", "our sauces", "our combo meals",
    "extras", "large orders", "retail", "deals", "more to explore",
}

SKIP_CATEGORIES = {
    "drinks", "drink", "appetizers", "appetizer",
    "desserts", "dessert", "sides", "side",
    "beverages", "beverage", "sauces", "sauce",
    "combos", "combo", "entrees", "entree",
    "specials", "special", "popular items",
    "featured", "recommended",
    "gin", "rum", "vodka", "whiskey", "whisky", "tequila", "bitters",
    "wine", "beer", "liquor", "spirits", "bourbon", "scotch",
    "champagne", "prosecco", "cocktails", "mixers", "sake",
}

HOURS_RE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM|a\.m\.|p\.m\.)", re.IGNORECASE)
ADDRESS_RE = re.compile(r"\d+\s+\w+\.?\s+(Street|St|Avenue|Ave|Lane|Ln|Road|Rd|Drive|Dr|Boulevard|Blvd)", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2,4}$")
PCT_RE = re.compile(r"^\d+%\s*\(\d+\)")
CALORIES_RE = re.compile(r"^\d+\s*(-|–)?\s*\d*\s*Cal(ories)?\.?\s*$", re.IGNORECASE)
CALORIES_INLINE_RE = re.compile(r"\s*•\s*\d+\s*(-|–)?\s*\d*\s*Cal(ories)?\.?\s*", re.IGNORECASE)
RATING_RE = re.compile(r"^\d+\.\d+$")
TIME_RE = re.compile(r"^\d+\s*min$", re.IGNORECASE)
PRODUCT_SIZE_RE = re.compile(r"^[\d.]+[\s]*(oz|fl\s*oz|ml|l|L|g|lb|count|pack|pk|ct)", re.IGNORECASE)
TERMS_RE = re.compile(r"valid for|while supplies last|free with|where can i", re.IGNORECASE)


class UberEatsScraper:
    def __init__(self, headless=True, debug=False):
        self.headless = headless
        self.debug = debug

    async def _ss(self, page, name):
        if self.debug:
            await page.screenshot(path=f"debug_{name}.png", full_page=True)

    async def _click(self, page, selector, timeout=5000):
        try:
            el = await page.wait_for_selector(selector, timeout=timeout)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(800)
                return True
        except Exception:
            pass
        return False

    async def _setup_homepage(self, page, location):
        await page.goto("https://www.ubereats.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1500)
        await self._click(page, "button:has-text('Got it'), button:has-text('Accept')")
        await self._click(page, "button:has-text('Type in delivery')")
        await page.wait_for_timeout(500)
        inp = await page.wait_for_selector(
            'input[placeholder*="Enter delivery"]', timeout=10000, state="visible"
        )
        await inp.click()
        await page.wait_for_timeout(200)
        await inp.fill(location)
        await page.wait_for_timeout(1000)
        try:
            sugg = await page.wait_for_selector(
                'li[class*="option"]:first-child, [role="option"]', timeout=5000
            )
            if sugg:
                await sugg.click()
        except Exception:
            await inp.press("Enter")
        await page.wait_for_timeout(3000)

    # ── Feed parsing ──────────────────────────────────────────────

    def _parse_feed(self, feed_data):
        stores = {}
        for item in feed_data.get("feedItems", []):
            if item.get("type") != "REGULAR_CAROUSEL":
                continue
            for s in item.get("carousel", {}).get("stores", []):
                uuid = s["storeUuid"]
                if uuid not in stores:
                    stores[uuid] = s
        results = []
        seen = set()
        for uuid, s in stores.items():
            name = s["title"]["text"]
            if not name or name in seen:
                continue
            seen.add(name)
            signpost = ""
            for sp in s.get("signposts") or []:
                t = sp.get("text", "")
                if t:
                    signpost = t
                    break
            if not signpost:
                continue
            href = s.get("actionUrl", "") or ""
            full_url = urljoin("https://www.ubereats.com", href) if href else ""
            results.append({"name": name, "signpost": signpost, "url": full_url, "uuid": uuid})
        return results

    # ── Page text & image extraction ─────────────────────────────

    async def _extract_images(self, page):
        return await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img[alt]');
                return Array.from(imgs)
                    .filter(img => img.alt && img.alt.length > 2
                        && !img.alt.includes('Uber') && !img.alt.includes('Google'))
                    .map(img => ({
                        name: img.alt.trim(),
                        src: img.getAttribute('src') || img.getAttribute('data-src') || '',
                    }));
            }
        """)

    def _build_image_map(self, imgs):
        img_map = {}
        for img in imgs:
            n = img["name"].lower()
            if n not in img_map and img["src"]:
                img_map[n] = img["src"]
        return img_map

    def _is_valid_item_name(self, name):
        low = name.lower()
        if low in SKIP_NAMES:
            return False
        if low in SKIP_CATEGORIES:
            return False
        if len(name) > 60:
            return False
        if HOURS_RE.match(name):
            return False
        if ADDRESS_RE.search(name):
            return False
        if DATE_RE.match(name):
            return False
        if PCT_RE.match(name):
            return False
        if re.match(r"^\d+%\s*\(\d+\)", name):
            return False
        if CALORIES_RE.match(name):
            return False
        if RATING_RE.match(name):
            return False
        if TIME_RE.match(name):
            return False
        if PRODUCT_SIZE_RE.match(name):
            return False
        if TERMS_RE.search(name):
            return False
        if "•" in name:
            return False
        if name.startswith("#"):
            return False
        if name.lower().startswith("save") or name.lower().startswith("save up to"):
            return False
        # Skip item descriptions (long sentences starting lowercase)
        if name[0].islower() and len(name) > 20 and sum(1 for c in name if c == " ") >= 3:
            return False
        # Skip descriptions starting uppercase but still sentence-like
        words = name.split()
        if len(words) >= 5 and len(name) > 35 and name.endswith("."):
            return False
        if len(words) >= 6 and len(name) > 40 and (" and " in name or " with " in name):
            return False
        return True

    def _clean_price(self, price):
        if not price:
            return price
        cleaned = CALORIES_INLINE_RE.sub("", price)
        # Also clean rating info like "• 86% (394)"
        cleaned = re.sub(r"\s*•\s*\d+%\s*\(\d+\)\s*", "", cleaned)
        cleaned = cleaned.strip()
        return cleaned

    def _is_valid_promo(self, text):
        low = text.lower()
        if not any(k in low for k in ["buy 1", "bogo", "get 1 free", "free item",
                                       "% off", "save", "spend"]):
            return False
        if len(text) > 100:
            return False
        if text.endswith("?") and len(text) > 40:
            return False
        if low in ["offers", "savings and more", "show more"]:
            return False
        return True

    async def _scrape_page_items(self, page):
        page_text = await page.inner_text("body")
        raw_lines = page_text.split("\n")
        lines = [l.strip() for l in raw_lines if l.strip()]

        if len(lines) < 10:
            return None

        imgs = await self._extract_images(page)
        img_map = self._build_image_map(imgs)

        items = []
        for i, line in enumerate(lines):
            if not self._is_valid_promo(line):
                continue

            promo_text = line
            item_name = ""
            item_price = ""

            for j in range(i - 1, max(i - 4, -1), -1):
                lj = lines[j]
                ljl = lj.lower()
                if lj.startswith("US$") or lj.startswith("CA$") or lj.startswith("$"):
                    item_price = lj
                elif (not item_name and lj
                      and not any(lj.startswith(p) for p in ["US$", "CA$", "$", "•", "(", "%"])
                      and len(lj) > 2
                      and not any(k in ljl for k in ["buy 1", "bogo", "get 1 free",
                                                     "free item", "% off"])):
                    if self._is_valid_item_name(lj):
                        item_name = lj
                        break

            if not item_name:
                continue

            key_low = item_name.lower()
            if any(k["name"].lower() == key_low and k["promo"] == promo_text for k in items):
                continue

            items.append({
                "name": item_name,
                "price": self._clean_price(item_price),
                "promo": promo_text,
                "image": img_map.get(key_low, ""),
            })

        return items

    async def _wait_for_content(self, page, min_lines=10, interval=1000, max_wait=8000):
        waited = 0
        await page.wait_for_timeout(2000)
        waited += 2000
        while waited < max_wait:
            text = await page.inner_text("body")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if len(lines) >= min_lines:
                return True
            await page.wait_for_timeout(interval)
            waited += interval
        return False

    # ── Public: scrape location (full) ──────────────────────────

    async def scrape_location(self, location: str, max_stores=20):
        results = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            feed_data = None

            page = await browser.new_page(
                viewport={"width": 1920, "height": 1080},
                user_agent=USER_AGENT,
                locale="en-US",
                timezone_id="America/New_York",
            )

            async def on_response(response):
                nonlocal feed_data
                if feed_data is None and "getFeedV1" in response.url:
                    try:
                        feed_data = json.loads(await response.text())
                    except Exception:
                        pass

            page.on("response", on_response)

            try:
                await self._setup_homepage(page, location)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)

                if not feed_data:
                    if self.debug:
                        print("No feed data captured")
                    return []

                stores = self._parse_feed(feed_data["data"])
                if self.debug:
                    print(f"Feed: {len(stores)} stores with deals")

                for idx, store in enumerate(stores[:max_stores]):
                    if self.debug:
                        print(f"  [{idx+1}/{min(max_stores, len(stores))}] {store['name']} ...")

                    menu_url = store["url"]
                    sep = "&" if "?" in menu_url else "?"
                    menu_url += f"{sep}diningMode=DELIVERY"

                    await page.evaluate(f'window.location.href = "{menu_url}"')
                    loaded = await self._wait_for_content(page)

                    items = await self._scrape_page_items(page)
                    if items is None:
                        if self.debug:
                            print(f"    Short page, retrying...")
                        loaded = await self._wait_for_content(page, max_wait=5000)
                        items = await self._scrape_page_items(page)

                    result_items = items if items else []

                    results.append({
                        "name": store["name"],
                        "signpost": store["signpost"],
                        "url": store["url"],
                        "items": result_items,
                        "scraped_at": datetime.now().isoformat(),
                    })

                # Append remaining stores without menu scrape
                visited_names = {s["name"] for s in stores[:max_stores]}
                for s in stores:
                    if s["name"] not in visited_names:
                        results.append({
                            "name": s["name"],
                            "signpost": s["signpost"],
                            "url": s["url"],
                            "items": [],
                            "scraped_at": datetime.now().isoformat(),
                        })

            except Exception as e:
                if self.debug:
                    print(f"Scrape error: {e}")
            finally:
                await browser.close()

        return results

    # ── Public: feed-only (fast, no store pages) ────────────────

    async def scrape_feed(self, location: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            feed_data = None

            page = await browser.new_page(
                viewport={"width": 1920, "height": 1080},
                user_agent=USER_AGENT,
                locale="en-US",
                timezone_id="America/New_York",
            )

            async def on_response(response):
                nonlocal feed_data
                if feed_data is None and "getFeedV1" in response.url:
                    try:
                        feed_data = json.loads(await response.text())
                    except Exception:
                        pass

            page.on("response", on_response)

            try:
                await self._setup_homepage(page, location)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)

                if not feed_data:
                    if self.debug:
                        print("No feed data captured")
                    return []

                stores = self._parse_feed(feed_data["data"])
                return stores

            except Exception as e:
                if self.debug:
                    print(f"Feed error: {e}")
                return []
            finally:
                await browser.close()

    # ── Public: single store items (lazy load) ──────────────────

    async def scrape_store_items(self, url: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            page = await browser.new_page(
                viewport={"width": 1920, "height": 1080},
                user_agent=USER_AGENT,
                locale="en-US",
                timezone_id="America/New_York",
            )

            try:
                await page.goto("https://www.ubereats.com", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)

                menu_url = url
                sep = "&" if "?" in url else "?"
                menu_url += f"{sep}diningMode=DELIVERY"

                await page.evaluate(f'window.location.href = "{menu_url}"')
                await self._wait_for_content(page)

                items = await self._scrape_page_items(page)
                return items if items else []
            except Exception as e:
                if self.debug:
                    print(f"Store items error: {e}")
                return []
            finally:
                await browser.close()

    # ── Public: single restaurant URL ────────────────────────────

    async def scrape_restaurant_url(self, url: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            page = await browser.new_page(
                viewport={"width": 1920, "height": 1080},
                user_agent=USER_AGENT,
                locale="en-US",
                timezone_id="America/New_York",
            )

            try:
                await self._setup_homepage(page, "New York, NY")

                menu_url = url
                sep = "&" if "?" in url else "?"
                menu_url += f"{sep}diningMode=DELIVERY"

                await page.evaluate(f'window.location.href = "{menu_url}"')
                await page.wait_for_timeout(8000)

                items = await self._scrape_page_items(page)
                return items if items else []

            except Exception as e:
                if self.debug:
                    print(f"Store scrape error: {e}")
                return []
            finally:
                await browser.close()


if __name__ == "__main__":
    import sys
    scraper = UberEatsScraper(headless=False, debug=True)
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        r = asyncio.run(scraper.scrape_restaurant_url(sys.argv[1]))
    else:
        loc = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "New York, NY"
        r = asyncio.run(scraper.scrape_location(loc))
    print(json.dumps(r, indent=2))
