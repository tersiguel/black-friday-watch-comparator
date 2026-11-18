"""Universal hybrid price scraper for any watch e-commerce product URL."""

import json
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from lxml import html as lxml_html

from src.models import OfferResult


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}


def http_get_text(url: str, timeout: int = 15) -> Tuple[int, str]:
    """Fetch URL content using requests (if available) or urllib.request."""
    try:
        import requests  # type: ignore

        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
        return resp.status_code, resp.text
    except ImportError:
        req = Request(url, headers=DEFAULT_HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read()
            return status, raw.decode("utf-8", errors="replace")


def infer_merchant_name(url: str, fallback: str = "") -> str:
    """Derive a clean merchant display name from a URL if not explicitly provided."""
    if fallback and fallback.strip():
        return fallback.strip()
    try:
        hostname = urlparse(url).hostname or ""
        hostname = re.sub(r"^www\.", "", hostname.lower())
        known = {
            "amazon.fr": "Amazon FR",
            "amazon.de": "Amazon DE",
            "amazon.es": "Amazon ES",
            "amazon.it": "Amazon IT",
            "ocarat.com": "Ocarat",
            "montresandco.com": "Montres & Co",
            "histoiredeor.com": "Histoire d'Or",
            "fnac.com": "Fnac",
            "darty.com": "Darty",
            "cdiscount.com": "Cdiscount",
            "boulanger.com": "Boulanger",
            "chrono24.fr": "Chrono24",
            "chrono24.com": "Chrono24",
            "sakurawatches.com": "Sakura Watches (Tokyo)",
            "shoppinginjapan.net": "Shopping In Japan (Japon)",
            "discovery-japan.me": "Discovery Japan",
            "seiyajapan.com": "SeiyaJapan",
            "creationwatches.com": "CreationWatches (Hors UE)",
            "gnomonwatches.com": "Gnomon Watches (Hors UE)",
            "louis-pion.fr": "Louis Pion",
            "galerieslafayette.com": "Galeries Lafayette",
            "dealabs.com": "Dealabs",
            "idealo.fr": "Idealo",
            "catawiki.com": "Catawiki (Enchères)",
        }
        for domain, label in known.items():
            if hostname == domain or hostname.endswith("." + domain):
                return label
        parts = hostname.split(".")
        return parts[0].capitalize() if parts else "Marchand"
    except Exception:
        return fallback or "Marchand"


NON_EU_IMPORT_DOMAINS = (
    "sakurawatches.com",
    "shoppinginjapan.net",
    "discovery-japan.me",
    "seiyajapan.com",
    "creationwatches.com",
    "gnomonwatches.com",
)


def is_non_eu_import_url(url: str) -> bool:
    """Return True if the URL belongs to a non-EU (e.g., Tokyo/Japan) boutique subject to French VAT & customs."""
    try:
        hostname = re.sub(r"^www\.", "", (urlparse(url).hostname or "").lower())
        return any(hostname == d or hostname.endswith("." + d) for d in NON_EU_IMPORT_DOMAINS)
    except Exception:
        return False


def compute_japan_import_price(
    raw_price_ht: float,
    shipping_eur: float = 24.0,
    vat_rate: float = 0.20,
    customs_duty_eur: float = 0.80,
    carrier_fee_eur: float = 18.0,
) -> Tuple[float, str]:
    """
    Compute true landed TTC price in France for a watch imported from Japan/non-EU (e.g. Sakura Watches Tokyo):
      - Insured express shipping (DHL/FedEx): ~24 €
      - EU watch customs duty (HS 9102): 0.80 €
      - French import VAT (20%) applied on (watch + shipping + duty)
      - Carrier customs clearance / disbursement fee (DHL/FedEx): ~18 €
    """
    taxes = (raw_price_ht + shipping_eur + customs_duty_eur) * vat_rate + customs_duty_eur
    total_ttc = round(raw_price_ht + shipping_eur + taxes + carrier_fee_eur, 2)
    note = (
        f"🇯🇵 Prix HT Tokyo {raw_price_ht:.0f} € + {shipping_eur:.0f}€ port DHL "
        f"+ {taxes:.0f}€ TVA/douane (20%) + {carrier_fee_eur:.0f}€ frais dossier"
    )
    return total_ttc, note


def compute_catawiki_price_with_fees(raw_bid: float) -> float:
    """Compute true Catawiki price including mandatory 9% + 3€ buyer protection fee."""
    return round(raw_bid * 1.09 + 3.0, 2)


def parse_price_string(raw: Any) -> Optional[float]:
    """Parse a French/International price string or number into a float."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        val = float(raw)
        return round(val, 2) if 5.0 <= val <= 25000.0 else None

    text = str(raw).strip()
    if not text:
        return None

    # Normalize currency symbols and spaces
    text = text.replace("\xa0", " ").replace("\u202f", " ")
    # Handle formats like "129€90" or "129 € 90"
    m_euro_sep = re.search(r"(\d[\d\s.]*)\s*€\s*(\d{2})\b", text)
    if m_euro_sep:
        whole = re.sub(r"[^\d]", "", m_euro_sep.group(1))
        cents = m_euro_sep.group(2)
        try:
            val = float(f"{whole}.{cents}")
            return round(val, 2) if 5.0 <= val <= 25000.0 else None
        except ValueError:
            pass

    # Prefer numbers explicitly adjacent to € or EUR (avoids matching model numbers like GW-M5610U)
    m_curr = re.search(
        r"(?:(?:€|EUR)\s*(\d{1,3}(?:[\s.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)|(\d{1,3}(?:[\s.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR\b))",
        text,
        re.I,
    )
    if m_curr:
        candidate = m_curr.group(1) or m_curr.group(2)
        m = re.search(r".+", candidate)
    else:
        # Standard numeric extraction: e.g. "1 249,90", "129.99", "249,00"
        m = re.search(r"(?<![A-Za-z0-9-])(\d{1,3}(?:[\s.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![A-Za-z0-9])", text)
    if not m:
        return None

    num_str = m.group(0).replace(" ", "")
    if "." in num_str and "," in num_str:
        if num_str.rfind(",") > num_str.rfind("."):
            num_str = num_str.replace(".", "").replace(",", ".")
        else:
            num_str = num_str.replace(",", "")
    elif "," in num_str:
        parts = num_str.split(",")
        if len(parts[-1]) in (1, 2):
            num_str = "".join(parts[:-1]) + "." + parts[-1]
        else:
            num_str = "".join(parts)

    try:
        val = float(num_str)
        return round(val, 2) if 5.0 <= val <= 25000.0 else None
    except ValueError:
        return None


def extract_from_json_ld(doc: lxml_html.HtmlElement) -> Optional[Dict[str, Any]]:
    """Layer 1: Extract price, original price, stock, and title from JSON-LD Schema.org Product."""
    scripts = doc.xpath("//script[contains(translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ld+json')]")

    def _walk_node(node: Any) -> Optional[Dict[str, Any]]:
        if isinstance(node, list):
            for item in node:
                res = _walk_node(item)
                if res:
                    return res
            return None
        if not isinstance(node, dict):
            return None

        node_type = node.get("@type", "")
        types = [node_type] if isinstance(node_type, str) else (node_type if isinstance(node_type, list) else [])
        types_lower = [str(t).lower() for t in types]

        if any("product" in t for t in types_lower):
            title = node.get("name", "")
            offers = node.get("offers")
            res = _extract_offers(offers)
            if res and res.get("price"):
                res["title"] = title
                return res

        if "@graph" in node:
            res = _walk_node(node["@graph"])
            if res:
                return res
        return None

    def _extract_offers(offers: Any) -> Optional[Dict[str, Any]]:
        if not offers:
            return None
        if isinstance(offers, list):
            valid = []
            for o in offers:
                r = _extract_offers(o)
                if r and r.get("price"):
                    valid.append(r)
            if not valid:
                return None
            valid.sort(key=lambda x: x["price"])
            return valid[0]

        if isinstance(offers, dict):
            raw_price = (
                offers.get("price")
                or offers.get("lowPrice")
                or (offers.get("priceSpecification", {}) if isinstance(offers.get("priceSpecification"), dict) else {}).get("price")
            )
            price = parse_price_string(raw_price)
            if not price and isinstance(offers.get("offers"), (list, dict)):
                return _extract_offers(offers["offers"])
            if price:
                avail = str(offers.get("availability", "")).lower()
                in_stock = True
                if any(out in avail for out in ("outofstock", "soldout", "discontinued")):
                    in_stock = False
                currency = offers.get("priceCurrency", "EUR")
                high_price = parse_price_string(offers.get("highPrice"))
                return {
                    "price": price,
                    "original_price": high_price if (high_price and high_price > price) else None,
                    "currency": currency,
                    "in_stock": in_stock,
                    "method": "json-ld",
                }
        return None

    for script in scripts:
        raw_text = script.text_content()
        if not raw_text:
            continue
        try:
            data = json.loads(raw_text.strip())
            res = _walk_node(data)
            if res and res.get("price"):
                return res
        except Exception:
            continue
    return None


def extract_from_meta(doc: lxml_html.HtmlElement) -> Optional[Dict[str, Any]]:
    """Layer 2: Extract from OpenGraph, Twitter, or Schema Microdata meta tags."""
    xpaths = [
        "//*[@property='product:price:amount']",
        "//*[@property='og:price:amount']",
        "//*[@name='twitter:data1']",
        "//*[@itemprop='price']",
        "//*[@itemprop='lowPrice']",
    ]
    price = None
    for xp in xpaths:
        nodes = doc.xpath(xp)
        for node in nodes:
            candidate = node.get("content") or node.text_content()
            price = parse_price_string(candidate)
            if price:
                break
        if price:
            break

    if not price:
        return None

    title_nodes = doc.xpath("//meta[@property='og:title']/@content | //title/text()")
    title = str(title_nodes[0]).strip() if title_nodes else ""

    avail_nodes = doc.xpath("//meta[@property='product:availability']/@content | //*[@itemprop='availability']/@href | //*[@itemprop='availability']/text()")
    in_stock = True
    if avail_nodes:
        avail_str = " ".join(str(a).lower() for a in avail_nodes)
        if any(w in avail_str for w in ("out", "épuisé", "indisponible")):
            in_stock = False

    return {
        "price": price,
        "original_price": None,
        "currency": "EUR",
        "in_stock": in_stock,
        "title": title,
        "method": "opengraph-meta",
    }


def extract_from_selectors(doc: lxml_html.HtmlElement, url: str = "") -> Optional[Dict[str, Any]]:
    """Layer 3: Domain-specific XPath/CSS selectors (Amazon, Ocarat, Montres&Co, Cdiscount, Fnac, etc.)."""
    current_xpaths = [
        # Amazon
        "//*[@id='corePriceDisplay_desktop_feature_div']//*[contains(@class, 'a-price')]//*[contains(@class, 'a-offscreen')]",
        "//*[@id='corePrice_feature_div']//*[contains(@class, 'a-price')]//*[contains(@class, 'a-offscreen')]",
        "//*[@id='priceblock_ourprice']",
        "//*[@id='priceblock_dealprice']",
        # Ocarat / PrestaShop / Magento horlogerie
        "//*[contains(@class, 'current-price-value')]",
        "//*[contains(@class, 'product-price')]//*[contains(@class, 'price')]",
        "//*[@id='our_price_display']",
        # Catawiki auction lot pages
        "//*[@data-testid='lot-bid-status-section']//*[contains(text(), '€')]",
        "//*[@data-testid='bid-amount']",
        "//*[contains(@class, 'be-lot-details-bidding-panel')]//*[contains(text(), '€')]",
        "//*[contains(@class, 'c-lot-card__price')]",
        # Generic e-commerce
        "//*[@data-testid='product-price']",
        "//*[contains(@class, 'f-priceBox-price')]",
        "//*[contains(@class, 'fpPrice')]",
        "//*[contains(@class, 'c-price__current')]",
        "//*[contains(@class, 'price-sales')]",
        "//*[contains(@class, 'special-price')]//*[contains(@class, 'price')]",
        "//*[contains(@class, 'final-price')]",
        "//*[contains(@class, 'price--main')]",
    ]

    old_price_xpaths = [
        "//*[contains(@class, 'basisPrice')]//*[contains(@class, 'a-offscreen')]",
        "//*[contains(@class, 'a-text-price')]//*[contains(@class, 'a-offscreen')]",
        "//*[contains(@class, 'regular-price')]",
        "//*[@id='old_price_display']",
        "//*[contains(@class, 'price-standard')]",
        "//*[contains(@class, 'old-price')]//*[contains(@class, 'price')]",
        "//*[contains(@class, 'c-price__old')]",
        "//del//*[contains(@class, 'price')]",
        "//s//*[contains(@class, 'price')]",
    ]

    price = None
    for xp in current_xpaths:
        nodes = doc.xpath(xp)
        for el in nodes:
            val = parse_price_string(el.get("content") or el.text_content())
            if val:
                price = val
                break
        if price:
            break

    original_price = None
    for xp in old_price_xpaths:
        nodes = doc.xpath(xp)
        for el in nodes:
            val = parse_price_string(el.get("content") or el.text_content())
            if val and (not price or val > price):
                original_price = val
                break
        if original_price:
            break

    title_nodes = doc.xpath("//*[@id='productTitle']/text() | //h1/text() | //title/text()")
    title = str(title_nodes[0]).strip() if title_nodes else ""

    promo_code = None
    page_text = " ".join(doc.xpath("//body//text()"))
    m_code = re.search(r"(?:code\s+promo|avec\s+le\s+code|code\s*:)\s*([A-Z0-9_-]{4,15})", page_text, re.I)
    if m_code:
        promo_code = m_code.group(1).upper()

    if not price and not original_price and not promo_code:
        return None

    return {
        "price": price,
        "original_price": original_price,
        "currency": "EUR",
        "in_stock": True,
        "title": title,
        "promo_code": promo_code,
        "method": "css-selector",
    }


def extract_from_html(html_str: str, url: str = "") -> Optional[Dict[str, Any]]:
    """Run all HTML extraction layers in priority order and enrich missing fields."""
    if not html_str or not html_str.strip():
        return None

    try:
        doc = lxml_html.fromstring(html_str)
    except Exception:
        return None

    res_ld = extract_from_json_ld(doc)
    res_meta = extract_from_meta(doc)
    res_sel = extract_from_selectors(doc, url)

    primary = res_ld or res_meta or (res_sel if (res_sel and res_sel.get("price")) else None)
    if not primary:
        return None

    if res_sel:
        if not primary.get("original_price") and res_sel.get("original_price"):
            if res_sel["original_price"] > primary["price"]:
                primary["original_price"] = res_sel["original_price"]
        if not primary.get("promo_code") and res_sel.get("promo_code"):
            primary["promo_code"] = res_sel["promo_code"]
        if not primary.get("title") and res_sel.get("title"):
            primary["title"] = res_sel["title"]

    return primary


def fetch_html_playwright(url: str, timeout_ms: int = 15000) -> Optional[str]:
    """Layer 4: Headless Chromium fallback via Playwright for JS-rendered or anti-bot pages."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                locale="fr-FR",
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1500)
            content = page.content()
            browser.close()
            return content
    except Exception:
        return None


