"""Automatic offer and deal discovery engine by watch reference and keywords (Dealabs, Idealo, Catawiki)."""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Set
from urllib.parse import quote_plus

from lxml import html as lxml_html

from src.models import WatchConfig, OfferResult
from src.scraper import http_get_text, parse_price_string, compute_catawiki_price_with_fees


def parse_dealabs_html_or_rss(content: str, watch: WatchConfig) -> List[OfferResult]:
    """Parse Dealabs search HTML or RSS feed to extract matching watch deals."""
    results: List[OfferResult] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    ref_norm = re.sub(r"[^a-z0-9]", "", watch.reference.lower())
    brand_norm = watch.brand.lower()

    if content.lstrip().startswith("<?xml") or "<rss" in content[:300]:
        try:
            root = ET.fromstring(content)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                combined = f"{title} {desc}"
                price = parse_price_string(title) or parse_price_string(desc)
                if price and (ref_norm[:6] in re.sub(r"[^a-z0-9]", "", combined.lower()) or brand_norm in combined.lower()):
                    results.append(
                        OfferResult(
                            watch_id=watch.id,
                            merchant="Dealabs (Communauté)",
                            url=link,
                            price=price,
                            title=title,
                            extraction_method="dealabs-rss",
                            timestamp=now_iso,
                            is_discovered=True,
                        )
                    )
            if results:
                return results
        except Exception:
            pass

    try:
        doc = lxml_html.fromstring(content)
    except Exception:
        return results

    articles = doc.xpath("//article[contains(@class, 'thread')] | //div[contains(@class, 'threadGrid')] | //*[@data-t='thread']")
    for art in articles:
        title_links = art.xpath(".//*[contains(@class, 'thread-title')]//a | .//a[contains(@class, 'thread-link')] | .//*[@data-t='threadLink']")
        if not title_links:
            continue
        title_el = title_links[0]
        title = " ".join(title_el.text_content().split())
        href = title_el.get("href", "")
        if href.startswith("/"):
            href = "https://www.dealabs.com" + href

        price_nodes = art.xpath(".//*[contains(@class, 'thread-price')] | .//*[@data-t='threadPrice']")
        price_text = price_nodes[0].text_content() if price_nodes else title
        price = parse_price_string(price_text)
        if not price:
            continue

        old_nodes = art.xpath(".//del | .//strike")
        old_price = parse_price_string(old_nodes[0].text_content()) if old_nodes else None

        temp_nodes = art.xpath(".//*[contains(@class, 'vote-temp')] | .//*[contains(@class, 'cept-vote-temp')]")
        temperature = temp_nodes[0].text_content().strip() if temp_nodes else None

        merch_nodes = art.xpath(".//*[contains(@class, 'cept-merchant-name')] | .//*[@data-t='merchantLink']")
        merchant_label = f"Dealabs • {merch_nodes[0].text_content().strip()}" if merch_nodes else "Dealabs"

        results.append(
            OfferResult(
                watch_id=watch.id,
                merchant=merchant_label,
                url=href,
                price=price,
                original_price=old_price if (old_price and old_price > price) else None,
                title=title,
                extraction_method="dealabs-search",
                timestamp=now_iso,
                is_discovered=True,
                temperature=temperature,
            )
        )

    return results


