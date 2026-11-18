"""Universal hybrid price, metadata & explicit fee scraper for watch product pages."""

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

FX_RATES_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.18,
    "CHF": 1.06,
    "JPY": 0.0061,
}

KNOWN_WATCH_BRANDS = (
    "Citizen",
    "Seiko",
    "Casio",
    "Junghans",
    "Tissot",
    "Orient",
    "Hamilton",
    "Longines",
    "Omega",
    "Certina",
    "Mido",
    "Sinn",
    "Bulova",
    "Timex",
    "Garmin",
    "Lip",
    "Yema",
    "Baltic",
)

NON_EU_IMPORT_DOMAINS = (
    "sakurawatches.com",
    "shoppinginjapan.net",
    "discovery-japan.me",
    "seiyajapan.com",
    "creationwatches.com",
    "gnomonwatches.com",
    "timeshop4you.co.uk",
    "amazon.co.jp",
    "amazon.com",
    "amazon.co.uk",
)

EU_RETAIL_DOMAINS = (
    "amazon.fr",
    "amazon.de",
    "amazon.es",
    "amazon.it",
    "ocarat.com",
    "montresandco.com",
    "histoiredeor.com",
    "lepage.fr",
    "louis-pion.fr",
    "citizenwatch.eu",
    "casio.com",
    "uhr24.de",
    "helveti.eu",
    "irisimo.com",
    "zeitlounge.com",
    "luna-time.fr",
    "luna-time.nl",
    "mastersintime.com",
    "watchxl.com",
    "rm-time.com",
    "watchhouse.de",
    "fnac.com",
    "darty.com",
    "boulanger.com",
    "cdiscount.com",
)


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
            "amazon.fr": "Amazon.fr",
            "amazon.de": "Amazon.de",
            "amazon.es": "Amazon.es",
            "amazon.it": "Amazon.it",
            "amazon.co.jp": "Amazon.co.jp",
            "amazon.co.uk": "Amazon.co.uk",
            "amazon.com": "Amazon.com",
            "ocarat.com": "Ocarat",
            "montresandco.com": "Montres & Co",
            "lepage.fr": "Lepage",
            "histoiredeor.com": "Histoire d'Or",
            "fnac.com": "Fnac",
            "darty.com": "Darty",
            "cdiscount.com": "Cdiscount",
            "boulanger.com": "Boulanger",
            "chrono24.fr": "Chrono24",
            "chrono24.com": "Chrono24",
            "sakurawatches.com": "Sakura Watches (Tokyo)",
            "shoppinginjapan.net": "Shopping In Japan",
            "discovery-japan.me": "Discovery Japan",
            "seiyajapan.com": "SeiyaJapan",
            "creationwatches.com": "CreationWatches",
            "gnomonwatches.com": "Gnomon Watches",
            "timeshop4you.co.uk": "Timeshop4you (UK)",
            "citizenwatch.eu": "Citizen Store EU",
            "de.citizenwatch.eu": "Citizen Store DE",
            "casio.com": "Casio Officiel",
            "uhr24.de": "Uhr24.de",
            "helveti.eu": "Helveti.eu",
            "irisimo.com": "Irisimo",
            "zeitlounge.com": "Zeitlounge",
            "luna-time.fr": "Luna-Time",
            "luna-time.nl": "Luna-Time NL",
            "mastersintime.com": "Masters In Time",
            "watchxl.com": "WatchXL",
            "rm-time.com": "RM-Time",
            "watchhouse.de": "Watchhouse.de",
            "catawiki.com": "Catawiki",
            "ebay.fr": "eBay.fr",
            "ebay.com": "eBay",
            "vinted.fr": "Vinted",
            "leboncoin.fr": "Leboncoin",
            "idealo.fr": "Idealo.fr",
        }
        for domain, label in known.items():
            if hostname == domain or hostname.endswith("." + domain):
                return label
        parts = hostname.split(".")
        return parts[0].capitalize() if parts else "Marchand"
    except Exception:
        return fallback or "Marchand"


def is_non_eu_import_url(url: str) -> bool:
    """Return True if the URL belongs to a non-EU (e.g. Tokyo/UK/US) boutique subject to French VAT & customs."""
    try:
        hostname = re.sub(r"^www\.", "", (urlparse(url).hostname or "").lower())
        return any(hostname == d or hostname.endswith("." + d) for d in NON_EU_IMPORT_DOMAINS)
    except Exception:
        return False


