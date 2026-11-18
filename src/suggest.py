"""On-demand product page suggestion helper (never adds URLs automatically)."""

import re
from typing import List, Dict, Any
from urllib.parse import quote_plus

from lxml import html as lxml_html

from src.models import WatchConfig, SuggestedURL
from src.scraper import (
    http_get_text,
    parse_price_string,
    compute_catawiki_fee_only,
    compute_japan_customs_only,
)


def parse_chrono24_suggestions(html_str: str, watch: WatchConfig, existing_urls: set) -> List[SuggestedURL]:
    """Extract real listing URLs from a Chrono24 reference page if fetched on demand."""
    results: List[SuggestedURL] = []
    if not html_str:
        return results
    try:
        doc = lxml_html.fromstring(html_str)
        links = doc.xpath("//a[contains(@href, '--id') and contains(@href, '.htm')]")
        seen = set()
        for link in links:
            href = link.get("href", "")
            if not href:
                continue
            full_url = href if href.startswith("http") else f"https://www.chrono24.fr{href}"
            full_url = full_url.split("?")[0]
            if full_url in seen or full_url in existing_urls:
                continue
            text = re.sub(r"\s+", " ", link.text_content()).strip()
            price = parse_price_string(text)
            if not price:
                continue
            cond = "used" if re.search(r"\b(?:occasion|pre-owned|très\s+bon|used)\b", text, re.I) else "new"
            ship = 0.0
            m_ship = re.search(r"\+\s*(\d{1,3})\s*€\s*(?:de\s+)?frais\s+de\s+port", text, re.I)
            if m_ship:
                ship = float(m_ship.group(1))
            is_jp = bool(re.search(r"\bJP\b", text))
            cust = compute_japan_customs_only(price, ship or 28.0) if is_jp else 0.0
            seen.add(full_url)
            results.append(
                SuggestedURL(
                    url=full_url,
                    merchant="Chrono24" + (" (Japon)" if is_jp else " (UE)"),
                    title=text[:110] or f"{watch.brand} {watch.reference}",
                    condition=cond,
                    estimated_base_price=price,
                    shipping_fee=ship,
                    site_fee=0.0,
                    customs_fee=cust,
                    fee_hint="Import JP (TVA 20% + douane)" if is_jp else "Vendeur UE • Protection Chrono24 0 €",
                )
            )
            if len(results) >= 4:
                break
    except Exception:
        pass
    return results


def build_fallback_suggestions_for_custom_watch(watch: WatchConfig, existing_urls: set) -> List[SuggestedURL]:
    """Build helpful candidate pages for a user-added watch reference."""
    ref_clean = watch.reference.strip()
    brand_clean = watch.brand.strip()
    q = quote_plus(f"{brand_clean} {ref_clean}".strip())
    ref_q = quote_plus(ref_clean)

    candidates = [
        SuggestedURL(
            url=f"https://www.amazon.fr/s?k={q}",
            merchant="Amazon.fr",
            title=f"Rechercher {brand_clean} {ref_clean} (Neuf vendu/expédié UE)",
            condition="new",
            shipping_fee=0.0,
            site_fee=0.0,
            customs_fee=0.0,
            fee_hint="Livraison gratuite UE • TVA incluse (0 € douane)",
        ),
        SuggestedURL(
            url=f"https://ocarat.com/recherche?controller=search&s={q}",
            merchant="Ocarat",
            title=f"Horloger agréé France — {brand_clean} {ref_clean}",
            condition="new",
            shipping_fee=0.0,
            site_fee=0.0,
            customs_fee=0.0,
            fee_hint="Boutique française • Port offert & 0 € douane",
        ),
        SuggestedURL(
            url=f"https://www.chrono24.fr/search/index.htm?query={ref_q}&usedOrNew=used",
            merchant="Chrono24 (Occasion)",
            title=f"Annonces Seconde Main vérifiées — {brand_clean} {ref_clean}",
            condition="used",
            shipping_fee=15.0,
            site_fee=0.0,
            customs_fee=0.0,
            fee_hint="Protection acheteur Chrono24 incluse (0 € frais site)",
        ),
        SuggestedURL(
            url=f"https://www.catawiki.com/fr/s?q={q}",
            merchant="Catawiki",
            title=f"Ventes aux enchères horlogerie — {brand_clean} {ref_clean}",
            condition="used",
            shipping_fee=18.0,
            site_fee=None,
            customs_fee=0.0,
            fee_hint="Frais Catawiki : 9 % + 3 € calculés automatiquement",
        ),
        SuggestedURL(
            url=f"https://www.sakurawatches.com/search/?search={ref_q}",
            merchant="Sakura Watches (Tokyo)",
            title=f"Import direct Japon (JDM) — {ref_clean}",
            condition="new",
            shipping_fee=24.0,
            site_fee=0.0,
            customs_fee=None,
            fee_hint="Hors-UE : Port DHL ~24 € + TVA 20 % + douane/dossier pré-remplis",
        ),
    ]
    return [c for c in candidates if c.url not in existing_urls]


def propose_product_pages(
    watch: WatchConfig,
    live_fetch: bool = False,
    timeout: int = 8,
) -> List[Dict[str, Any]]:
    """
    Return candidate product pages that the user can choose to add to a watch card.
    Never modifies watch.urls automatically.
    """
    existing = {u.url.rstrip("/") for u in watch.urls}
    proposals: List[SuggestedURL] = []

    # 1. Verified curated product pages not yet added by the user
    for s in watch.suggested_urls:
        if s.url.rstrip("/") not in existing:
            proposals.append(s)

    # 2. Optional live Chrono24 fetch when requested via local server or CLI
    if live_fetch and watch.reference:
        slug_brand = re.sub(r"[^a-z0-9]+", "", watch.brand.lower())
        slug_ref = re.sub(r"[^a-z0-9]+", "", watch.reference.lower())
        c24_ref_url = f"https://www.chrono24.fr/{slug_brand}/ref-{slug_ref}.htm"
        try:
            status, html_text = http_get_text(c24_ref_url, timeout=timeout)
            if status == 200 and html_text:
                live_items = parse_chrono24_suggestions(html_text, watch, existing)
                for item in live_items:
                    if all(p.url != item.url for p in proposals):
                        proposals.append(item)
        except Exception:
            pass

    # 3. Fallback suggestions if watch was newly created by user without curated suggestions
    if not proposals:
        proposals.extend(build_fallback_suggestions_for_custom_watch(watch, existing))

    out: List[Dict[str, Any]] = []
    for p in proposals:
        d = p.to_dict()
        # Pre-compute site_fee or customs_fee if base price is known
        base = p.estimated_base_price
        if base is not None:
            if d["site_fee"] is None and "catawiki." in p.url.lower():
                d["site_fee"] = compute_catawiki_fee_only(base)
            if d["customs_fee"] is None and "sakurawatches." in p.url.lower():
                d["customs_fee"] = compute_japan_customs_only(base, d["shipping_fee"] or 24.0)
        out.append(d)
    return out