def parse_catawiki_html(content: str, watch: WatchConfig) -> List[OfferResult]:
    """Parse Catawiki auction search/category HTML and compute fee-inclusive prices (bid + 9% + 3€)."""
    results: List[OfferResult] = []
    if not content or not content.strip():
        return results

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        doc = lxml_html.fromstring(content)
    except Exception:
        return results

    cards = doc.xpath(
        "//article[contains(@class, 'c-lot-card')] | "
        "//*[@data-testid='lot-card'] | "
        "//a[contains(@href, '/l/')]/ancestor::article[1] | "
        "//a[contains(@href, '/l/')]"
    )
    seen_hrefs: Set[str] = set()
    for card in cards[:8]:
        if card.tag == "a":
            href = card.get("href", "")
            link_el = card
        else:
            links = card.xpath(".//a[contains(@href, '/l/')] | .//a[@href]")
            if not links:
                continue
            link_el = links[0]
            href = link_el.get("href", "")

        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.catawiki.com" + href
        if href in seen_hrefs:
            continue

        title_nodes = card.xpath(
            ".//*[contains(@class, 'c-lot-card__title')] | "
            ".//*[@data-testid='lot-card-title'] | "
            ".//h2 | .//h3 | .//p[1]"
        )
        title = " ".join(
            (title_nodes[0].text_content() if title_nodes else link_el.text_content()).split()
        )
        if not title:
            continue

        price_nodes = card.xpath(
            ".//*[contains(@class, 'c-lot-card__price')] | "
            ".//*[@data-testid='lot-card-price'] | "
            ".//*[contains(text(), '€')]"
        )
        raw_bid = parse_price_string(
            price_nodes[0].text_content() if price_nodes else card.text_content()
        )
        if not raw_bid:
            continue

        seen_hrefs.add(href)
        total_with_fees = compute_catawiki_price_with_fees(raw_bid)
        results.append(
            OfferResult(
                watch_id=watch.id,
                merchant="Catawiki (Enchères)",
                url=href,
                price=total_with_fees,
                title=title,
                extraction_method="catawiki-auction",
                shipping_note=f"🔨 Enchère {raw_bid:.0f} € + 9% + 3€ frais Catawiki inclus (hors port)",
                timestamp=now_iso,
                is_discovered=True,
            )
        )

    return results


def discover_offers_for_watch(
    watch: WatchConfig,
    existing_urls: Set[str],
    timeout: int = 12,
) -> List[OfferResult]:
    """Search Dealabs, Idealo, and Catawiki auctions for offers matching the watch."""
    discovered: List[OfferResult] = []
    seen_urls = set(existing_urls)

    queries = watch.search_queries or [f"{watch.brand} {watch.reference}"]
    for query in queries[:2]:
        encoded = quote_plus(query)

        # 1. Dealabs search
        dealabs_url = f"https://www.dealabs.com/search?q={encoded}"
        try:
            status, text = http_get_text(dealabs_url, timeout=timeout)
            if status == 200:
                for d in parse_dealabs_html_or_rss(text, watch):
                    if d.url not in seen_urls:
                        seen_urls.add(d.url)
                        discovered.append(d)
        except Exception:
            pass

        # 2. Idealo FR search
        idealo_url = f"https://www.idealo.fr/prechcat.html?q={encoded}"
        try:
            status, text = http_get_text(idealo_url, timeout=timeout)
            if status == 200:
                doc = lxml_html.fromstring(text)
                cards = doc.xpath("//*[@data-testid='productCard'] | //*[contains(@class, 'sr-resultList__item')]")
                for card in cards[:3]:
                    t_nodes = card.xpath(".//*[@data-testid='productCard-title'] | .//*[contains(@class, 'sr-productSummary__title')]")
                    p_nodes = card.xpath(".//*[@data-testid='productCard-price'] | .//*[contains(@class, 'sr-detailedPriceInfo__price')]")
                    a_nodes = card.xpath(".//a[@href]")
                    price = parse_price_string(p_nodes[0].text_content() if p_nodes else "")
                    if price and a_nodes:
                        href = a_nodes[0].get("href", "")
                        if href.startswith("/"):
                            href = "https://www.idealo.fr" + href
                        if href not in seen_urls:
                            seen_urls.add(href)
                            discovered.append(
                                OfferResult(
                                    watch_id=watch.id,
                                    merchant="Idealo Comparateur",
                                    url=href,
                                    price=price,
                                    title=" ".join(t_nodes[0].text_content().split()) if t_nodes else watch.name,
                                    extraction_method="idealo-discovery",
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    is_discovered=True,
                                )
                            )
        except Exception:
            pass

        # 3. Catawiki Auctions search
        catawiki_url = f"https://www.catawiki.com/fr/s?q={encoded}"
        try:
            status, text = http_get_text(catawiki_url, timeout=timeout)
            if status == 200:
                for lot in parse_catawiki_html(text, watch)[:2]:
                    if lot.url not in seen_urls:
                        seen_urls.add(lot.url)
                        discovered.append(lot)
        except Exception:
            pass

    return discovered