def is_eu_retail_url(url: str) -> bool:
    """Return True if the URL belongs to an EU retail store where VAT is already included."""
    try:
        hostname = re.sub(r"^www\.", "", (urlparse(url).hostname or "").lower())
        return any(hostname == d or hostname.endswith("." + d) for d in EU_RETAIL_DOMAINS)
    except Exception:
        return False


def compute_japan_customs_only(
    raw_price_ht: float,
    shipping_eur: float = 24.0,
    vat_rate: float = 0.20,
    customs_duty_eur: float = 0.80,
    carrier_fee_eur: float = 18.0,
) -> float:
    """Compute French customs + 20% VAT + carrier clearance fee (excluding shipping_eur itself)."""
    taxes = (raw_price_ht + shipping_eur + customs_duty_eur) * vat_rate + customs_duty_eur
    return round(taxes + carrier_fee_eur, 2)


def compute_japan_import_price(
    raw_price_ht: float,
    shipping_eur: float = 24.0,
    vat_rate: float = 0.20,
    customs_duty_eur: float = 0.80,
    carrier_fee_eur: float = 18.0,
) -> Tuple[float, str]:
    """Compute landed TTC price in France for a watch imported from outside the EU."""
    customs_total = compute_japan_customs_only(
        raw_price_ht=raw_price_ht,
        shipping_eur=shipping_eur,
        vat_rate=vat_rate,
        customs_duty_eur=customs_duty_eur,
        carrier_fee_eur=carrier_fee_eur,
    )
    total_ttc = round(raw_price_ht + shipping_eur + customs_total, 2)
    note = (
        f"Prix HT {raw_price_ht:.0f} € + {shipping_eur:.0f} € port "
        f"+ {customs_total:.2f} € douane/TVA/dossier"
    )
    return total_ttc, note


def compute_catawiki_fee_only(raw_bid: float) -> float:
    """Compute mandatory Catawiki buyer protection fee (9% + 3 €)."""
    return round(raw_bid * 0.09 + 3.0, 2)


def compute_catawiki_price_with_fees(raw_bid: float) -> float:
    """Compute total Catawiki price including 9% + 3 € buyer protection fee."""
    return round(raw_bid + compute_catawiki_fee_only(raw_bid), 2)


def _detect_currency_code(text: str, hint: str = "") -> str:
    h = (hint or "").strip().upper()
    if h in FX_RATES_TO_EUR:
        return h
    if "€" in text or re.search(r"\bEUR\b", text, re.I):
        return "EUR"
    if re.search(r"US\s*\$|\bUSD\b|\$", text, re.I):
        return "USD"
    if "£" in text or re.search(r"\bGBP\b", text, re.I):
        return "GBP"
    if re.search(r"\bCHF\b", text, re.I):
        return "CHF"
    if "¥" in text or "￥" in text or "円" in text or re.search(r"\bJPY\b", text, re.I):
        return "JPY"
    return "EUR"