def scrape_offer(
    watch_id: str,
    url: str,
    merchant: str = "",
    timeout: int = 15,
    use_playwright_fallback: bool = True,
    import_settings: Optional[Dict[str, Any]] = None,
) -> OfferResult:
    """Scrape a single product URL using the 4-layer hybrid engine."""
    merchant_name = infer_merchant_name(url, merchant)
    now_iso = datetime.now(timezone.utc).isoformat()

    html_str = None
    http_error = None
    try:
        status, text = http_get_text(url, timeout=timeout)
        if status == 200 and len(text) > 500:
            html_str = text
        else:
            http_error = f"HTTP {status}"
    except Exception as exc:
        http_error = str(exc)

    extracted = extract_from_html(html_str, url) if html_str else None

    if not extracted and use_playwright_fallback:
        pw_html = fetch_html_playwright(url, timeout_ms=timeout * 1000)
        if pw_html:
            extracted = extract_from_html(pw_html, url)
            if extracted:
                extracted["method"] = f"playwright+{extracted.get('method', 'dom')}"

    if extracted and extracted.get("price"):
        final_price = extracted["price"]
        shipping_note = None
        if "catawiki." in url.lower():
            raw_bid = final_price
            final_price = compute_catawiki_price_with_fees(raw_bid)
            shipping_note = f"🔨 Enchère {raw_bid:.0f} € + 9% + 3€ frais Catawiki inclus (hors port)"
        elif is_non_eu_import_url(url):
            imp = import_settings or {}
            final_price, shipping_note = compute_japan_import_price(
                raw_price_ht=final_price,
                shipping_eur=float(imp.get("shipping_eur", 24.0)),
                vat_rate=float(imp.get("vat_rate", 0.20)),
                customs_duty_eur=float(imp.get("customs_duty_eur", 0.80)),
                carrier_fee_eur=float(imp.get("carrier_fee_eur", 18.0)),
            )

        return OfferResult(
            watch_id=watch_id,
            merchant=merchant_name,
            url=url,
            price=final_price,
            original_price=extracted.get("original_price"),
            currency=extracted.get("currency", "EUR"),
            in_stock=extracted.get("in_stock", True),
            title=extracted.get("title", ""),
            extraction_method=extracted.get("method", "hybrid"),
            promo_code=extracted.get("promo_code"),
            shipping_note=shipping_note,
            timestamp=now_iso,
        )

    return OfferResult(
        watch_id=watch_id,
        merchant=merchant_name,
        url=url,
        price=None,
        in_stock=False,
        extraction_method="failed",
        timestamp=now_iso,
        error=http_error or "Prix non détecté sur la page",
    )
