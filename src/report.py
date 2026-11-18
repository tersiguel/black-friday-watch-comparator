"""Keepa-style HTML Web Application generator (1 Card per Watch Reference, Neuf & Occasion curves, Fee Pre-filler)."""

import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.models import WatchAnalysis
from src.suggest import propose_product_pages


def _serialize_app_payload(
    analyses: List[WatchAnalysis],
    history: Dict[str, Any],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    watches_payload: List[Dict[str, Any]] = []
    for a in analyses:
        w = a.watch
        w_hist = history.get("watches", {}).get(w.id, {})
        entries = w_hist.get("entries", [])

        offers_list = []
        # Match configured URLs with their latest OfferResult
        offer_by_url = {o.url: o for o in a.offers}
        for u in w.urls:
            o = offer_by_url.get(u.url)
            base_p = o.base_price if (o and o.base_price is not None) else u.manual_price
            ship_f = o.shipping_fee if o else (u.shipping_fee or 0.0)
            site_f = o.site_fee if o else (u.site_fee or 0.0)
            cust_f = o.customs_fee if o else (u.customs_fee or 0.0)
            tot_p = (
                round(base_p + ship_f + site_f + cust_f, 2)
                if base_p is not None
                else None
            )
            offers_list.append(
                {
                    "url": u.url,
                    "merchant": (o.merchant if o and o.merchant else u.merchant) or "Marchand",
                    "condition": (o.condition if o else u.condition) or "new",
                    "base_price": base_p,
                    "shipping_fee": round(ship_f, 2),
                    "site_fee": round(site_f, 2),
                    "customs_fee": round(cust_f, 2),
                    "total_price": tot_p,
                    "shipping_detected": bool(o.shipping_detected) if o else (u.shipping_fee is not None),
                    "site_fee_detected": bool(o.site_fee_detected) if o else (u.site_fee is not None),
                    "customs_detected": bool(o.customs_detected) if o else (u.customs_fee is not None),
                    "title": (o.title if o else "") or "",
                    "in_stock": bool(o.in_stock) if o else True,
                    "error": o.error if o else None,
                }
            )

        suggestions = propose_product_pages(w, live_fetch=False)

        watches_payload.append(
            {
                "id": w.id,
                "name": w.name,
                "brand": w.brand,
                "reference": w.reference,
                "ean": w.ean,
                "asin": w.asin,
                "image_url": w.image_url,
                "features": w.features,
                "specs": w.specs,
                "target_price_new": w.target_price_new,
                "target_price_used": w.target_price_used,
                "reference_price": w.reference_price,
                "urls": offers_list,
                "suggested_urls": suggestions,
                "history": entries,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "currency": settings.get("currency", "EUR"),
            "ntfy_server": settings.get("ntfy_server", "https://ntfy.sh"),
            "ntfy_topic": settings.get("ntfy_topic", "bf-montres-solaires-2026"),
            "japan_import": settings.get(
                "japan_import",
                {
                    "shipping_eur": 24.0,
                    "vat_rate": 0.20,
                    "customs_duty_eur": 0.80,
                    "carrier_fee_eur": 18.0,
                },
            ),
        },
        "watches": watches_payload,
    }


def generate_html_report(
    analyses: List[WatchAnalysis],
    history: Dict[str, Any],
    settings: Dict[str, Any],
    output_path: str,
) -> str:
    """Generate the self-contained Keepa-style HTML product tracker."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    docs_dir = os.path.dirname(os.path.abspath(output_path))

    # Write Service Worker for native Chrome notifications
    sw_path = os.path.join(docs_dir, "sw.js")
    sw_code = """self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || './';
  event.waitUntil(clients.openWindow(targetUrl));
});
"""
    with open(sw_path, "w", encoding="utf-8") as swf:
        swf.write(sw_code)

    payload = _serialize_app_payload(analyses, history, settings)
    payload_json = json.dumps(payload, ensure_ascii=False)

    html_content = HTML_TEMPLATE.replace("__INITIAL_APP_DATA__", payload_json)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Also write latest_summary.json alongside index.html
    summary_path = os.path.join(docs_dir, "latest_summary.json")
    with open(summary_path, "w", encoding="utf-8") as sf:
        json.dump(
            {
                "updated_at": payload["generated_at"],
                "watches_count": len(payload["watches"]),
                "watches": [
                    {
                        "id": w["id"],
                        "reference": w["reference"],
                        "target_price_new": w["target_price_new"],
                        "target_price_used": w["target_price_used"],
                        "urls_count": len(w["urls"]),
                    }
                    for w in payload["watches"]
                ],
            },
            sf,
            indent=2,
            ensure_ascii=False,
        )

    return output_path


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>KeepaWatch — Suivi Prix Montres Neuf & Occasion (Frais Inclus)</title>
  <meta name="description" content="Suivi de prix style Keepa par référence horlogère : courbes Neuf & Occasion, calcul des frais de port, frais du site et douane, alertes de seuil." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg-page: #f2f4f8;
      --bg-card: #ffffff;
      --bg-subtle: #f8fafc;
      --bg-muted: #f1f5f9;
      --border: #dde3ec;
      --border-strong: #cbd5e1;
      --text-main: #0f172a;
      --text-secondary: #475569;
      --text-muted: #64748b;

      /* Keepa-inspired semantic colors */
      --new-color: #2563eb;
      --new-bg: #eff6ff;
      --new-border: #bfdbfe;

      --used-color: #d97706;
      --used-bg: #fffbeb;
      --used-border: #fde68a;

      --success: #059669;
      --success-bg: #ecfdf5;
      --success-border: #a7f3d0;

      --danger: #dc2626;
      --danger-bg: #fef2f2;

      --header-bg: #1e293b;
      --header-text: #f8fafc;

      --shadow-card: 0 1px 3px rgba(15, 23, 42, 0.06), 0 4px 12px rgba(15, 23, 42, 0.04);
      --radius-lg: 12px;
      --radius-md: 8px;
      --radius-sm: 6px;
    }

    html[data-theme="dark"] {
      --bg-page: #0b1120;
      --bg-card: #151f32;
      --bg-subtle: #1b273d;
      --bg-muted: #24324b;
      --border: #2a3954;
      --border-strong: #3b4f73;
      --text-main: #f1f5f9;
      --text-secondary: #cbd5e1;
      --text-muted: #94a3b8;

      --new-color: #38bdf8;
      --new-bg: rgba(56, 189, 248, 0.12);
      --new-border: rgba(56, 189, 248, 0.35);

      --used-color: #fbbf24;
      --used-bg: rgba(251, 191, 36, 0.12);
      --used-border: rgba(251, 191, 36, 0.35);

      --success: #34d399;
      --success-bg: rgba(52, 211, 153, 0.12);
      --success-border: rgba(52, 211, 153, 0.35);

      --danger: #f87171;
      --danger-bg: rgba(248, 113, 113, 0.12);

      --header-bg: #090e1a;
      --shadow-card: 0 4px 18px rgba(0, 0, 0, 0.35);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      padding: 0;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg-page);
      color: var(--text-main);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    /* Top Keepa-style Navigation Bar */
    .topbar {
      position: sticky;
      top: 0;
      z-index: 100;
      background: var(--header-bg);
      color: var(--header-text);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    }

    .topbar-inner {
      max-width: 1180px;
      margin: 0 auto;
      padding: 12px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
    }

    .brand-logo {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
      font-size: 17px;
      letter-spacing: -0.02em;
      color: #ffffff;
    }

    .brand-logo .keepa-bars {
      display: inline-flex;
      align-items: flex-end;
      gap: 2px;
      height: 18px;
    }

    .brand-logo .keepa-bars span {
      width: 4px;
      border-radius: 2px;
      background: #38bdf8;
    }
    .brand-logo .keepa-bars span:nth-child(1) { height: 8px; background: #94a3b8; }
    .brand-logo .keepa-bars span:nth-child(2) { height: 13px; background: #fbbf24; }
    .brand-logo .keepa-bars span:nth-child(3) { height: 18px; background: #38bdf8; }

    .search-box {
      flex: 1;
      min-width: 220px;
      max-width: 360px;
      position: relative;
    }

    .search-box input {
      width: 100%;
      padding: 8px 12px 8px 34px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.18);
      background: rgba(255, 255, 255, 0.1);
      color: #ffffff;
      font-size: 13.5px;
      outline: none;
      transition: border-color 0.15s, background 0.15s;
    }

    .search-box input::placeholder {
      color: rgba(255, 255, 255, 0.6);
    }

    .search-box input:focus {
      background: rgba(255, 255, 255, 0.16);
      border-color: #38bdf8;
    }

    .search-box .search-icon {
      position: absolute;
      left: 11px;
      top: 50%;
      transform: translateY(-50%);
      font-size: 13px;
      opacity: 0.7;
      pointer-events: none;
    }

    .topbar-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 13px;
      border-radius: var(--radius-sm);
      font-family: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.15s ease;
      text-decoration: none;
      white-space: nowrap;
    }

    .btn-primary {
      background: #2563eb;
      color: #ffffff;
    }
    .btn-primary:hover {
      background: #1d4ed8;
    }

    .btn-topbar {
      background: rgba(255, 255, 255, 0.1);
      color: #f8fafc;
      border-color: rgba(255, 255, 255, 0.16);
    }
    .btn-topbar:hover {
      background: rgba(255, 255, 255, 0.18);
    }

    .btn-outline {
      background: var(--bg-card);
      color: var(--text-main);
      border-color: var(--border-strong);
    }
    .btn-outline:hover {
      background: var(--bg-muted);
    }

    .btn-suggest {
      background: var(--used-bg);
      color: var(--used-color);
      border-color: var(--used-border);
    }
    .btn-suggest:hover {
      filter: brightness(0.97);
    }

    .btn-sm {
      padding: 5px 10px;
      font-size: 12px;
    }

    /* Filter Bar */
    .filter-strip {
      max-width: 1180px;
      margin: 18px auto 6px;
      padding: 0 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .brand-pills {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }

    .filter-pill {
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 12.5px;
      font-weight: 600;
      background: var(--bg-card);
      color: var(--text-secondary);
      border: 1px solid var(--border);
      cursor: pointer;
      transition: all 0.15s;
    }
    .filter-pill:hover {
      border-color: var(--border-strong);
      color: var(--text-main);
    }
    .filter-pill.active {
      background: var(--text-main);
      color: var(--bg-card);
      border-color: var(--text-main);
    }

    .server-status {
      font-size: 12px;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      display: inline-block;
    }

    /* Main Container: Vertical Stack of Cards (1 Card per Reference) */
    .cards-container {
      max-width: 1180px;
      margin: 12px auto 60px;
      padding: 0 20px;
      display: flex;
      flex-direction: column;
      gap: 28px;
    }

    .watch-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-card);
      overflow: hidden;
    }

    /* 1. Product Presentation Header */
    .card-product-header {
      padding: 24px 26px 20px;
      display: grid;
      grid-template-columns: 148px 1fr auto;
      gap: 24px;
      align-items: start;
      border-bottom: 1px solid var(--border);
    }

    .watch-photo-box {
      width: 148px;
      height: 148px;
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      position: relative;
    }

    .watch-photo-box img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      transition: transform 0.2s ease;
    }
    .watch-photo-box:hover img {
      transform: scale(1.05);
    }

    .watch-info {
      min-width: 0;
    }

    .watch-brand-row {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 4px;
    }

    .brand-tag {
      font-size: 11.5px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--new-color);
    }

    .watch-title {
      margin: 0 0 8px;
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.015em;
      color: var(--text-main);
      line-height: 1.3;
    }

    .id-badges {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }

    .id-chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 9px;
      border-radius: 5px;
      background: var(--bg-muted);
      border: 1px solid var(--border);
      font-family: 'JetBrains Mono', monospace;
      font-size: 11.5px;
      color: var(--text-secondary);
      cursor: pointer;
    }
    .id-chip:hover {
      border-color: var(--border-strong);
      color: var(--text-main);
    }

    .watch-description {
      margin: 0 0 12px;
      font-size: 14px;
      color: var(--text-secondary);
      line-height: 1.55;
      max-width: 680px;
    }

    .spec-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .spec-pill {
      font-size: 12px;
      padding: 4px 10px;
      border-radius: 6px;
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      color: var(--text-secondary);
    }
    .spec-pill strong {
      color: var(--text-main);
      font-weight: 600;
    }

    /* Right Keepa Price Summary */
    .price-summary-col {
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 215px;
      align-items: stretch;
    }

    .price-kpi {
      padding: 10px 14px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .price-kpi.kpi-new {
      background: var(--new-bg);
      border-color: var(--new-border);
    }

    .price-kpi.kpi-used {
      background: var(--used-bg);
      border-color: var(--used-border);
    }

    .price-kpi-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 11.5px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .kpi-new .price-kpi-top { color: var(--new-color); }
    .kpi-used .price-kpi-top { color: var(--used-color); }

    .price-kpi-val {
      font-family: 'JetBrains Mono', monospace;
      font-size: 21px;
      font-weight: 700;
      color: var(--text-main);
    }

    .price-kpi-sub {
      font-size: 11.5px;
      color: var(--text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .alert-hit-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 7px;
      border-radius: 999px;
      font-size: 10.5px;
      font-weight: 700;
      background: var(--success);
      color: #ffffff;
    }

    .card-top-tools {
      display: flex;
      justify-content: flex-end;
      gap: 6px;
    }

    .icon-btn {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 12px;
      cursor: pointer;
    }
    .icon-btn:hover {
      color: var(--danger);
      border-color: var(--danger);
      background: var(--danger-bg);
    }

    /* 2. Keepa Chart Section */
    .keepa-chart-section {
      padding: 18px 26px 20px;
      border-bottom: 1px solid var(--border);
      background: var(--bg-card);
    }

    .chart-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }

    .chart-section-title {
      font-size: 13.5px;
      font-weight: 700;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .range-tabs {
      display: inline-flex;
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      background: var(--bg-subtle);
    }

    .range-tab {
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 600;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      cursor: pointer;
    }
    .range-tab.active {
      background: var(--new-color);
      color: #ffffff;
    }

    .keepa-chart-grid {
      display: grid;
      grid-template-columns: 1fr 235px;
      gap: 18px;
      align-items: center;
    }

    .chart-canvas-wrap {
      position: relative;
      height: 265px;
      width: 100%;
    }

    .keepa-legend-panel {
      background: var(--bg-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .keepa-legend-heading {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-muted);
    }

    .legend-toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      user-select: none;
    }

    .legend-toggle-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .dot-new, .dot-used, .dot-threshold {
      width: 11px;
      height: 11px;
      border-radius: 50%;
      display: inline-block;
    }
    .dot-new { background: var(--new-color); }
    .dot-used { background: var(--used-color); }
    .dot-threshold {
      border: 2px dashed var(--text-muted);
      background: transparent;
    }

    .keepa-stats-mini {
      border-top: 1px solid var(--border);
      padding-top: 10px;
      font-size: 11.5px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .stats-row {
      display: flex;
      justify-content: space-between;
      color: var(--text-secondary);
    }
    .stats-row strong {
      font-family: 'JetBrains Mono', monospace;
      color: var(--text-main);
    }

    /* 3. Keepa Threshold Tracking Form ("Suivi Prix Seuil") */
    .threshold-section {
      padding: 16px 26px;
      background: var(--bg-subtle);
      border-bottom: 1px solid var(--border);
    }

    .threshold-form {
      display: grid;
      grid-template-columns: auto 1fr 1fr auto;
      gap: 16px;
      align-items: center;
    }

    .threshold-label-block {
      min-width: 175px;
    }
    .threshold-label-block h4 {
      margin: 0;
      font-size: 13.5px;
      font-weight: 700;
      color: var(--text-main);
    }
    .threshold-label-block p {
      margin: 2px 0 0;
      font-size: 11.5px;
      color: var(--text-muted);
    }

    .keepa-input-card {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      background: var(--bg-card);
    }
    .keepa-input-card.new-tint {
      background: var(--new-bg);
      border-color: var(--new-border);
    }
    .keepa-input-card.used-tint {
      background: var(--used-bg);
      border-color: var(--used-border);
    }

    .keepa-input-card label {
      font-size: 12px;
      font-weight: 700;
      min-width: 64px;
    }
    .new-tint label { color: var(--new-color); }
    .used-tint label { color: var(--used-color); }

    .euro-field {
      display: flex;
      align-items: center;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: 6px;
      padding: 4px 8px;
      flex: 1;
      min-width: 95px;
    }
    .euro-field span {
      font-weight: 600;
      color: var(--text-muted);
      margin-right: 5px;
      font-size: 13px;
    }
    .euro-field input {
      width: 100%;
      border: none;
      background: transparent;
      color: var(--text-main);
      font-family: 'JetBrains Mono', monospace;
      font-size: 13.5px;
      font-weight: 600;
      outline: none;
    }

    .ou-moins {
      font-size: 11.5px;
      color: var(--text-secondary);
      white-space: nowrap;
    }

    .quick-pct-btn {
      border: 1px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--text-secondary);
      border-radius: 4px;
      padding: 2px 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
    }
    .quick-pct-btn:hover {
      color: var(--text-main);
      border-color: var(--text-main);
    }

    /* 4. Product URLs Section below Chart */
    .urls-section {
      padding: 20px 26px 24px;
    }

    .urls-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }

    .urls-header h3 {
      margin: 0;
      font-size: 14.5px;
      font-weight: 700;
      color: var(--text-main);
    }

    .urls-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .urls-table-wrap {
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
    }

    table.urls-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: left;
    }

    table.urls-table th {
      background: var(--bg-subtle);
      color: var(--text-secondary);
      font-weight: 600;
      font-size: 11.5px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }

    table.urls-table td {
      padding: 11px 12px;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }
    table.urls-table tr:last-child td {
      border-bottom: none;
    }
    table.urls-table tr:hover td {
      background: var(--bg-subtle);
    }

    .cond-badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11.5px;
      font-weight: 700;
    }
    .cond-new {
      background: var(--new-bg);
      color: var(--new-color);
      border: 1px solid var(--new-border);
    }
    .cond-used {
      background: var(--used-bg);
      color: var(--used-color);
      border: 1px solid var(--used-border);
    }

    .merchant-link {
      font-weight: 600;
      color: var(--text-main);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .merchant-link:hover {
      color: var(--new-color);
      text-decoration: underline;
    }

    .url-domain-hint {
      display: block;
      font-size: 11px;
      color: var(--text-muted);
      max-width: 280px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .mono-num {
      font-family: 'JetBrains Mono', monospace;
      white-space: nowrap;
    }

    .total-cell {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 700;
      font-size: 14px;
      color: var(--text-main);
    }
    .total-cell.is-best-new { color: var(--new-color); }
    .total-cell.is-best-used { color: var(--used-color); }

    /* Inline Add/Edit URL Form */
    .url-drawer {
      display: none;
      margin-bottom: 16px;
      padding: 18px;
      border-radius: var(--radius-md);
      background: var(--bg-subtle);
      border: 1px solid var(--border-strong);
    }
    .url-drawer.open {
      display: block;
    }

    .drawer-title-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .drawer-title-row h4 {
      margin: 0;
      font-size: 14px;
      font-weight: 700;
    }

    .url-inspect-row {
      display: flex;
      gap: 8px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }
    .url-inspect-row input {
      flex: 1;
      min-width: 240px;
      padding: 9px 12px;
      border-radius: 6px;
      border: 1px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--text-main);
      font-size: 13.5px;
    }

    .url-form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }

    .field-group {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .field-group label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-secondary);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 4px;
    }
    .field-group input, .field-group select, .field-group textarea {
      padding: 8px 10px;
      border-radius: 6px;
      border: 1px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--text-main);
      font-family: inherit;
      font-size: 13px;
    }

    .fee-status-hint {
      font-size: 11px;
      min-height: 15px;
    }
    .fee-status-hint.auto-ok { color: var(--success); font-weight: 500; }
    .fee-status-hint.manual-needed { color: var(--used-color); font-weight: 500; }

    .url-total-preview-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--border);
      flex-wrap: wrap;
    }

    .url-total-formula {
      font-size: 13px;
      color: var(--text-secondary);
    }
    .url-total-formula strong {
      font-family: 'JetBrains Mono', monospace;
      font-size: 15px;
      color: var(--text-main);
    }

    /* Suggestions Panel ("Proposer des pages produit") */
    .suggest-drawer {
      display: none;
      margin-bottom: 16px;
      padding: 16px 18px;
      border-radius: var(--radius-md);
      background: var(--used-bg);
      border: 1px solid var(--used-border);
    }
    .suggest-drawer.open {
      display: block;
    }

    .suggest-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }

    .suggest-item {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 10px;
    }

    .suggest-item-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-main);
      margin: 4px 0;
    }

    .suggest-item-hint {
      font-size: 11.5px;
      color: var(--text-muted);
    }

    .suggest-item-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    /* Modals */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 200;
      background: rgba(15, 23, 42, 0.55);
      backdrop-filter: blur(2px);
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .modal-backdrop.open {
      display: flex;
    }

    .modal-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      max-width: 600px;
      width: 100%;
      max-height: 90vh;
      overflow-y: auto;
      padding: 24px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
    }

    .modal-card h3 {
      margin: 0 0 16px;
      font-size: 18px;
    }

    /* Toast Notification */
    .toast-stack {
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 300;
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-width: 380px;
    }

    .toast-item {
      background: #0f172a;
      color: #f8fafc;
      padding: 12px 16px;
      border-radius: 10px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.25);
      font-size: 13px;
      border-left: 4px solid #38bdf8;
      animation: slideIn 0.2s ease;
    }
    @keyframes slideIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 920px) {
      .card-product-header {
        grid-template-columns: 110px 1fr;
      }
      .price-summary-col {
        grid-column: 1 / -1;
        flex-direction: row;
        flex-wrap: wrap;
      }
      .price-kpi { flex: 1; min-width: 160px; }
      .keepa-chart-grid {
        grid-template-columns: 1fr;
      }
      .threshold-form {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 580px) {
      .card-product-header {
        grid-template-columns: 1fr;
      }
      .watch-photo-box {
        width: 100%;
        height: 160px;
      }
    }
  </style>
</head>
<body>

  <!-- Top Navigation Bar -->
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand-logo">
        <div class="keepa-bars"><span></span><span></span><span></span></div>
        <span>KeepaWatch</span>
      </div>

      <div class="search-box">
        <span class="search-icon">🔎</span>
        <input type="search" id="searchInput" placeholder="Filtrer par référence (ex: CB1160, SBTM323, Max Bill)..." oninput="renderAllCards()" />
      </div>

      <div class="topbar-actions">
        <button class="btn btn-primary" onclick="openAddProductModal()">+ Ajouter un produit</button>
        <button class="btn btn-topbar" onclick="openNotifyModal()">🔔 Notifications</button>
        <button class="btn btn-topbar" onclick="openYamlModal()">💾 Config YAML</button>
        <button class="btn btn-topbar" id="themeBtn" onclick="toggleTheme()" title="Basculer le thème">🌙</button>
      </div>
    </div>
  </header>

  <!-- Brand & Alert Filters -->
  <div class="filter-strip">
    <div class="brand-pills" id="brandFilterBar"></div>
    <div class="server-status" id="persistenceStatus">
      <span class="status-dot"></span>
      <span>Sauvegarde locale active</span>
    </div>
  </div>

  <!-- Main List: 1 Card per Watch Reference -->
  <main class="cards-container" id="cardsContainer"></main>

  <!-- Modal: Ajouter une référence produit -->
  <div class="modal-backdrop" id="addProductModal">
    <div class="modal-card">
      <div class="drawer-title-row">
        <h3>+ Ajouter une référence produit</h3>
        <button class="icon-btn" onclick="closeModal('addProductModal')">✕</button>
      </div>
      <form onsubmit="submitNewProduct(event)">
        <div class="url-form-grid">
          <div class="field-group">
            <label>Marque *</label>
            <input type="text" id="npBrand" required placeholder="ex: Citizen, Seiko, Omega" />
          </div>
          <div class="field-group">
            <label>Référence exacte *</label>
            <input type="text" id="npRef" required placeholder="ex: CB1160-55W" />
          </div>
        </div>
        <div class="field-group" style="margin-bottom:12px;">
          <label>Nom complet du modèle *</label>
          <input type="text" id="npName" required placeholder="ex: Citizen Collection Super Titanium CB1160-55W" />
        </div>
        <div class="url-form-grid">
          <div class="field-group">
            <label>Code EAN (optionnel)</label>
            <input type="text" id="npEan" placeholder="ex: 4974374356321" />
          </div>
          <div class="field-group">
            <label>URL de la photo produit</label>
            <input type="url" id="npImage" placeholder="https://.../photo.jpg (ou auto)" />
          </div>
        </div>
        <div class="field-group" style="margin-bottom:12px;">
          <label>Courte présentation du produit *</label>
          <textarea id="npFeatures" rows="3" required placeholder="Décrivez brièvement le boîtier, mouvement, verre, diamètre..."></textarea>
        </div>
        <div class="url-form-grid">
          <div class="field-group">
            <label>Seuil notification Neuf (€)</label>
            <input type="number" step="0.01" id="npTargetNew" placeholder="ex: 390" />
          </div>
          <div class="field-group">
            <label>Seuil notification Occasion (€)</label>
            <input type="number" step="0.01" id="npTargetUsed" placeholder="ex: 290" />
          </div>
        </div>
        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
          <button type="button" class="btn btn-outline" onclick="closeModal('addProductModal')">Annuler</button>
          <button type="submit" class="btn btn-primary">Créer la fiche produit</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Modal: Notifications Chrome & ntfy.sh -->
  <div class="modal-backdrop" id="notifyModal">
    <div class="modal-card">
      <div class="drawer-title-row">
        <h3>🔔 Notifications de Seuils (Neuf & Occasion)</h3>
        <button class="icon-btn" onclick="closeModal('notifyModal')">✕</button>
      </div>
      <p style="font-size:13.5px; color:var(--text-secondary); margin-top:0;">
        Une notification est envoyée dès que le meilleur prix <strong>tout frais compris</strong> d'une montre passe sous votre seuil <strong>Neuf</strong> ou votre seuil <strong>Occasion</strong>.
      </p>
      <div class="field-group" style="margin-bottom:14px;">
        <label>Canal Web Push ntfy.sh (Chrome & Mobile)</label>
        <input type="text" id="ntfyTopicInput" placeholder="bf-montres-solaires-2026" />
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:8px; justify-content:space-between; align-items:center;">
        <a id="ntfyWebLink" href="https://ntfy.sh/app" target="_blank" rel="noopener" class="btn btn-outline">Ouvrir ntfy.sh Web ↗</a>
        <div style="display:flex; gap:8px;">
          <button type="button" class="btn btn-outline" onclick="testThresholdNotification()">🔔 Tester une alerte maintenant</button>
          <button type="button" class="btn btn-primary" onclick="saveNotifySettings()">Enregistrer</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Modal: Export / Import / Reset YAML -->
  <div class="modal-backdrop" id="yamlModal">
    <div class="modal-card">
      <div class="drawer-title-row">
        <h3>💾 Sauvegarde & Synchronisation watches.yaml</h3>
        <button class="icon-btn" onclick="closeModal('yamlModal')">✕</button>
      </div>
      <p style="font-size:13.5px; color:var(--text-secondary); margin-top:0;">
        Vos produits, URLs, frais (port, site, douane) et seuils d'alerte sont enregistrés instantanément dans votre navigateur (et directement dans <code>watches.yaml</code> si vous lancez <code>python3 tracker.py serve</code>). Vous pouvez aussi télécharger le fichier <code>watches.yaml</code> mis à jour pour votre dépôt GitHub.
      </p>
      <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:16px;">
        <button class="btn btn-primary" onclick="downloadYamlConfig()">⬇️ Télécharger watches.yaml</button>
        <button class="btn btn-outline" onclick="resetLocalChanges()">↺ Réinitialiser les données par défaut</button>
      </div>
    </div>
  </div>

  <div class="toast-stack" id="toastStack"></div>

  <script id="initialDataScript" type="application/json">__INITIAL_APP_DATA__</script>
  <script>
    const STORAGE_KEY = 'keepawatch_state_v2';
    const THEME_KEY = 'keepawatch_theme';

    const DEFAULT_STATE = JSON.parse(document.getElementById('initialDataScript').textContent);
    let appState = loadAppState();
    let activeBrandFilter = 'ALL';
    let chartInstances = {};
    let cardRanges = {}; // watchId -> days ('7', '30', '90', 'all')
    let cardVisibility = {}; // watchId -> { new: true, used: true, thresholds: true }
    let localApiAvailable = false;

    function loadAppState() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (parsed && Array.isArray(parsed.watches)) {
            return parsed;
          }
        }
      } catch (e) {}
      return JSON.parse(JSON.stringify(DEFAULT_STATE));
    }

    async function persistState(toastMsg) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(appState));
      } catch (e) {}
      if (localApiAvailable) {
        try {
          await fetch('/api/save-state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(appState)
          });
        } catch (e) {}
      }
      if (toastMsg) showToast(toastMsg);
    }

    async function checkLocalApi() {
      if (location.protocol === 'file:') return;
      try {
        const resp = await fetch('/api/ping', { method: 'GET' });
        if (resp.ok) {
          localApiAvailable = true;
          const el = document.getElementById('persistenceStatus');
          if (el) {
            el.innerHTML = '<span class="status-dot"></span><span>Connecté à watches.yaml (serveur local actif)</span>';
          }
        }
      } catch (e) {}
    }

    function escapeHtml(str) {
      return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function fmtEur(val) {
      if (val === null || val === undefined || isNaN(val)) return '—';
      return Number(val).toFixed(2).replace('.', ',') + ' €';
    }

    function getHostnameLabel(url) {
      try {
        return new URL(url).hostname.replace(/^www\./, '');
      } catch (e) {
        return url;
      }
    }

    function buildWatchFallbackSvg(brand, ref) {
      const label = escapeHtml((brand || 'WATCH').toUpperCase().slice(0, 10));
      const sub = escapeHtml((ref || '').slice(0, 12));
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">
        <rect width="160" height="160" fill="#ffffff"/>
        <rect x="62" y="8" width="36" height="26" rx="4" fill="#cbd5e1"/>
        <rect x="62" y="126" width="36" height="26" rx="4" fill="#cbd5e1"/>
        <circle cx="80" cy="80" r="50" fill="#f8fafc" stroke="#94a3b8" stroke-width="5"/>
        <circle cx="80" cy="80" r="43" fill="#1e293b"/>
        <text x="80" y="64" text-anchor="middle" fill="#e2e8f0" font-family="sans-serif" font-size="8.5" font-weight="700">${label}</text>
        <text x="80" y="104" text-anchor="middle" fill="#94a3b8" font-family="monospace" font-size="7.5">${sub}</text>
        <line x1="80" y1="80" x2="62" y2="63" stroke="#f8fafc" stroke-width="3" stroke-linecap="round"/>
        <line x1="80" y1="80" x2="106" y2="66" stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round"/>
        <circle cx="80" cy="80" r="3" fill="#fbbf24"/>
      </svg>`;
      return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
    }

    function computeWatchSummary(watch) {
      let bestNew = null;
      let bestUsed = null;

      (watch.urls || []).forEach((u) => {
        const base = (u.base_price !== null && u.base_price !== undefined && u.base_price !== '') ? Number(u.base_price) : null;
        if (base === null || isNaN(base)) return;
        const ship = Number(u.shipping_fee || 0);
        const site = Number(u.site_fee || 0);
        const cust = Number(u.customs_fee || 0);
        u.total_price = Math.round((base + ship + site + cust) * 100) / 100;
        if (u.in_stock === false) return;
        if (u.condition === 'used') {
          if (!bestUsed || u.total_price < bestUsed.total_price) bestUsed = u;
        } else {
          if (!bestNew || u.total_price < bestNew.total_price) bestNew = u;
        }
      });

      const alertNew = !!(bestNew && watch.target_price_new > 0 && bestNew.total_price <= watch.target_price_new);
      const alertUsed = !!(bestUsed && watch.target_price_used > 0 && bestUsed.total_price <= watch.target_price_used);

      // Compute historical stats
      const hist = watch.history || [];
      const newVals = hist.map(h => h.new_price).filter(v => typeof v === 'number');
      if (bestNew) newVals.push(bestNew.total_price);
      const usedVals = hist.map(h => h.used_price).filter(v => typeof v === 'number');
      if (bestUsed) usedVals.push(bestUsed.total_price);

      const calcStats = (arr) => {
        if (!arr.length) return { min: null, avg: null, max: null };
        const min = Math.min(...arr);
        const max = Math.max(...arr);
        const avg = arr.reduce((a, b) => a + b, 0) / arr.length;
        return { min, avg, max };
      };

      return {
        bestNew,
        bestUsed,
        alertNew,
        alertUsed,
        newStats: calcStats(newVals),
        usedStats: calcStats(usedVals)
      };
    }

    function renderBrandFilterBar() {
      const bar = document.getElementById('brandFilterBar');
      const brands = Array.from(new Set(appState.watches.map(w => w.brand).filter(Boolean)));
      let alertCount = 0;
      appState.watches.forEach(w => {
        const s = computeWatchSummary(w);
        if (s.alertNew || s.alertUsed) alertCount++;
      });

      const items = [
        { key: 'ALL', label: `Toutes les références (${appState.watches.length})` },
        { key: 'ALERTS', label: `🔔 Seuils atteints (${alertCount})` },
        ...brands.map(b => ({
          key: b,
          label: `${b} (${appState.watches.filter(w => w.brand === b).length})`
        }))
      ];

      bar.innerHTML = items.map(it => `
        <button class="filter-pill ${activeBrandFilter === it.key ? 'active' : ''}" onclick="setBrandFilter('${escapeHtml(it.key)}')">
          ${escapeHtml(it.label)}
        </button>
      `).join('');
    }

    function setBrandFilter(key) {
      activeBrandFilter = key;
      renderAllCards();
    }

    function renderAllCards() {
      renderBrandFilterBar();
      const query = (document.getElementById('searchInput').value || '').trim().toLowerCase();
      const container = document.getElementById('cardsContainer');

      // Destroy previous chart instances cleanly
      Object.values(chartInstances).forEach(ch => {
        try { ch.destroy(); } catch (e) {}
      });
      chartInstances = {};

      const filtered = appState.watches.filter(w => {
        const sum = computeWatchSummary(w);
        if (activeBrandFilter === 'ALERTS' && !(sum.alertNew || sum.alertUsed)) return false;
        if (activeBrandFilter !== 'ALL' && activeBrandFilter !== 'ALERTS' && w.brand !== activeBrandFilter) return false;
        if (!query) return true;
        const hay = `${w.brand} ${w.name} ${w.reference} ${w.ean || ''} ${w.asin || ''} ${w.features || ''}`.toLowerCase();
        return hay.includes(query);
      });

      if (!filtered.length) {
        container.innerHTML = `
          <div class="watch-card" style="padding:40px; text-align:center; color:var(--text-secondary);">
            Aucune référence horlogère ne correspond à ce filtre.
          </div>`;
        return;
      }

      container.innerHTML = filtered.map(w => renderSingleCardHtml(w)).join('');

      filtered.forEach(w => {
        initKeepaChart(w);
      });
    }

    function renderSingleCardHtml(w) {
      const sum = computeWatchSummary(w);
      const vis = cardVisibility[w.id] || (cardVisibility[w.id] = { new: true, used: true, thresholds: true });
      const range = cardRanges[w.id] || 'all';
      const fallbackImg = buildWatchFallbackSvg(w.brand, w.reference);
      const imgSrc = w.image_url || fallbackImg;

      const specsHtml = Object.entries(w.specs || {}).map(([k, v]) =>
        `<span class="spec-pill"><strong>${escapeHtml(k)} :</strong> ${escapeHtml(v)}</span>`
      ).join('');

      const rowsHtml = (w.urls || []).map((u, idx) => {
        const isBestNew = sum.bestNew && sum.bestNew.url === u.url && u.condition !== 'used';
        const isBestUsed = sum.bestUsed && sum.bestUsed.url === u.url && u.condition === 'used';
        const totalClass = isBestNew ? 'is-best-new' : (isBestUsed ? 'is-best-used' : '');
        return `
          <tr>
            <td>
              <a class="merchant-link" href="${escapeHtml(u.url)}" target="_blank" rel="noopener noreferrer">
                <span>${escapeHtml(u.merchant || getHostnameLabel(u.url))}</span>
                <span style="font-size:11px; opacity:0.65;">↗</span>
              </a>
              <span class="url-domain-hint" title="${escapeHtml(u.url)}">${escapeHtml(u.url)}</span>
            </td>
            <td>
              <span class="cond-badge ${u.condition === 'used' ? 'cond-used' : 'cond-new'}">
                ${u.condition === 'used' ? 'Occasion' : 'Neuf'}
              </span>
            </td>
            <td class="mono-num">${fmtEur(u.base_price)}</td>
            <td class="mono-num">${Number(u.shipping_fee || 0) > 0 ? '+ ' + fmtEur(u.shipping_fee) : '0,00 €'}</td>
            <td class="mono-num">${Number(u.site_fee || 0) > 0 ? '+ ' + fmtEur(u.site_fee) : '0,00 €'}</td>
            <td class="mono-num">${Number(u.customs_fee || 0) > 0 ? '+ ' + fmtEur(u.customs_fee) : '0,00 €'}</td>
            <td class="total-cell ${totalClass}">${fmtEur(u.total_price)}</td>
            <td style="text-align:right; white-space:nowrap;">
              <button class="btn btn-outline btn-sm" onclick="openEditUrlDrawer('${escapeHtml(w.id)}', ${idx})" title="Modifier le prix ou les frais">✏️ Frais</button>
              <button class="icon-btn" onclick="deleteUrlFromWatch('${escapeHtml(w.id)}', ${idx})" title="Supprimer cette page produit">🗑️</button>
            </td>
          </tr>
        `;
      }).join('');

      const emptyUrlsHtml = `
        <tr>
          <td colspan="8" style="text-align:center; padding:20px; color:var(--text-muted);">
            Aucune page produit suivie pour le moment. Cliquez sur <strong>+ Ajouter une URL produit</strong> ou <strong>✨ Proposer des pages produit</strong>.
          </td>
        </tr>`;

      const existingSet = new Set((w.urls || []).map(u => u.url.replace(/\/$/, '')));
      const availableSuggestions = (w.suggested_urls || []).filter(s => !existingSet.has((s.url || '').replace(/\/$/, '')));

      const suggestionsHtml = availableSuggestions.length ? availableSuggestions.map((s, sIdx) => `
        <div class="suggest-item">
          <div>
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
              <strong style="font-size:12.5px;">${escapeHtml(s.merchant)}</strong>
              <span class="cond-badge ${s.condition === 'used' ? 'cond-used' : 'cond-new'}">${s.condition === 'used' ? 'Occasion' : 'Neuf'}</span>
            </div>
            <div class="suggest-item-title">${escapeHtml(s.title || w.name)}</div>
            <div class="suggest-item-hint">${escapeHtml(s.fee_hint || '')}</div>
          </div>
          <div class="suggest-item-footer">
            <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" style="font-size:12px; color:var(--new-color); text-decoration:none; font-weight:600;">Vérifier la page ↗</a>
            <button type="button" class="btn btn-primary btn-sm" onclick="selectSuggestedUrl('${escapeHtml(w.id)}', ${sIdx})">Choisir & Configurer →</button>
          </div>
        </div>
      `).join('') : `<div style="font-size:13px; color:var(--text-secondary);">Toutes les pages suggérées connues sont déjà dans votre liste ci-dessous.</div>`;

      return `
      <article class="watch-card" id="card-${escapeHtml(w.id)}">
        <!-- 1. Short Product Presentation + Photo -->
        <div class="card-product-header">
          <div class="watch-photo-box">
            <img src="${escapeHtml(imgSrc)}" alt="${escapeHtml(w.name)}" loading="lazy" onerror="this.onerror=null;this.src='${fallbackImg}';" />
          </div>

          <div class="watch-info">
            <div class="watch-brand-row">
              <span class="brand-tag">${escapeHtml(w.brand)}</span>
              ${w.reference_price ? `<span style="font-size:12px; color:var(--text-muted);">• Prix public indicatif : ${fmtEur(w.reference_price)}</span>` : ''}
            </div>
            <h2 class="watch-title">${escapeHtml(w.name)}</h2>
            <div class="id-badges">
              <span class="id-chip" onclick="copyText('${escapeHtml(w.reference)}')" title="Copier la référence">Réf : ${escapeHtml(w.reference)} 📋</span>
              ${w.ean ? `<span class="id-chip" onclick="copyText('${escapeHtml(w.ean)}')" title="Copier le code EAN">EAN : ${escapeHtml(w.ean)} 📋</span>` : ''}
              ${w.asin ? `<span class="id-chip" onclick="copyText('${escapeHtml(w.asin)}')" title="Copier l'ASIN">ASIN : ${escapeHtml(w.asin)} 📋</span>` : ''}
            </div>
            <p class="watch-description">${escapeHtml(w.features)}</p>
            <div class="spec-pills">${specsHtml}</div>
          </div>

          <div class="price-summary-col">
            <div class="card-top-tools">
              <button class="icon-btn" onclick="deleteWatchCard('${escapeHtml(w.id)}')" title="Supprimer cette référence produit">🗑️ Retirer la fiche</button>
            </div>

            <div class="price-kpi kpi-new">
              <div class="price-kpi-top">
                <span>Prix Neuf</span>
                ${sum.alertNew ? '<span class="alert-hit-badge">🔔 Seuil atteint</span>' : ''}
              </div>
              <div class="price-kpi-val">${sum.bestNew ? fmtEur(sum.bestNew.total_price) : '—'}</div>
              <div class="price-kpi-sub">${sum.bestNew ? 'Chez ' + escapeHtml(sum.bestNew.merchant) + ' (frais inclus)' : 'Aucune URL Neuf suivie'}</div>
            </div>

            <div class="price-kpi kpi-used">
              <div class="price-kpi-top">
                <span>Prix Occasion</span>
                ${sum.alertUsed ? '<span class="alert-hit-badge">🔔 Seuil atteint</span>' : ''}
              </div>
              <div class="price-kpi-val">${sum.bestUsed ? fmtEur(sum.bestUsed.total_price) : '—'}</div>
              <div class="price-kpi-sub">${sum.bestUsed ? 'Chez ' + escapeHtml(sum.bestUsed.merchant) + ' (frais inclus)' : 'Aucune URL Occasion suivie'}</div>
            </div>
          </div>
        </div>

        <!-- 2. Keepa-Style Price Evolution Chart (Neuf & Occasion) -->
        <div class="keepa-chart-section">
          <div class="chart-toolbar">
            <div class="chart-section-title">
              <span>📈 Historique d'évolution du prix (frais de port, site & douane compris)</span>
            </div>
            <div class="range-tabs">
              <button class="range-tab ${range === '7' ? 'active' : ''}" onclick="setCardRange('${escapeHtml(w.id)}', '7')">7j</button>
              <button class="range-tab ${range === '30' ? 'active' : ''}" onclick="setCardRange('${escapeHtml(w.id)}', '30')">1 mois</button>
              <button class="range-tab ${range === '90' ? 'active' : ''}" onclick="setCardRange('${escapeHtml(w.id)}', '90')">3 mois</button>
              <button class="range-tab ${range === 'all' ? 'active' : ''}" onclick="setCardRange('${escapeHtml(w.id)}', 'all')">Tout</button>
            </div>
          </div>

          <div class="keepa-chart-grid">
            <div class="chart-canvas-wrap">
              <canvas id="chart-${escapeHtml(w.id)}"></canvas>
            </div>

            <div class="keepa-legend-panel">
              <div class="keepa-legend-heading">Courbes Keepa</div>

              <label class="legend-toggle">
                <span class="legend-toggle-left">
                  <input type="checkbox" ${vis.new ? 'checked' : ''} onchange="toggleCurve('${escapeHtml(w.id)}', 'new', this.checked)" />
                  <span class="dot-new"></span>
                  <span>Neuf</span>
                </span>
                <span class="mono-num" style="color:var(--new-color);">${sum.bestNew ? fmtEur(sum.bestNew.total_price) : '—'}</span>
              </label>

              <label class="legend-toggle">
                <span class="legend-toggle-left">
                  <input type="checkbox" ${vis.used ? 'checked' : ''} onchange="toggleCurve('${escapeHtml(w.id)}', 'used', this.checked)" />
                  <span class="dot-used"></span>
                  <span>Occasion</span>
                </span>
                <span class="mono-num" style="color:var(--used-color);">${sum.bestUsed ? fmtEur(sum.bestUsed.total_price) : '—'}</span>
              </label>

              <label class="legend-toggle">
                <span class="legend-toggle-left">
                  <input type="checkbox" ${vis.thresholds ? 'checked' : ''} onchange="toggleCurve('${escapeHtml(w.id)}', 'thresholds', this.checked)" />
                  <span class="dot-threshold"></span>
                  <span>Seuils d'alerte</span>
                </span>
              </label>

              <div class="keepa-stats-mini">
                <div class="stats-row"><span>Plus bas Neuf :</span><strong>${fmtEur(sum.newStats.min)}</strong></div>
                <div class="stats-row"><span>Moyenne Neuf :</span><strong>${fmtEur(sum.newStats.avg)}</strong></div>
                <div class="stats-row"><span>Plus bas Occasion :</span><strong>${fmtEur(sum.usedStats.min)}</strong></div>
                <div class="stats-row"><span>Moyenne Occasion :</span><strong>${fmtEur(sum.usedStats.avg)}</strong></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 3. Notification Threshold Form (Neuf & Occasion, Keepa Suivi Style) -->
        <div class="threshold-section">
          <form class="threshold-form" onsubmit="saveThresholds(event, '${escapeHtml(w.id)}')">
            <div class="threshold-label-block">
              <h4>🔔 Suivi & Alertes de prix</h4>
              <p>Notification dès que le prix descend sous le seuil</p>
            </div>

            <div class="keepa-input-card new-tint">
              <label for="th-new-${escapeHtml(w.id)}">Neuf</label>
              <div class="euro-field">
                <span>€</span>
                <input type="number" step="0.01" min="0" id="th-new-${escapeHtml(w.id)}" value="${w.target_price_new ?? ''}" placeholder="Aucun" />
              </div>
              <span class="ou-moins">ou moins</span>
              ${sum.bestNew ? `<button type="button" class="quick-pct-btn" onclick="applyQuickPct('${escapeHtml(w.id)}', 'new', ${sum.bestNew.total_price}, 0.95)" title="-5% sous l'actuel">-5%</button>` : ''}
            </div>

            <div class="keepa-input-card used-tint">
              <label for="th-used-${escapeHtml(w.id)}">Occasion</label>
              <div class="euro-field">
                <span>€</span>
                <input type="number" step="0.01" min="0" id="th-used-${escapeHtml(w.id)}" value="${w.target_price_used ?? ''}" placeholder="Aucun" />
              </div>
              <span class="ou-moins">ou moins</span>
              ${sum.bestUsed ? `<button type="button" class="quick-pct-btn" onclick="applyQuickPct('${escapeHtml(w.id)}', 'used', ${sum.bestUsed.total_price}, 0.95)" title="-5% sous l'actuel">-5%</button>` : ''}
            </div>

            <button type="submit" class="btn btn-primary">Enregistrer le suivi</button>
          </form>
        </div>

        <!-- 4. User-Managed Product Pages & Fee Breakdown below the Chart -->
        <div class="urls-section">
          <div class="urls-header">
            <h3>🔗 Pages produit suivies (${(w.urls || []).length})</h3>
            <div class="urls-actions">
              <button type="button" class="btn btn-suggest btn-sm" onclick="toggleSuggestDrawer('${escapeHtml(w.id)}')">
                ✨ Proposer des pages produit (${availableSuggestions.length})
              </button>
              <button type="button" class="btn btn-primary btn-sm" onclick="openAddUrlDrawer('${escapeHtml(w.id)}')">
                + Ajouter une URL produit
              </button>
            </div>
          </div>

          <!-- On-demand Product Page Suggestions Drawer -->
          <div class="suggest-drawer" id="suggest-drawer-${escapeHtml(w.id)}">
            <div class="drawer-title-row">
              <h4>✨ Pages produit proposées pour ${escapeHtml(w.brand)} ${escapeHtml(w.reference)}</h4>
              <button type="button" class="icon-btn" onclick="toggleSuggestDrawer('${escapeHtml(w.id)}')">✕</button>
            </div>
            <div style="font-size:12.5px; color:var(--text-secondary);">
              Aucune page n'est ajoutée automatiquement. Cliquez sur <strong>Choisir & Configurer</strong> pour pré-remplir une page et vérifier ses frais avant ajout :
            </div>
            <div class="suggest-list">${suggestionsHtml}</div>
          </div>

          <!-- Add / Edit URL & Fees Drawer -->
          <div class="url-drawer" id="url-drawer-${escapeHtml(w.id)}">
            <div class="drawer-title-row">
              <h4 id="url-drawer-title-${escapeHtml(w.id)}">+ Ajouter une page produit à suivre</h4>
              <button type="button" class="icon-btn" onclick="closeUrlDrawer('${escapeHtml(w.id)}')">✕</button>
            </div>

            <form onsubmit="submitUrlForm(event, '${escapeHtml(w.id)}')">
              <input type="hidden" id="uf-edit-idx-${escapeHtml(w.id)}" value="-1" />

              <div class="url-inspect-row">
                <input type="url" required id="uf-url-${escapeHtml(w.id)}" placeholder="Collez l'URL de la page produit (Amazon, Ocarat, Chrono24, Catawiki, Sakura...)" onblur="autoInspectUrlOnBlur('${escapeHtml(w.id)}')" />
                <button type="button" class="btn btn-outline" id="uf-inspect-btn-${escapeHtml(w.id)}" onclick="inspectAndPrefillUrl('${escapeHtml(w.id)}')">
                  🔎 Analyser le site & Pré-remplir
                </button>
              </div>

              <div class="url-form-grid">
                <div class="field-group">
                  <label>Marchand</label>
                  <input type="text" id="uf-merchant-${escapeHtml(w.id)}" placeholder="ex: Ocarat, Chrono24..." />
                  <span class="fee-status-hint" id="uf-merch-hint-${escapeHtml(w.id)}"></span>
                </div>

                <div class="field-group">
                  <label>État du produit</label>
                  <select id="uf-cond-${escapeHtml(w.id)}" onchange="recalcUrlPreview('${escapeHtml(w.id)}')">
                    <option value="new">Neuf</option>
                    <option value="used">Occasion</option>
                  </select>
                  <span class="fee-status-hint" id="uf-cond-hint-${escapeHtml(w.id)}"></span>
                </div>

                <div class="field-group">
                  <label>Prix affiché sur le site (€) *</label>
                  <input type="number" step="0.01" min="0" required id="uf-base-${escapeHtml(w.id)}" placeholder="ex: 369.00" oninput="onBasePriceInput('${escapeHtml(w.id)}')" />
                  <span class="fee-status-hint" id="uf-base-hint-${escapeHtml(w.id)}"></span>
                </div>

                <div class="field-group">
                  <label>Frais de port (€)</label>
                  <input type="number" step="0.01" min="0" id="uf-ship-${escapeHtml(w.id)}" placeholder="À saisir (ex: 0 ou 15)" oninput="markManualFee('${escapeHtml(w.id)}', 'ship'); recalcUrlPreview('${escapeHtml(w.id)}')" />
                  <span class="fee-status-hint" id="uf-ship-hint-${escapeHtml(w.id)}"></span>
                </div>

                <div class="field-group">
                  <label>Frais du site / acheteur (€)</label>
                  <input type="number" step="0.01" min="0" id="uf-site-${escapeHtml(w.id)}" placeholder="À saisir (ex: 0 ou Catawiki)" oninput="markManualFee('${escapeHtml(w.id)}', 'site'); recalcUrlPreview('${escapeHtml(w.id)}')" />
                  <span class="fee-status-hint" id="uf-site-hint-${escapeHtml(w.id)}"></span>
                </div>

                <div class="field-group">
                  <label>Frais de douane & TVA (€)</label>
                  <input type="number" step="0.01" min="0" id="uf-cust-${escapeHtml(w.id)}" placeholder="À saisir (0 € en UE)" oninput="markManualFee('${escapeHtml(w.id)}', 'cust'); recalcUrlPreview('${escapeHtml(w.id)}')" />
                  <span class="fee-status-hint" id="uf-cust-hint-${escapeHtml(w.id)}"></span>
                </div>
              </div>

              <div class="url-total-preview-bar">
                <div class="url-total-formula" id="uf-formula-${escapeHtml(w.id)}">
                  Prix total calculé : <strong>—</strong>
                </div>
                <div style="display:flex; gap:8px;">
                  <button type="button" class="btn btn-outline" onclick="closeUrlDrawer('${escapeHtml(w.id)}')">Annuler</button>
                  <button type="submit" class="btn btn-primary">Enregistrer l'URL</button>
                </div>
              </div>
            </form>
          </div>

          <!-- Tracked URLs Table -->
          <div class="urls-table-wrap">
            <table class="urls-table">
              <thead>
                <tr>
                  <th>Page produit</th>
                  <th>État</th>
                  <th>Prix affiché</th>
                  <th>Frais de port</th>
                  <th>Frais du site</th>
                  <th>Frais de douane</th>
                  <th>Total (frais inclus)</th>
                  <th style="text-align:right;">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${rowsHtml || emptyUrlsHtml}
              </tbody>
            </table>
          </div>
        </div>
      </article>`;
    }

    function initKeepaChart(w) {
      const canvas = document.getElementById('chart-' + w.id);
      if (!canvas || typeof Chart === 'undefined') return;

      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      const newColor = isDark ? '#38bdf8' : '#2563eb';
      const newFill = isDark ? 'rgba(56, 189, 248, 0.10)' : 'rgba(37, 99, 235, 0.08)';
      const usedColor = isDark ? '#fbbf24' : '#d97706';
      const usedFill = isDark ? 'rgba(251, 191, 36, 0.10)' : 'rgba(217, 119, 6, 0.08)';
      const gridColor = isDark ? 'rgba(148, 163, 184, 0.14)' : 'rgba(15, 23, 42, 0.07)';
      const tickColor = isDark ? '#94a3b8' : '#64748b';

      const sum = computeWatchSummary(w);
      let entries = Array.isArray(w.history) ? [...w.history] : [];

      // Filter by selected range
      const range = cardRanges[w.id] || 'all';
      if (range !== 'all' && entries.length > 0) {
        const days = Number(range);
        const cutoff = Date.now() - days * 86400 * 1000;
        const filtered = entries.filter(e => new Date(e.timestamp).getTime() >= cutoff);
        if (filtered.length >= 2) entries = filtered;
      }

      // Ensure current live point is reflected at the right end of the Keepa curve
      const nowLabel = 'Actuel';
      const labels = entries.map(e => {
        const d = new Date(e.timestamp);
        return isNaN(d.getTime()) ? '' : d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
      });
      const newSeries = entries.map(e => (typeof e.new_price === 'number' ? e.new_price : null));
      const usedSeries = entries.map(e => (typeof e.used_price === 'number' ? e.used_price : null));

      if (sum.bestNew || sum.bestUsed) {
        labels.push(nowLabel);
        newSeries.push(sum.bestNew ? sum.bestNew.total_price : null);
        usedSeries.push(sum.bestUsed ? sum.bestUsed.total_price : null);
      }

      const vis = cardVisibility[w.id] || { new: true, used: true, thresholds: true };
      const datasets = [];

      if (vis.new) {
        datasets.push({
          label: 'Prix Neuf (frais inclus)',
          data: newSeries,
          borderColor: newColor,
          backgroundColor: newFill,
          borderWidth: 2.5,
          stepped: 'after',
          fill: true,
          spanGaps: true,
          pointRadius: 2.5,
          pointHoverRadius: 5
        });
      }

      if (vis.used) {
        datasets.push({
          label: 'Prix Occasion (frais inclus)',
          data: usedSeries,
          borderColor: usedColor,
          backgroundColor: usedFill,
          borderWidth: 2.5,
          stepped: 'after',
          fill: true,
          spanGaps: true,
          pointRadius: 2.5,
          pointHoverRadius: 5
        });
      }

      if (vis.thresholds && w.target_price_new > 0) {
        datasets.push({
          label: 'Seuil Alerte Neuf',
          data: labels.map(() => Number(w.target_price_new)),
          borderColor: newColor,
          borderWidth: 1.4,
          borderDash: [6, 5],
          pointRadius: 0,
          fill: false
        });
      }

      if (vis.thresholds && w.target_price_used > 0) {
        datasets.push({
          label: 'Seuil Alerte Occasion',
          data: labels.map(() => Number(w.target_price_used)),
          borderColor: usedColor,
          borderWidth: 1.4,
          borderDash: [6, 5],
          pointRadius: 0,
          fill: false
        });
      }

      chartInstances[w.id] = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: isDark ? '#0f172a' : '#1e293b',
              titleColor: '#f8fafc',
              bodyColor: '#f8fafc',
              padding: 10,
              callbacks: {
                label: (ctx) => `${ctx.dataset.label} : ${fmtEur(ctx.parsed.y)}`
              }
            }
          },
          scales: {
            x: {
              grid: { color: gridColor },
              ticks: { color: tickColor, maxTicksLimit: 9, font: { size: 11 } }
            },
            y: {
              grid: { color: gridColor },
              ticks: {
                color: tickColor,
                font: { family: 'JetBrains Mono', size: 11 },
                callback: (v) => v + ' €'
              }
            }
          }
        }
      });
    }

    function setCardRange(watchId, range) {
      cardRanges[watchId] = range;
      renderAllCards();
    }

    function toggleCurve(watchId, key, checked) {
      if (!cardVisibility[watchId]) cardVisibility[watchId] = { new: true, used: true, thresholds: true };
      cardVisibility[watchId][key] = checked;
      const w = appState.watches.find(x => x.id === watchId);
      if (w) {
        if (chartInstances[watchId]) chartInstances[watchId].destroy();
        initKeepaChart(w);
      }
    }

    /* Threshold Form Logic */
    function applyQuickPct(watchId, type, currentPrice, mult) {
      const inputId = type === 'new' ? `th-new-${watchId}` : `th-used-${watchId}`;
      const el = document.getElementById(inputId);
      if (el) {
        el.value = Math.floor(currentPrice * mult);
      }
    }

    async function saveThresholds(ev, watchId) {
      ev.preventDefault();
      const w = appState.watches.find(x => x.id === watchId);
      if (!w) return;
      const rawNew = document.getElementById(`th-new-${watchId}`).value;
      const rawUsed = document.getElementById(`th-used-${watchId}`).value;
      w.target_price_new = rawNew !== '' ? Number(rawNew) : null;
      w.target_price_used = rawUsed !== '' ? Number(rawUsed) : null;

      await persistState(`Seuils enregistrés pour ${w.reference}`);
      renderAllCards();

      const sum = computeWatchSummary(w);
      if (sum.alertNew) {
        dispatchAlertNotification(
          `🔔 Seuil NEUF atteint : ${w.brand} ${w.reference}`,
          `Disponible neuf à ${fmtEur(sum.bestNew.total_price)} chez ${sum.bestNew.merchant} (seuil : ${fmtEur(w.target_price_new)})`,
          sum.bestNew.url
        );
      }
      if (sum.alertUsed) {
        dispatchAlertNotification(
          `🔔 Seuil OCCASION atteint : ${w.brand} ${w.reference}`,
          `Disponible d'occasion à ${fmtEur(sum.bestUsed.total_price)} chez ${sum.bestUsed.merchant} (seuil : ${fmtEur(w.target_price_used)})`,
          sum.bestUsed.url
        );
      }
    }

    /* URL Fee Auto-Detection & Management */
    const urlFeeAutoState = {}; // watchId -> { shipMode: 'auto'|'manual', siteMode: 'auto'|'manual', custMode: 'auto'|'manual', ruleType: '' }

    function setHint(id, text, cls) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = text || '';
      el.className = 'fee-status-hint ' + (cls || '');
    }

    function markManualFee(watchId, kind) {
      if (!urlFeeAutoState[watchId]) urlFeeAutoState[watchId] = {};
      urlFeeAutoState[watchId][kind + 'Mode'] = 'manual';
      setHint(`uf-${kind}-hint-${watchId}`, '✍️ Saisi par vous', '');
    }

    function openAddUrlDrawer(watchId) {
      const drawer = document.getElementById(`url-drawer-${watchId}`);
      document.getElementById(`url-drawer-title-${watchId}`).textContent = '+ Ajouter une page produit à suivre';
      document.getElementById(`uf-edit-idx-${watchId}`).value = '-1';
      document.getElementById(`uf-url-${watchId}`).value = '';
      document.getElementById(`uf-merchant-${watchId}`).value = '';
      document.getElementById(`uf-cond-${watchId}`).value = 'new';
      document.getElementById(`uf-base-${watchId}`).value = '';
      document.getElementById(`uf-ship-${watchId}`).value = '';
      document.getElementById(`uf-site-${watchId}`).value = '';
      document.getElementById(`uf-cust-${watchId}`).value = '';
      ['merch', 'cond', 'base', 'ship', 'site', 'cust'].forEach(k => setHint(`uf-${k}-hint-${watchId}`, '', ''));
      urlFeeAutoState[watchId] = { shipMode: 'auto', siteMode: 'auto', custMode: 'auto', ruleType: '' };
      recalcUrlPreview(watchId);
      drawer.classList.add('open');
      document.getElementById(`uf-url-${watchId}`).focus();
    }

    function openEditUrlDrawer(watchId, idx) {
      const w = appState.watches.find(x => x.id === watchId);
      if (!w || !w.urls[idx]) return;
      const u = w.urls[idx];
      const drawer = document.getElementById(`url-drawer-${watchId}`);
      document.getElementById(`url-drawer-title-${watchId}`).textContent = `✏️ Modifier les frais — ${u.merchant}`;
      document.getElementById(`uf-edit-idx-${watchId}`).value = String(idx);
      document.getElementById(`uf-url-${watchId}`).value = u.url;
      document.getElementById(`uf-merchant-${watchId}`).value = u.merchant || '';
      document.getElementById(`uf-cond-${watchId}`).value = u.condition || 'new';
      document.getElementById(`uf-base-${watchId}`).value = u.base_price ?? '';
      document.getElementById(`uf-ship-${watchId}`).value = u.shipping_fee ?? 0;
      document.getElementById(`uf-site-${watchId}`).value = u.site_fee ?? 0;
      document.getElementById(`uf-cust-${watchId}`).value = u.customs_fee ?? 0;
      ['merch', 'cond', 'base', 'ship', 'site', 'cust'].forEach(k => setHint(`uf-${k}-hint-${watchId}`, '', ''));
      urlFeeAutoState[watchId] = { shipMode: 'manual', siteMode: 'manual', custMode: 'manual', ruleType: '' };
      recalcUrlPreview(watchId);
      drawer.classList.add('open');
    }

    function closeUrlDrawer(watchId) {
      const el = document.getElementById(`url-drawer-${watchId}`);
      if (el) el.classList.remove('open');
    }

    function toggleSuggestDrawer(watchId) {
      const el = document.getElementById(`suggest-drawer-${watchId}`);
      if (el) el.classList.toggle('open');
    }

    function selectSuggestedUrl(watchId, sIdx) {
      const w = appState.watches.find(x => x.id === watchId);
      if (!w) return;
      const existingSet = new Set((w.urls || []).map(u => u.url.replace(/\/$/, '')));
      const available = (w.suggested_urls || []).filter(s => !existingSet.has((s.url || '').replace(/\/$/, '')));
      const s = available[sIdx];
      if (!s) return;

      toggleSuggestDrawer(watchId);
      openAddUrlDrawer(watchId);

      document.getElementById(`uf-url-${watchId}`).value = s.url;
      document.getElementById(`uf-merchant-${watchId}`).value = s.merchant || '';
      document.getElementById(`uf-cond-${watchId}`).value = s.condition || 'new';
      if (s.estimated_base_price !== null && s.estimated_base_price !== undefined) {
        document.getElementById(`uf-base-${watchId}`).value = s.estimated_base_price;
        setHint(`uf-base-hint-${watchId}`, 'Prix indicatif pré-rempli (ajustable)', 'auto-ok');
      }
      if (s.shipping_fee !== null && s.shipping_fee !== undefined) {
        document.getElementById(`uf-ship-${watchId}`).value = s.shipping_fee;
        setHint(`uf-ship-hint-${watchId}`, '✓ Port pré-rempli', 'auto-ok');
      }
      if (s.site_fee !== null && s.site_fee !== undefined) {
        document.getElementById(`uf-site-${watchId}`).value = s.site_fee;
        setHint(`uf-site-hint-${watchId}`, '✓ Frais site pré-remplis', 'auto-ok');
      }
      if (s.customs_fee !== null && s.customs_fee !== undefined) {
        document.getElementById(`uf-cust-${watchId}`).value = s.customs_fee;
        setHint(`uf-cust-hint-${watchId}`, '✓ Douane pré-remplie', 'auto-ok');
      }
      recalcUrlPreview(watchId);
    }

    function clientSideSiteRules(url, basePrice) {
      const u = (url || '').toLowerCase();
      let host = '';
      try { host = new URL(url).hostname.replace(/^www\./, '').toLowerCase(); } catch (e) {}

      const merchantMap = {
        'amazon.fr': 'Amazon.fr',
        'amazon.de': 'Amazon.de',
        'ocarat.com': 'Ocarat',
        'montresandco.com': 'Montres & Co',
        'lepage.fr': 'Lepage',
        'chrono24.fr': 'Chrono24',
        'chrono24.com': 'Chrono24',
        'catawiki.com': 'Catawiki',
        'vinted.fr': 'Vinted',
        'leboncoin.fr': 'Leboncoin',
        'ebay.fr': 'eBay.fr',
        'sakurawatches.com': 'Sakura Watches (Tokyo)',
        'shoppinginjapan.net': 'Shopping In Japan',
        'seiyajapan.com': 'SeiyaJapan',
        'creationwatches.com': 'CreationWatches',
        'gnomonwatches.com': 'Gnomon Watches',
        'citizenwatch.eu': 'Citizen Store EU',
        'casio.com': 'Casio Officiel',
        'uhr24.de': 'Uhr24.de',
        'helveti.eu': 'Helveti.eu',
        'irisimo.com': 'Irisimo',
        'zeitlounge.com': 'Zeitlounge',
        'luna-time.fr': 'Luna-Time',
        'mastersintime.com': 'Masters In Time',
        'rm-time.com': 'RM-Time'
      };

      let merchant = '';
      for (const [d, label] of Object.entries(merchantMap)) {
        if (host === d || host.endsWith('.' + d)) { merchant = label; break; }
      }
      if (!merchant && host) merchant = host.split('.')[0].charAt(0).toUpperCase() + host.split('.')[0].slice(1);

      const isUsedUrl = u.includes('used') || u.includes('occasion') || host.includes('catawiki') || host.includes('vinted') || host.includes('leboncoin');
      const condition = isUsedUrl ? 'used' : 'new';

      const nonEuDomains = ['sakurawatches.com', 'shoppinginjapan.net', 'seiyajapan.com', 'discovery-japan.me', 'creationwatches.com', 'gnomonwatches.com', 'timeshop4you.co.uk'];
      const euDomains = ['amazon.fr', 'amazon.de', 'ocarat.com', 'montresandco.com', 'lepage.fr', 'citizenwatch.eu', 'casio.com', 'uhr24.de', 'helveti.eu', 'irisimo.com', 'zeitlounge.com', 'luna-time.fr', 'mastersintime.com', 'rm-time.com'];

      const isNonEu = nonEuDomains.some(d => host === d || host.endsWith('.' + d));
      const isEu = euDomains.some(d => host === d || host.endsWith('.' + d));

      let ship = null, shipReason = '';
      let site = null, siteReason = '';
      let cust = null, custReason = '';
      let ruleType = 'standard';

      if (host.includes('catawiki')) {
        ruleType = 'catawiki';
        if (basePrice > 0) {
          site = Math.round((basePrice * 0.09 + 3.0) * 100) / 100;
          siteReason = '✓ Barème Catawiki (9 % + 3 €)';
        } else {
          siteReason = 'Sera calculé (9 % + 3 €) dès le prix saisi';
        }
      } else if (host.includes('vinted')) {
        ruleType = 'vinted';
        if (basePrice > 0) {
          site = Math.round((basePrice * 0.05 + 0.70) * 100) / 100;
          siteReason = '✓ Protection Vinted (5 % + 0,70 €)';
        }
      } else if (isEu || isNonEu || host.includes('chrono24')) {
        site = 0;
        siteReason = '✓ Aucun frais acheteur sur ce site (0 €)';
      }

      if (isNonEu) {
        ruleType = 'japan_import';
        ship = 24.0;
        shipReason = '✓ Forfait DHL Express hors-UE (~24 €)';
        if (basePrice > 0) {
          const taxes = (basePrice + ship + 0.80) * 0.20 + 0.80;
          cust = Math.round((taxes + 18.0) * 100) / 100;
          custReason = '✓ TVA 20 % + douane 0,80 € + dossier 18 €';
        } else {
          custReason = 'TVA 20 % + douane calculée dès le prix saisi';
        }
      } else if (isEu) {
        ship = 0.0;
        shipReason = '✓ Livraison standard UE offerte (vérifier si < seuil)';
        cust = 0.0;
        custReason = '✓ Boutique UE TTC (0 € de douane)';
      }

      return { merchant, condition, ship, shipReason, site, siteReason, cust, custReason, ruleType };
    }

    function autoInspectUrlOnBlur(watchId) {
      const editIdx = Number(document.getElementById(`uf-edit-idx-${watchId}`).value);
      if (editIdx >= 0) return;
      const urlVal = document.getElementById(`uf-url-${watchId}`).value.trim();
      if (urlVal && !document.getElementById(`uf-merchant-${watchId}`).value) {
        inspectAndPrefillUrl(watchId);
      }
    }

    async function inspectAndPrefillUrl(watchId) {
      const urlInput = document.getElementById(`uf-url-${watchId}`);
      const url = urlInput.value.trim();
      if (!url) return;

      const btn = document.getElementById(`uf-inspect-btn-${watchId}`);
      const oldLabel = btn.textContent;
      btn.textContent = '⏳ Analyse de la page...';
      btn.disabled = true;

      let inspected = null;

      // 1. Try local Python server /api/inspect-url if running
      if (localApiAvailable) {
        try {
          const resp = await fetch('/api/inspect-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
          });
          if (resp.ok) inspected = await resp.json();
        } catch (e) {}
      }

      // 2. Apply server inspection result OR client-side site rules
      const currentBase = parseFloat(document.getElementById(`uf-base-${watchId}`).value) || 0;
      const rules = clientSideSiteRules(url, (inspected && inspected.base_price) || currentBase);
      urlFeeAutoState[watchId] = { shipMode: 'auto', siteMode: 'auto', custMode: 'auto', ruleType: rules.ruleType };

      document.getElementById(`uf-merchant-${watchId}`).value = (inspected && inspected.merchant) || rules.merchant;
      document.getElementById(`uf-cond-${watchId}`).value = (inspected && inspected.condition) || rules.condition;

      if (inspected && inspected.base_price !== null && inspected.base_price !== undefined) {
        document.getElementById(`uf-base-${watchId}`).value = inspected.base_price;
        setHint(`uf-base-hint-${watchId}`, '✓ Prix lu en clair sur la page', 'auto-ok');
      } else if (!document.getElementById(`uf-base-${watchId}`).value) {
        setHint(`uf-base-hint-${watchId}`, '✍️ Saisissez le prix affiché sur la page', 'manual-needed');
      }

      const shipVal = (inspected && inspected.shipping_detected) ? inspected.shipping_fee : rules.ship;
      const shipWhy = (inspected && inspected.shipping_detected) ? ('✓ ' + inspected.shipping_reason) : rules.shipReason;
      if (shipVal !== null && shipVal !== undefined) {
        document.getElementById(`uf-ship-${watchId}`).value = shipVal;
        setHint(`uf-ship-hint-${watchId}`, shipWhy, 'auto-ok');
      } else {
        document.getElementById(`uf-ship-${watchId}`).value = '';
        setHint(`uf-ship-hint-${watchId}`, '✍️ Non indiqué en clair — à saisir', 'manual-needed');
      }

      const siteVal = (inspected && inspected.site_fee_detected) ? inspected.site_fee : rules.site;
      const siteWhy = (inspected && inspected.site_fee_detected) ? ('✓ ' + inspected.site_fee_reason) : rules.siteReason;
      if (siteVal !== null && siteVal !== undefined) {
        document.getElementById(`uf-site-${watchId}`).value = siteVal;
        setHint(`uf-site-hint-${watchId}`, siteWhy, 'auto-ok');
      } else {
        document.getElementById(`uf-site-${watchId}`).value = '';
        setHint(`uf-site-hint-${watchId}`, siteWhy || '✍️ Non indiqué en clair — à saisir', 'manual-needed');
      }

      const custVal = (inspected && inspected.customs_detected) ? inspected.customs_fee : rules.cust;
      const custWhy = (inspected && inspected.customs_detected) ? ('✓ ' + inspected.customs_reason) : rules.custReason;
      if (custVal !== null && custVal !== undefined) {
        document.getElementById(`uf-cust-${watchId}`).value = custVal;
        setHint(`uf-cust-hint-${watchId}`, custWhy, 'auto-ok');
      } else {
        document.getElementById(`uf-cust-${watchId}`).value = '';
        setHint(`uf-cust-hint-${watchId}`, custWhy || '✍️ Vérifiez pays du vendeur (0 € si UE)', 'manual-needed');
      }

      btn.textContent = oldLabel;
      btn.disabled = false;
      recalcUrlPreview(watchId);
    }

    function onBasePriceInput(watchId) {
      const st = urlFeeAutoState[watchId] || {};
      const base = parseFloat(document.getElementById(`uf-base-${watchId}`).value) || 0;
      const ship = parseFloat(document.getElementById(`uf-ship-${watchId}`).value) || 0;

      if (base > 0) {
        if (st.siteMode === 'auto' && st.ruleType === 'catawiki') {
          const fee = Math.round((base * 0.09 + 3.0) * 100) / 100;
          document.getElementById(`uf-site-${watchId}`).value = fee;
          setHint(`uf-site-hint-${watchId}`, '✓ Catawiki 9 % + 3 € calculé', 'auto-ok');
        } else if (st.siteMode === 'auto' && st.ruleType === 'vinted') {
          const fee = Math.round((base * 0.05 + 0.70) * 100) / 100;
          document.getElementById(`uf-site-${watchId}`).value = fee;
          setHint(`uf-site-hint-${watchId}`, '✓ Vinted 5 % + 0,70 € calculé', 'auto-ok');
        }
        if (st.custMode === 'auto' && st.ruleType === 'japan_import') {
          const taxes = (base + (ship || 24.0) + 0.80) * 0.20 + 0.80 + 18.0;
          document.getElementById(`uf-cust-${watchId}`).value = Math.round(taxes * 100) / 100;
          setHint(`uf-cust-hint-${watchId}`, '✓ TVA 20 % + douane + dossier calculés', 'auto-ok');
        }
      }
      recalcUrlPreview(watchId);
    }

    function recalcUrlPreview(watchId) {
      const base = parseFloat(document.getElementById(`uf-base-${watchId}`).value);
      const ship = parseFloat(document.getElementById(`uf-ship-${watchId}`).value) || 0;
      const site = parseFloat(document.getElementById(`uf-site-${watchId}`).value) || 0;
      const cust = parseFloat(document.getElementById(`uf-cust-${watchId}`).value) || 0;
      const formulaEl = document.getElementById(`uf-formula-${watchId}`);
      if (!formulaEl) return;
      if (isNaN(base)) {
        formulaEl.innerHTML = 'Prix total calculé : <strong>—</strong>';
        return;
      }
      const total = Math.round((base + ship + site + cust) * 100) / 100;
      formulaEl.innerHTML = `${fmtEur(base)} (prix) + ${fmtEur(ship)} (port) + ${fmtEur(site)} (site) + ${fmtEur(cust)} (douane) = <strong>${fmtEur(total)} TTC</strong>`;
    }

    async function submitUrlForm(ev, watchId) {
      ev.preventDefault();
      const w = appState.watches.find(x => x.id === watchId);
      if (!w) return;

      const editIdx = Number(document.getElementById(`uf-edit-idx-${watchId}`).value);
      const url = document.getElementById(`uf-url-${watchId}`).value.trim();
      const merchant = document.getElementById(`uf-merchant-${watchId}`).value.trim() || getHostnameLabel(url);
      const condition = document.getElementById(`uf-cond-${watchId}`).value;
      const base_price = parseFloat(document.getElementById(`uf-base-${watchId}`).value);
      const shipping_fee = parseFloat(document.getElementById(`uf-ship-${watchId}`).value) || 0;
      const site_fee = parseFloat(document.getElementById(`uf-site-${watchId}`).value) || 0;
      const customs_fee = parseFloat(document.getElementById(`uf-cust-${watchId}`).value) || 0;
      const total_price = Math.round((base_price + shipping_fee + site_fee + customs_fee) * 100) / 100;

      const record = {
        url,
        merchant,
        condition,
        base_price,
        shipping_fee,
        site_fee,
        customs_fee,
        total_price,
        in_stock: true
      };

      if (!Array.isArray(w.urls)) w.urls = [];
      if (editIdx >= 0 && w.urls[editIdx]) {
        w.urls[editIdx] = record;
      } else {
        w.urls.push(record);
      }

      closeUrlDrawer(watchId);
      await persistState(`Page ${merchant} (${condition === 'used' ? 'Occasion' : 'Neuf'} : ${fmtEur(total_price)}) enregistrée`);
      renderAllCards();

      const sum = computeWatchSummary(w);
      if (condition !== 'used' && sum.alertNew && total_price <= w.target_price_new) {
        dispatchAlertNotification(
          `🔔 Seuil NEUF atteint : ${w.brand} ${w.reference}`,
          `${fmtEur(total_price)} tout compris chez ${merchant} !`,
          url
        );
      } else if (condition === 'used' && sum.alertUsed && total_price <= w.target_price_used) {
        dispatchAlertNotification(
          `🔔 Seuil OCCASION atteint : ${w.brand} ${w.reference}`,
          `${fmtEur(total_price)} tout compris chez ${merchant} !`,
          url
        );
      }
    }

    async function deleteUrlFromWatch(watchId, idx) {
      const w = appState.watches.find(x => x.id === watchId);
      if (!w || !w.urls[idx]) return;
      const removed = w.urls.splice(idx, 1)[0];
      await persistState(`Lien ${removed.merchant} supprimé`);
      renderAllCards();
    }

    /* Add / Delete Watch Reference Card */
    function openAddProductModal() {
      document.getElementById('addProductModal').classList.add('open');
    }

    function openNotifyModal() {
      document.getElementById('ntfyTopicInput').value = (appState.settings && appState.settings.ntfy_topic) || 'bf-montres-solaires-2026';
      document.getElementById('notifyModal').classList.add('open');
    }

    function openYamlModal() {
      document.getElementById('yamlModal').classList.add('open');
    }

    function closeModal(id) {
      const el = document.getElementById(id);
      if (el) el.classList.remove('open');
    }

    async function submitNewProduct(ev) {
      ev.preventDefault();
      const brand = document.getElementById('npBrand').value.trim();
      const reference = document.getElementById('npRef').value.trim();
      const name = document.getElementById('npName').value.trim();
      const ean = document.getElementById('npEan').value.trim();
      const image_url = document.getElementById('npImage').value.trim();
      const features = document.getElementById('npFeatures').value.trim();
      const tNew = document.getElementById('npTargetNew').value;
      const tUsed = document.getElementById('npTargetUsed').value;

      const id = (brand + '-' + reference).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || ('watch-' + Date.now());
      const q = encodeURIComponent(`${brand} ${reference}`);

      const newWatch = {
        id,
        name,
        brand,
        reference,
        ean,
        asin: '',
        image_url,
        features,
        specs: { Référence: reference },
        target_price_new: tNew !== '' ? Number(tNew) : null,
        target_price_used: tUsed !== '' ? Number(tUsed) : null,
        reference_price: 0,
        urls: [],
        suggested_urls: [
          {
            url: `https://www.amazon.fr/s?k=${q}`,
            merchant: 'Amazon.fr',
            title: `Rechercher ${brand} ${reference} sur Amazon.fr`,
            condition: 'new',
            shipping_fee: 0,
            site_fee: 0,
            customs_fee: 0,
            fee_hint: 'Livraison UE • 0 € douane'
          },
          {
            url: `https://ocarat.com/recherche?controller=search&s=${q}`,
            merchant: 'Ocarat',
            title: `${brand} ${reference} chez Ocarat France`,
            condition: 'new',
            shipping_fee: 0,
            site_fee: 0,
            customs_fee: 0,
            fee_hint: 'Boutique agréée France • 0 € douane'
          },
          {
            url: `https://www.chrono24.fr/search/index.htm?query=${encodeURIComponent(reference)}&usedOrNew=used`,
            merchant: 'Chrono24 (Occasion)',
            title: `Annonces Occasion ${brand} ${reference}`,
            condition: 'used',
            shipping_fee: 15,
            site_fee: 0,
            customs_fee: 0,
            fee_hint: 'Protection acheteur Chrono24 incluse'
          },
          {
            url: `https://www.catawiki.com/fr/s?q=${q}`,
            merchant: 'Catawiki',
            title: `Enchères ${brand} ${reference}`,
            condition: 'used',
            shipping_fee: 18,
            site_fee: null,
            customs_fee: 0,
            fee_hint: 'Frais Catawiki 9 % + 3 € pré-calculés'
          }
        ],
        history: []
      };

      appState.watches.unshift(newWatch);
      closeModal('addProductModal');
      ev.target.reset();
      await persistState(`Référence ${brand} ${reference} ajoutée ! Ajoutez maintenant vos URLs.`);
      renderAllCards();
    }

    async function deleteWatchCard(watchId) {
      const w = appState.watches.find(x => x.id === watchId);
      if (!w) return;
      if (!confirm(`Retirer la fiche produit « ${w.name} » de votre suivi ?`)) return;
      appState.watches = appState.watches.filter(x => x.id !== watchId);
      await persistState(`Fiche ${w.reference} supprimée`);
      renderAllCards();
    }

    /* Notifications */
    async function saveNotifySettings() {
      const topic = document.getElementById('ntfyTopicInput').value.trim();
      if (!appState.settings) appState.settings = {};
      appState.settings.ntfy_topic = topic;
      await persistState('Canal de notification enregistré');
      closeModal('notifyModal');
    }

    async function dispatchAlertNotification(title, body, clickUrl) {
      showToast(`${title} — ${body}`);

      // Browser Notification API / Service Worker
      try {
        if ('Notification' in window) {
          if (Notification.permission === 'default') {
            await Notification.requestPermission();
          }
          if (Notification.permission === 'granted') {
            if ('serviceWorker' in navigator) {
              const reg = await navigator.serviceWorker.getRegistration();
              if (reg) {
                reg.showNotification(title, { body, data: { url: clickUrl || location.href } });
              } else {
                new Notification(title, { body });
              }
            } else {
              new Notification(title, { body });
            }
          }
        }
      } catch (e) {}

      // Web Push via ntfy.sh
      const topic = appState.settings && appState.settings.ntfy_topic;
      const server = (appState.settings && appState.settings.ntfy_server) || 'https://ntfy.sh';
      if (topic) {
        try {
          await fetch(`${server.replace(/\/$/, '')}/${encodeURIComponent(topic)}`, {
            method: 'POST',
            headers: { 'Title': title.replace(/[^\x20-\x7E]/g, ''), 'Priority': 'high', 'Tags': 'watch,bell' },
            body
          });
        } catch (e) {}
      }
    }

    function testThresholdNotification() {
      const first = appState.watches[0];
      const ref = first ? `${first.brand} ${first.reference}` : 'Citizen CB1160-55E';
      dispatchAlertNotification(
        `🔔 Test Alerte Prix — ${ref}`,
        'Les notifications Neuf & Occasion (Chrome + ntfy.sh) sont actives !',
        location.href
      );
    }

    /* Export YAML */
    function downloadYamlConfig() {
      const lines = [
        '# Configuration KeepaWatch — Générée depuis l\'interface',
        'settings:',
        `  currency: ${(appState.settings && appState.settings.currency) || 'EUR'}`,
        `  ntfy_topic: ${(appState.settings && appState.settings.ntfy_topic) || 'bf-montres-solaires-2026'}`,
        `  ntfy_server: ${(appState.settings && appState.settings.ntfy_server) || 'https://ntfy.sh'}`,
        '  request_timeout: 15',
        '  use_playwright_fallback: true',
        '',
        'watches:'
      ];

      appState.watches.forEach(w => {
        lines.push(`  - id: ${JSON.stringify(w.id)}`);
        lines.push(`    name: ${JSON.stringify(w.name)}`);
        lines.push(`    brand: ${JSON.stringify(w.brand)}`);
        lines.push(`    reference: ${JSON.stringify(w.reference)}`);
        if (w.ean) lines.push(`    ean: ${JSON.stringify(w.ean)}`);
        if (w.asin) lines.push(`    asin: ${JSON.stringify(w.asin)}`);
        if (w.image_url) lines.push(`    image_url: ${JSON.stringify(w.image_url)}`);
        lines.push(`    features: ${JSON.stringify(w.features || '')}`);
        if (w.target_price_new !== null && w.target_price_new !== undefined) {
          lines.push(`    target_price_new: ${Number(w.target_price_new)}`);
        }
        if (w.target_price_used !== null && w.target_price_used !== undefined) {
          lines.push(`    target_price_used: ${Number(w.target_price_used)}`);
        }
        if (w.reference_price) lines.push(`    reference_price: ${Number(w.reference_price)}`);
        lines.push('    urls:');
        (w.urls || []).forEach(u => {
          lines.push(`      - url: ${JSON.stringify(u.url)}`);
          lines.push(`        merchant: ${JSON.stringify(u.merchant || '')}`);
          lines.push(`        condition: ${JSON.stringify(u.condition || 'new')}`);
          if (u.base_price !== null && u.base_price !== undefined) lines.push(`        manual_price: ${Number(u.base_price)}`);
          lines.push(`        shipping_fee: ${Number(u.shipping_fee || 0)}`);
          lines.push(`        site_fee: ${Number(u.site_fee || 0)}`);
          lines.push(`        customs_fee: ${Number(u.customs_fee || 0)}`);
        });
      });

      const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/yaml;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'watches.yaml';
      a.click();
      closeModal('yamlModal');
      showToast('Fichier watches.yaml téléchargé');
    }

    function resetLocalChanges() {
      if (!confirm('Réinitialiser toutes vos modifications locales avec la configuration par défaut ?')) return;
      localStorage.removeItem(STORAGE_KEY);
      appState = JSON.parse(JSON.stringify(DEFAULT_STATE));
      closeModal('yamlModal');
      renderAllCards();
      showToast('Configuration par défaut restaurée');
    }

    function copyText(txt) {
      navigator.clipboard?.writeText(txt);
      showToast(`Copié : ${txt}`);
    }

    function showToast(msg) {
      const stack = document.getElementById('toastStack');
      const div = document.createElement('div');
      div.className = 'toast-item';
      div.textContent = msg;
      stack.appendChild(div);
      setTimeout(() => { div.remove(); }, 4200);
    }

    /* Theme */
    function initTheme() {
      const saved = localStorage.getItem(THEME_KEY) || 'light';
      document.documentElement.setAttribute('data-theme', saved);
      document.getElementById('themeBtn').textContent = saved === 'dark' ? '☀️' : '🌙';
    }

    function toggleTheme() {
      const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', cur);
      localStorage.setItem(THEME_KEY, cur);
      document.getElementById('themeBtn').textContent = cur === 'dark' ? '☀️' : '🌙';
      renderAllCards();
    }

    if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
      navigator.serviceWorker.register('./sw.js').catch(() => {});
    }

    initTheme();
    renderAllCards();
    checkLocalApi();
  </script>
</body>
</html>
"""