def parse_amount_string(
    raw: Any,
    min_val: float = 0.0,
    max_val: float = 25000.0,
    currency_hint: str = "",
) -> Optional[float]:
    """Parse a numeric price or fee string in EUR/USD/GBP/CHF/JPY and convert to EUR."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        curr = (currency_hint or "EUR").upper()
        val = float(raw) * FX_RATES_TO_EUR.get(curr, 1.0)
        return round(val, 2) if min_val <= val <= max_val else None

    text = str(raw).strip()
    if not text:
        return None

    text = text.replace("\xa0", " ").replace("\u202f", " ")
    curr = _detect_currency_code(text, currency_hint)

    m_euro_sep = re.search(r"(\d[\d\s.]*)\s*€\s*(\d{2})\b", text)
    if m_euro_sep:
        whole = re.sub(r"[^\d]", "", m_euro_sep.group(1))
        cents = m_euro_sep.group(2)
        try:
            val = float(f"{whole}.{cents}")
            return round(val, 2) if min_val <= val <= max_val else None
        except ValueError:
            pass

    m_curr = re.search(
        r"(?:(?:€|EUR|US\s*\$|\$|£|GBP|CHF|¥|￥|JPY)\s*(\d{1,3}(?:[\s.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)|(\d{1,3}(?:[\s.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR\b|USD\b|\$|£|GBP\b|CHF\b|¥|￥|JPY\b|円))",
        text,
        re.I,
    )
    if m_curr:
        num_str = (m_curr.group(1) or m_curr.group(2) or "").strip()
    else:
        m = re.search(
            r"(?<![A-Za-z0-9-])(\d{1,3}(?:[\s.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![A-Za-z0-9])",
            text,
        )
        if not m:
            return None
        num_str = m.group(0)

    num_str = num_str.replace(" ", "")
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
    elif "." in num_str:
        parts = num_str.split(".")
        # Handle German/European thousands dot e.g. "1.315" when > 1 and 3 digits at end
        if len(parts[-1]) == 3 and curr in ("EUR", "JPY"):
            num_str = "".join(parts)

    try:
        raw_val = float(num_str)
        eur_val = raw_val * FX_RATES_TO_EUR.get(curr, 1.0)
        return round(eur_val, 2) if min_val <= eur_val <= max_val else None
    except ValueError:
        return None


def parse_price_string(raw: Any, currency_hint: str = "") -> Optional[float]:
    """Parse a watch product price (>= 5 €)."""
    return parse_amount_string(raw, min_val=5.0, max_val=25000.0, currency_hint=currency_hint)


def infer_watch_metadata_from_text(title: str, url: str = "", description: str = "") -> Dict[str, str]:
    """Infer brand, watch reference, and ASIN from title/URL when not explicitly in JSON-LD."""
    combined = f"{title} {description} {url}"
    brand = ""
    for b in KNOWN_WATCH_BRANDS:
        if re.search(rf"\b{re.escape(b)}\b", combined, re.I):
            brand = b
            break

    # Typical watch reference patterns: CB1160-55E, SBTM323, LCW-M100TSE-1AER, 059/2020.04, 59/2020.02, SSC813P1
    ref = ""
    ref_patterns = [
        r"\b([A-Z]{2,5}-?[A-Z0-9]{2,6}-[A-Z0-9]{2,5})\b",
        r"\b(0?\d{2}/\d{4}\.\d{2})\b",
        r"\b([A-Z]{3,4}\d{3,4}[A-Z0-9]{0,3})\b",
    ]
    for pat in ref_patterns:
        m = re.search(pat, f"{title} {url.upper()}")
        if m:
            candidate = m.group(1).strip()
            if not candidate.startswith("HTTP") and candidate not in ("HTML", "UTF-8"):
                ref = candidate
                break

    asin = ""
    m_asin = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})\b", url, re.I)
    if m_asin:
        asin = m_asin.group(1).upper()

    return {"brand": brand, "reference": ref, "asin": asin}


def extract_from_json_ld(doc: lxml_html.HtmlElement) -> Optional[Dict[str, Any]]:
    """Layer 1: Extract price, condition, shippingDetails, brand, SKU/EAN, image, and title from JSON-LD."""
    scripts = doc.xpath(
        "//script[contains(translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ld+json')]"
    )

    def _extract_shipping_from_offer(offer_obj: Dict[str, Any]) -> Optional[float]:
        ship = offer_obj.get("shippingDetails")
        if isinstance(ship, list) and ship:
            ship = ship[0]
        if isinstance(ship, dict):
            rate = ship.get("shippingRate")
            if isinstance(rate, dict):
                raw_val = rate.get("value")
                curr = str(rate.get("currency", "EUR")).upper()
                return parse_amount_string(raw_val, min_val=0.0, max_val=500.0, currency_hint=curr)
        return None

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
            title = str(node.get("name", "") or "").strip()
            desc = str(node.get("description", "") or "").strip()
            brand_obj = node.get("brand", "")
            brand = (
                str(brand_obj.get("name", ""))
                if isinstance(brand_obj, dict)
                else str(brand_obj or "")
            ).strip()
            sku = str(node.get("mpn") or node.get("model") or node.get("sku") or "").strip()
            ean = str(node.get("gtin13") or node.get("ean") or node.get("gtin") or "").strip()

            img = node.get("image", "")
            if isinstance(img, list) and img:
                img = img[0]
            if isinstance(img, dict):
                img = img.get("url", "")

            offers = node.get("offers")
            res = _extract_offers(offers)
            if res and res.get("price"):
                res["title"] = title
                res["description"] = re.sub(r"\s+", " ", desc)[:280]
                res["brand"] = brand
                res["reference"] = sku
                res["ean"] = ean
                if isinstance(img, str) and img.startswith("http"):
                    res["image_url"] = img
                return res

        for sub_key in ("@graph", "mainEntity"):
            if sub_key in node:
                res = _walk_node(node[sub_key])
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
            spec = offers.get("priceSpecification")
            if isinstance(spec, list) and spec:
                spec = spec[0]
            spec_dict = spec if isinstance(spec, dict) else {}
            currency = str(
                offers.get("priceCurrency") or spec_dict.get("priceCurrency") or "EUR"
            ).upper()
            raw_price = offers.get("price") or offers.get("lowPrice") or spec_dict.get("price")
            price = parse_price_string(raw_price, currency_hint=currency)

            if not price and isinstance(offers.get("offers"), (list, dict)):
                return _extract_offers(offers["offers"])
            if price:
                avail = str(offers.get("availability", "")).lower()
                in_stock = not any(out in avail for out in ("outofstock", "soldout", "discontinued"))
                cond_raw = str(offers.get("itemCondition", "")).lower()
                condition = None
                if any(k in cond_raw for k in ("used", "refurbished", "secondhand", "damaged")):
                    condition = "used"
                elif "new" in cond_raw:
                    condition = "new"

                ship_fee = _extract_shipping_from_offer(offers)
                high_price = parse_price_string(offers.get("highPrice"), currency_hint=currency)
                return {
                    "price": price,
                    "original_currency": currency,
                    "original_price": high_price if (high_price and high_price > price) else None,
                    "currency": "EUR",
                    "in_stock": in_stock,
                    "condition": condition,
                    "shipping_fee": ship_fee,
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
    curr_nodes = doc.xpath(
        "//*[@property='product:price:currency']/@content | //*[@property='og:price:currency']/@content | //*[@itemprop='priceCurrency']/@content"
    )
    curr = str(curr_nodes[0]).strip().upper() if curr_nodes else ""

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
            price = parse_price_string(candidate, currency_hint=curr)
            if price:
                break
        if price:
            break

    if not price:
        return None

    title_nodes = doc.xpath("//meta[@property='og:title']/@content | //title/text()")
    title = str(title_nodes[0]).strip() if title_nodes else ""

    desc_nodes = doc.xpath("//meta[@property='og:description']/@content | //meta[@name='description']/@content")
    desc = str(desc_nodes[0]).strip() if desc_nodes else ""

    img_nodes = doc.xpath("//meta[@property='og:image']/@content")
    img_url = str(img_nodes[0]).strip() if img_nodes else ""

    avail_nodes = doc.xpath(
        "//meta[@property='product:availability']/@content | //*[@itemprop='availability']/@href | //*[@itemprop='availability']/text()"
    )
    in_stock = True
    if avail_nodes:
        avail_str = " ".join(str(a).lower() for a in avail_nodes)
        if any(w in avail_str for w in ("out", "épuisé", "indisponible")):
            in_stock = False

    return {
        "price": price,
        "original_currency": curr or "EUR",
        "original_price": None,
        "currency": "EUR",
        "in_stock": in_stock,
        "title": title,
        "description": desc[:280],
        "image_url": img_url,
        "method": "opengraph-meta",
    }


def extract_from_selectors(doc: lxml_html.HtmlElement, url: str = "") -> Optional[Dict[str, Any]]:
    """Layer 3: Domain-specific XPath/CSS selectors."""
    current_xpaths = [
        # Amazon
        "//*[@id='corePriceDisplay_desktop_feature_div']//*[contains(@class, 'a-price')]//*[contains(@class, 'a-offscreen')]",
        "//*[@id='corePrice_feature_div']//*[contains(@class, 'a-price')]//*[contains(@class, 'a-offscreen')]",
        "//*[@id='priceblock_ourprice']",
        "//*[@id='priceblock_dealprice']",
        # Sakura Watches / OpenCart
        "//*[@id='product']//*[contains(@class, 'price-new')]",
        "//*[@id='content']//ul[contains(@class, 'list-unstyled')]//h2",
        "//*[contains(@class, 'price-new')]",
        # Chrono24
        "//*[contains(@class, 'js-price-shipping-country')]",
        "//*[contains(@class, 'detail-page-price')]",
        # PrestaShop / Ocarat / Horlogers
        "//*[contains(@class, 'current-price-value')]",
        "//*[contains(@class, 'product-price')]//*[contains(@class, 'price')]",
        "//*[@id='our_price_display']",
        # Catawiki
        "//*[@data-testid='lot-bid-status-section']//*[contains(text(), '€')]",
        "//*[@data-testid='bid-amount']",
        "//*[contains(@class, 'be-lot-details-bidding-panel')]//*[contains(text(), '€')]",
        "//*[contains(@class, 'c-lot-card__price')]",
        # Generic
        "//*[@data-testid='product-price']",
        "//*[contains(@class, 'f-priceBox-price')]",
        "//*[contains(@class, 'fpPrice')]",
        "//*[contains(@class, 'c-price__current')]",
        "//*[contains(@class, 'price-sales')]",
        "//*[contains(@class, 'special-price')]//*[contains(@class, 'price')]",
        "//*[contains(@class, 'final-price')]",
        "//*[contains(@class, 'price--main')]",
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

    title_nodes = doc.xpath("//*[@id='productTitle']/text() | //h1/text() | //title/text()")
    title = str(title_nodes[0]).strip() if title_nodes else ""

    desc_nodes = doc.xpath("//meta[@name='description']/@content | //meta[@property='og:description']/@content")
    desc = str(desc_nodes[0]).strip() if desc_nodes else ""

    img_nodes = doc.xpath("//meta[@property='og:image']/@content | //*[@id='landingImage']/@src")
    img_url = str(img_nodes[0]).strip() if img_nodes else ""

    if not price:
        return None

    return {
        "price": price,
        "original_price": None,
        "currency": "EUR",
        "in_stock": True,
        "title": title,
        "description": desc[:280],
        "image_url": img_url,
        "method": "css-selector",
    }


def extract_explicit_fees_and_condition(
    html_str: str,
    url: str,
    base_price: Optional[float],
    json_ld_shipping: Optional[float] = None,
    json_ld_condition: Optional[str] = None,
    import_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Detect shipping fees, site fees, customs fees, and product condition (Neuf / Occasion)
    ONLY when stated in clear text on the page or known from explicit platform rules.
    Returns None for any fee that cannot be determined so the user can fill it in.
    """
    url_lower = (url or "").lower()
    body_text = ""
    if html_str:
        try:
            doc = lxml_html.fromstring(html_str)
            body_text = re.sub(r"\s+", " ", " ".join(doc.xpath("//body//text()")))
        except Exception:
            body_text = re.sub(r"<[^>]+>", " ", html_str)

    # 1. Condition ("new" vs "used")
    condition = json_ld_condition
    if not condition:
        if any(k in url_lower for k in ("-used", "usedornew=used", "occasion", "catawiki.", "vinted.", "leboncoin.")):
            condition = "used"
        elif re.search(
            r"\b(?:état\s*:\s*(?:occasion|très\s+bon|bon\s+état)|pre-owned|gebraucht|d'occasion|seconde\s+main)\b",
            body_text,
            re.I,
        ):
            condition = "used"
        else:
            condition = "new"

    # 2. Shipping Fee (Frais de port)
    shipping_fee: Optional[float] = None
    shipping_detected = False
    shipping_reason = ""

    if json_ld_shipping is not None:
        shipping_fee = json_ld_shipping
        shipping_detected = True
        shipping_reason = "Indiqué dans les métadonnées livraison de la page"
    elif body_text:
        if re.search(
            r"(?:livraison\s+(?:gratuite|offerte)|frais\s+de\s+port\s+offerts|port\s+gratuit|free\s+(?:shipping|delivery)|versandkostenfrei|kostenloser\s+versand)",
            body_text,
            re.I,
        ):
            shipping_fee = 0.0
            shipping_detected = True
            shipping_reason = "Marqué « Livraison gratuite » sur la page"
        else:
            ship_patterns = [
                r"\+\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*€\s*(?:de\s+)?(?:frais\s+de\s+port|livraison|port)",
                r"(?:frais\s+de\s+port|frais\s+d'expédition|livraison\s+à|shipping(?:\s+cost)?|versand(?:kosten)?)\s*[:\-]?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*€",
                r"(?:shipping|delivery)\s*[:\-]?\s*€\s*(\d{1,3}(?:[.,]\d{1,2})?)",
                r"zzgl\.?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*€\s*versand",
            ]
            for pat in ship_patterns:
                m_ship = re.search(pat, body_text, re.I)
                if m_ship:
                    val = parse_amount_string(m_ship.group(1), min_val=0.0, max_val=300.0)
                    if val is not None:
                        shipping_fee = val
                        shipping_detected = True
                        shipping_reason = f"Marqué en clair sur la page ({val:.2f} €)"
                        break

    # 3. Site Fee / Buyer Protection (Frais du site)
    site_fee: Optional[float] = None
    site_fee_detected = False
    site_fee_reason = ""

    if "catawiki." in url_lower:
        if base_price is not None:
            site_fee = compute_catawiki_fee_only(base_price)
            site_fee_detected = True
            site_fee_reason = "Protection acheteur Catawiki (9 % + 3 €)"
    elif "vinted." in url_lower:
        if base_price is not None:
            site_fee = round(base_price * 0.05 + 0.70, 2)
            site_fee_detected = True
            site_fee_reason = "Protection acheteurs Vinted (5 % + 0,70 €)"
    elif body_text:
        m_site = re.search(
            r"(?:frais\s+(?:de\s+protection\s+)?acheteur|buyer\s+protection(?:\s+fee)?|frais\s+de\s+service)\s*[:\-]?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*€",
            body_text,
            re.I,
        )
        if m_site:
            val = parse_amount_string(m_site.group(1), min_val=0.0, max_val=500.0)
            if val is not None:
                site_fee = val
                site_fee_detected = True
                site_fee_reason = f"Frais acheteur indiqués sur la page ({val:.2f} €)"

    if site_fee is None and (
        is_eu_retail_url(url) or is_non_eu_import_url(url) or "chrono24." in url_lower
    ):
        site_fee = 0.0
        site_fee_detected = True
        site_fee_reason = "Aucun frais acheteur facturé par ce site (0 €)"

    # 4. Customs & Import VAT Fee (Frais de douane)
    customs_fee: Optional[float] = None
    customs_detected = False
    customs_reason = ""

    imp = import_settings or {}
    vat_rate = float(imp.get("vat_rate", 0.20))
    duty_eur = float(imp.get("customs_duty_eur", 0.80))
    carrier_eur = float(imp.get("carrier_fee_eur", 18.0))
    default_jp_ship = float(imp.get("shipping_eur", 24.0))

    if body_text:
        m_imp_dep = re.search(
            r"(?:acompte\s+frais\s+d'importation|import\s+fees\s+deposit|frais\s+de\s+douane)\s*[:\-]?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€",
            body_text,
            re.I,
        )
        if m_imp_dep:
            val = parse_amount_string(m_imp_dep.group(1), min_val=0.0, max_val=1500.0)
            if val is not None:
                customs_fee = val
                customs_detected = True
                customs_reason = f"Frais d'importation affichés sur la page ({val:.2f} €)"

    if customs_fee is None:
        non_eu_text = bool(
            body_text
            and re.search(
                r"(?:expédié\s+depuis\s+(?:le\s+)?(?:japon|royaume-uni|suisse|états-unis)|ships\s+from\s+(?:japan|united\s+kingdom|switzerland|us)|location\s*:\s*(?:japan|switzerland|uk|united\s+states)|standort\s*:\s*japan|hors\s+taxes)",
                body_text,
                re.I,
            )
        )
        if is_non_eu_import_url(url) or non_eu_text:
            if shipping_fee is None and is_non_eu_import_url(url):
                shipping_fee = default_jp_ship
                shipping_detected = True
                shipping_reason = f"Forfait express international boutique hors-UE ({default_jp_ship:.0f} €)"
            if base_price is not None:
                eff_ship = shipping_fee if shipping_fee is not None else default_jp_ship
                customs_fee = compute_japan_customs_only(
                    raw_price_ht=base_price,
                    shipping_eur=eff_ship,
                    vat_rate=vat_rate,
                    customs_duty_eur=duty_eur,
                    carrier_fee_eur=carrier_eur,
                )
                customs_detected = True
                customs_reason = "Import hors-UE : TVA 20 % + douane 0,80 € + frais dossier 18 €"
        elif is_eu_retail_url(url) or (
            body_text
            and re.search(r"\b(?:tva\s+incluse|ttc|incl\.?\s*vat|inkl\.?\s*mwst)\b", body_text, re.I)
            and "chrono24." not in url_lower
        ):
            customs_fee = 0.0
            customs_detected = True
            customs_reason = "Boutique UE / TVA incluse (0 € de douane)"

    return {
        "condition": condition,
        "shipping_fee": shipping_fee,
        "shipping_detected": shipping_detected,
        "shipping_reason": shipping_reason,
        "site_fee": site_fee,
        "site_fee_detected": site_fee_detected,
        "site_fee_reason": site_fee_reason,
        "customs_fee": customs_fee,
        "customs_detected": customs_detected,
        "customs_reason": customs_reason,
    }


def extract_metadata_only(doc: lxml_html.HtmlElement, url: str = "") -> Dict[str, Any]:
    """Extract product metadata (title, description, image_url, brand, reference, ean, asin) even if price is absent."""
    title_nodes = doc.xpath(
        "//meta[@property='og:title']/@content | //*[@id='productTitle']/text() | //h1/text() | //title/text()"
    )
    title = ""
    for t in title_nodes:
        ts = re.sub(r"\s+", " ", str(t)).strip()
        if ts:
            title = ts
            break

    desc_nodes = doc.xpath("//meta[@property='og:description']/@content | //meta[@name='description']/@content")
    desc = re.sub(r"\s+", " ", str(desc_nodes[0])).strip()[:280] if desc_nodes else ""

    img_nodes = doc.xpath(
        "//meta[@property='og:image']/@content | //*[@id='landingImage']/@src | //meta[@name='twitter:image']/@content"
    )
    img_url = str(img_nodes[0]).strip() if img_nodes else ""

    brand = ""
    sku = ""
    ean = ""
    scripts = doc.xpath(
        "//script[contains(translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ld+json')]"
    )
    for script in scripts:
        raw_text = script.text_content() or ""
        try:
            data = json.loads(raw_text.strip())
            nodes = data if isinstance(data, list) else [data]
            for n in nodes:
                if isinstance(n, dict) and "product" in str(n.get("@type", "")).lower():
                    b_obj = n.get("brand", "")
                    brand = brand or (
                        str(b_obj.get("name", "")) if isinstance(b_obj, dict) else str(b_obj or "")
                    ).strip()
                    sku = sku or str(n.get("mpn") or n.get("model") or n.get("sku") or "").strip()
                    ean = ean or str(n.get("gtin13") or n.get("ean") or n.get("gtin") or "").strip()
                    if not img_url:
                        im = n.get("image", "")
                        if isinstance(im, list) and im:
                            im = im[0]
                        if isinstance(im, dict):
                            im = im.get("url", "")
                        if isinstance(im, str) and im.startswith("http"):
                            img_url = im
        except Exception:
            continue

    inferred = infer_watch_metadata_from_text(title, url, desc)
    return {
        "title": title,
        "description": desc,
        "image_url": img_url,
        "brand": brand or inferred["brand"],
        "reference": sku or inferred["reference"],
        "ean": ean,
        "asin": inferred["asin"],
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

    meta_fallback = extract_metadata_only(doc, url)
    for extra in (res_meta, res_sel, meta_fallback):
        if extra:
            for field_name in ("title", "description", "image_url", "original_price", "brand", "reference", "ean", "asin"):
                if not primary.get(field_name) and extra.get(field_name):
                    primary[field_name] = extra[field_name]

    return primary


def fetch_html_playwright(url: str, timeout_ms: int = 15000) -> Optional[str]:
    """Layer 4: Headless Chromium fallback via Playwright."""
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


def inspect_product_url(
    url: str,
    html_str: Optional[str] = None,
    timeout: int = 12,
    use_playwright_fallback: bool = True,
    import_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Inspect a product URL: returns merchant, title, brand, reference, ean, asin,
    description, image_url, condition, base_price, and any explicitly detectable fees.
    """
    merchant = infer_merchant_name(url)
    fetch_error = None

    if html_str is None:
        try:
            status, text = http_get_text(url, timeout=timeout)
            if status == 200 and len(text) > 300:
                html_str = text
            else:
                fetch_error = f"HTTP {status}"
        except Exception as exc:
            fetch_error = str(exc)

        if (not html_str or not extract_from_html(html_str, url)) and use_playwright_fallback:
            pw_html = fetch_html_playwright(url, timeout_ms=timeout * 1000)
            if pw_html:
                html_str = pw_html

    extracted = extract_from_html(html_str, url) if html_str else None
    meta_only: Dict[str, Any] = {}
    if html_str and not extracted:
        try:
            meta_only = extract_metadata_only(lxml_html.fromstring(html_str), url)
        except Exception:
            meta_only = {}

    base_price = extracted.get("price") if extracted else None
    fees = extract_explicit_fees_and_condition(
        html_str=html_str or "",
        url=url,
        base_price=base_price,
        json_ld_shipping=extracted.get("shipping_fee") if extracted else None,
        json_ld_condition=extracted.get("condition") if extracted else None,
        import_settings=import_settings,
    )

    title = (extracted.get("title") if extracted else "") or meta_only.get("title", "")
    description = (extracted.get("description") if extracted else "") or meta_only.get("description", "")
    inferred = infer_watch_metadata_from_text(title, url, description)

    return {
        "url": url,
        "merchant": merchant,
        "title": title,
        "description": description,
        "brand": (extracted.get("brand") if extracted else "") or meta_only.get("brand", "") or inferred["brand"],
        "reference": (extracted.get("reference") if extracted else "") or meta_only.get("reference", "") or inferred["reference"],
        "ean": (extracted.get("ean") if extracted else "") or meta_only.get("ean", ""),
        "asin": (extracted.get("asin") if extracted else "") or meta_only.get("asin", "") or inferred["asin"],
        "image_url": (extracted.get("image_url") if extracted else "") or meta_only.get("image_url", ""),
        "base_price": base_price,
        "original_currency": (extracted.get("original_currency") if extracted else "EUR") or "EUR",
        "condition": fees["condition"],
        "shipping_fee": fees["shipping_fee"],
        "shipping_detected": fees["shipping_detected"],
        "shipping_reason": fees["shipping_reason"],
        "site_fee": fees["site_fee"],
        "site_fee_detected": fees["site_fee_detected"],
        "site_fee_reason": fees["site_fee_reason"],
        "customs_fee": fees["customs_fee"],
        "customs_detected": fees["customs_detected"],
        "customs_reason": fees["customs_reason"],
        "error": None if base_price is not None else (fetch_error or "Prix non détecté automatiquement"),
    }


def scrape_offer(
    watch_id: str,
    url: str,
    merchant: str = "",
    condition: str = "new",
    shipping_fee: Optional[float] = None,
    site_fee: Optional[float] = None,
    customs_fee: Optional[float] = None,
    manual_price: Optional[float] = None,
    timeout: int = 15,
    use_playwright_fallback: bool = True,
    import_settings: Optional[Dict[str, Any]] = None,
) -> OfferResult:
    """Scrape a user-configured product URL and apply explicit or auto-detected fees."""
    merchant_name = infer_merchant_name(url, merchant)
    now_iso = datetime.now(timezone.utc).isoformat()

    html_str = None
    http_error = None
    try:
        status, text = http_get_text(url, timeout=timeout)
        if status == 200 and len(text) > 400:
            html_str = text
        else:
            http_error = f"HTTP {status}"
    except Exception as exc:
        http_error = str(exc)

    extracted = extract_from_html(html_str, url) if html_str else None

    if not extracted and use_playwright_fallback:
        pw_html = fetch_html_playwright(url, timeout_ms=timeout * 1000)
        if pw_html:
            html_str = pw_html
            extracted = extract_from_html(pw_html, url)
            if extracted:
                extracted["method"] = f"playwright+{extracted.get('method', 'dom')}"

    base_price = extracted.get("price") if (extracted and extracted.get("price")) else manual_price
    if base_price is not None:
        detected = extract_explicit_fees_and_condition(
            html_str=html_str or "",
            url=url,
            base_price=base_price,
            json_ld_shipping=extracted.get("shipping_fee") if extracted else None,
            json_ld_condition=extracted.get("condition") if extracted else None,
            import_settings=import_settings,
        )

        eff_condition = condition or detected["condition"] or "new"
        eff_ship = shipping_fee if shipping_fee is not None else (detected["shipping_fee"] or 0.0)
        eff_site = site_fee if site_fee is not None else (detected["site_fee"] or 0.0)
        eff_cust = customs_fee if customs_fee is not None else (detected["customs_fee"] or 0.0)
        total_price = round(base_price + eff_ship + eff_site + eff_cust, 2)

        fee_notes = []
        if detected["shipping_reason"] and shipping_fee is None:
            fee_notes.append(detected["shipping_reason"])
        if detected["site_fee_reason"] and site_fee is None and eff_site > 0:
            fee_notes.append(detected["site_fee_reason"])
        if detected["customs_reason"] and customs_fee is None and eff_cust > 0:
            fee_notes.append(detected["customs_reason"])

        return OfferResult(
            watch_id=watch_id,
            merchant=merchant_name,
            url=url,
            price=total_price,
            base_price=round(base_price, 2),
            condition=eff_condition,
            shipping_fee=round(eff_ship, 2),
            site_fee=round(eff_site, 2),
            customs_fee=round(eff_cust, 2),
            shipping_detected=(shipping_fee is None and detected["shipping_detected"]),
            site_fee_detected=(site_fee is None and detected["site_fee_detected"]),
            customs_detected=(customs_fee is None and detected["customs_detected"]),
            fee_notes=fee_notes,
            original_price=extracted.get("original_price") if extracted else None,
            currency="EUR",
            in_stock=extracted.get("in_stock", True) if extracted else True,
            title=(extracted.get("title") if extracted else "") or "",
            extraction_method=(extracted.get("method") if extracted else "manual-price"),
            timestamp=now_iso,
        )

    return OfferResult(
        watch_id=watch_id,
        merchant=merchant_name,
        url=url,
        price=None,
        base_price=None,
        condition=condition or "new",
        shipping_fee=round(shipping_fee or 0.0, 2),
        site_fee=round(site_fee or 0.0, 2),
        customs_fee=round(customs_fee or 0.0, 2),
        in_stock=False,
        extraction_method="failed",
        timestamp=now_iso,
        error=http_error or "Prix non détecté sur la page",
    )
