#!/usr/bin/env python3
"""
KeepaWatch — Suivi Prix Montres (Neuf & Occasion, Frais Inclus).

Commandes :
  python3 tracker.py run [--demo] [--no-notify]
  python3 tracker.py serve [--port 8000]
  python3 tracker.py add-watch --brand ... --name ... --reference ...
  python3 tracker.py remove-watch --id ...
  python3 tracker.py add-url --watch-id ... --url ... [--condition new|used] [--shipping-fee ...] [--site-fee ...] [--customs-fee ...]
  python3 tracker.py remove-url --url ...
  python3 tracker.py set-thresholds --watch-id ... [--new 420] [--used 320]
  python3 tracker.py suggest --watch-id ...
  python3 tracker.py test-notify
"""

import argparse
import json
import mimetypes
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Any, List, Tuple, Optional

import yaml

from src.models import WatchConfig, WatchURL, SuggestedURL, OfferResult, WatchAnalysis
from src.scraper import scrape_offer, inspect_product_url, infer_merchant_name
from src.suggest import propose_product_pages
from src.analyzer import load_history, save_history, analyze_watch_and_update_history
from src.notifier import (
    build_daily_recap_message,
    send_ntfy_chrome_push,
    send_local_desktop_notification,
)
from src.report import generate_html_report


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "watches.yaml")
DEFAULT_HISTORY_PATH = os.path.join(BASE_DIR, "data", "history.json")
DEFAULT_DOCS_DIR = os.path.join(BASE_DIR, "docs")


def _opt_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


def _opt_positive_price(val: Any) -> Optional[float]:
    parsed = _opt_float(val)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def load_config(config_path: str) -> Tuple[Dict[str, Any], List[WatchConfig]]:
    """Load settings and user-configured watches from watches.yaml."""
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    settings = raw.get("settings", {})
    watches: List[WatchConfig] = []

    for item in raw.get("watches", []):
        urls: List[WatchURL] = []
        for u in item.get("urls", []):
            if isinstance(u, str):
                urls.append(WatchURL(url=u, merchant=infer_merchant_name(u)))
            elif isinstance(u, dict) and u.get("url"):
                urls.append(
                    WatchURL(
                        url=str(u["url"]).strip(),
                        merchant=str(u.get("merchant", "")).strip(),
                        condition=str(u.get("condition", "new")).strip().lower() or "new",
                        shipping_fee=_opt_float(u.get("shipping_fee")),
                        site_fee=_opt_float(u.get("site_fee")),
                        customs_fee=_opt_float(u.get("customs_fee")),
                        manual_price=_opt_positive_price(u.get("manual_price")),
                        note=str(u.get("note", "")),
                    )
                )

        suggested: List[SuggestedURL] = []
        for s in item.get("suggested_urls", []):
            if isinstance(s, dict) and s.get("url"):
                suggested.append(
                    SuggestedURL(
                        url=str(s["url"]).strip(),
                        merchant=str(s.get("merchant", "")).strip() or infer_merchant_name(s["url"]),
                        title=str(s.get("title", "")).strip(),
                        condition=str(s.get("condition", "new")).strip().lower() or "new",
                        estimated_base_price=_opt_float(s.get("estimated_base_price")),
                        shipping_fee=_opt_float(s.get("shipping_fee")),
                        site_fee=_opt_float(s.get("site_fee")),
                        customs_fee=_opt_float(s.get("customs_fee")),
                        fee_hint=str(s.get("fee_hint", "")).strip(),
                    )
                )

        # Backward compatibility if old target_price exists
        t_new = _opt_float(item.get("target_price_new"))
        if t_new is None and item.get("target_price") is not None:
            t_new = _opt_float(item.get("target_price"))
        t_used = _opt_float(item.get("target_price_used"))

        watches.append(
            WatchConfig(
                id=str(item["id"]),
                name=str(item["name"]),
                brand=str(item.get("brand", "")),
                reference=str(item.get("reference", "")),
                features=str(item.get("features", "")),
                target_price_new=t_new,
                target_price_used=t_used,
                reference_price=float(item.get("reference_price", 0.0) or 0.0),
                ean=str(item.get("ean", "")),
                asin=str(item.get("asin", "")),
                image_url=str(item.get("image_url", "")),
                specs=dict(item.get("specs", {}) or {}),
                urls=urls,
                suggested_urls=suggested,
            )
        )

    return settings, watches


def save_config_from_watches(
    config_path: str,
    settings: Dict[str, Any],
    watches: List[WatchConfig],
) -> None:
    """Persist settings and WatchConfig list cleanly to watches.yaml."""
    raw_watches = []
    for w in watches:
        w_dict: Dict[str, Any] = {
            "id": w.id,
            "name": w.name,
            "brand": w.brand,
            "reference": w.reference,
        }
        if w.ean:
            w_dict["ean"] = w.ean
        if w.asin:
            w_dict["asin"] = w.asin
        if w.image_url:
            w_dict["image_url"] = w.image_url
        w_dict["features"] = w.features
        if w.specs:
            w_dict["specs"] = w.specs
        if w.target_price_new is not None:
            w_dict["target_price_new"] = w.target_price_new
        if w.target_price_used is not None:
            w_dict["target_price_used"] = w.target_price_used
        if w.reference_price:
            w_dict["reference_price"] = w.reference_price

        w_dict["urls"] = [
            {
                k: v
                for k, v in {
                    "url": u.url,
                    "merchant": u.merchant,
                    "condition": u.condition,
                    "manual_price": u.manual_price,
                    "shipping_fee": u.shipping_fee if u.shipping_fee is not None else 0.0,
                    "site_fee": u.site_fee if u.site_fee is not None else 0.0,
                    "customs_fee": u.customs_fee if u.customs_fee is not None else 0.0,
                }.items()
                if v is not None
            }
            for u in w.urls
        ]
        if w.suggested_urls:
            w_dict["suggested_urls"] = [
                {k: v for k, v in s.to_dict().items() if v is not None and v != ""}
                for s in w.suggested_urls
            ]
        raw_watches.append(w_dict)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"settings": settings, "watches": raw_watches},
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )


def build_demo_offers_and_seed_keepa_history(
    watches: List[WatchConfig],
    history: Dict[str, Any],
) -> Dict[str, List[OfferResult]]:
    """
    Build OfferResult objects strictly from the user's configured URLs (no automatic discovery)
    and seed realistic 45-day Keepa step-curve history for Neuf & Occasion if empty.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    offers_by_watch: Dict[str, List[OfferResult]] = {}

    # Stepped multipliers over 45 days to render authentic Keepa step-lines
    step_days = [45, 38, 31, 24, 18, 12, 7, 3, 1]
    new_mults = [1.09, 1.09, 1.06, 1.06, 1.04, 1.05, 1.02, 1.02, 1.01]
    used_mults = [1.12, 1.08, 1.08, 1.05, 1.05, 1.03, 1.03, 1.01, 1.00]

    for w in watches:
        w_offers: List[OfferResult] = []
        for u in w.urls:
            base_p = u.manual_price
            ship_f = u.shipping_fee if u.shipping_fee is not None else 0.0
            site_f = u.site_fee if u.site_fee is not None else 0.0
            cust_f = u.customs_fee if u.customs_fee is not None else 0.0
            total_p = round(base_p + ship_f + site_f + cust_f, 2) if base_p is not None else None
            w_offers.append(
                OfferResult(
                    watch_id=w.id,
                    merchant=u.merchant or infer_merchant_name(u.url),
                    url=u.url,
                    price=total_p,
                    base_price=round(base_p, 2) if base_p is not None else None,
                    condition=u.condition or "new",
                    shipping_fee=round(ship_f, 2),
                    site_fee=round(site_f, 2),
                    customs_fee=round(cust_f, 2),
                    shipping_detected=True,
                    site_fee_detected=True,
                    customs_detected=True,
                    in_stock=(base_p is not None),
                    title=w.name,
                    extraction_method="configured",
                    timestamp=now_iso,
                )
            )

        offers_by_watch[w.id] = w_offers

        # Seed Keepa history if empty
        w_hist = history.setdefault("watches", {}).setdefault(
            w.id,
            {
                "name": w.name,
                "reference": w.reference,
                "target_price_new": w.target_price_new,
                "target_price_used": w.target_price_used,
                "reference_price": w.reference_price,
                "entries": [],
            },
        )
        if not w_hist["entries"] and w_offers:
            new_candidates = [o for o in w_offers if o.condition != "used" and o.price is not None]
            used_candidates = [o for o in w_offers if o.condition == "used" and o.price is not None]
            best_new = min(new_candidates, key=lambda x: x.price) if new_candidates else None  # type: ignore
            best_used = min(used_candidates, key=lambda x: x.price) if used_candidates else None  # type: ignore

            for idx, d_ago in enumerate(step_days):
                ts = (now - timedelta(days=d_ago)).isoformat()
                w_hist["entries"].append(
                    {
                        "timestamp": ts,
                        "new_price": round(best_new.price * new_mults[idx], 2) if best_new and best_new.price else None,
                        "new_merchant": best_new.merchant if best_new else "",
                        "used_price": round(best_used.price * used_mults[idx], 2) if best_used and best_used.price else None,
                        "used_merchant": best_used.merchant if best_used else "",
                    }
                )

    return offers_by_watch


def run_comparator(
    config_path: str = DEFAULT_CONFIG_PATH,
    history_path: str = DEFAULT_HISTORY_PATH,
    docs_dir: str = DEFAULT_DOCS_DIR,
    demo_mode: bool = False,
    no_notify: bool = False,
) -> List[WatchAnalysis]:
    """Run the Keepa-style watch price tracker strictly on user-configured URLs."""
    settings, watches = load_config(config_path)
    history = load_history(history_path)

    timeout = int(settings.get("request_timeout", 15))
    use_pw = bool(settings.get("use_playwright_fallback", True))
    import_settings = settings.get("japan_import", {})

    offers_by_watch: Dict[str, List[OfferResult]] = {}

    if demo_mode:
        offers_by_watch = build_demo_offers_and_seed_keepa_history(watches, history)
    else:
        for w in watches:
            print(f"🔎 Relevé des pages suivies pour {w.brand} {w.reference} ({len(w.urls)} URLs)...")
            w_offers: List[OfferResult] = []
            for u in w.urls:
                res = scrape_offer(
                    watch_id=w.id,
                    url=u.url,
                    merchant=u.merchant,
                    condition=u.condition,
                    shipping_fee=u.shipping_fee,
                    site_fee=u.site_fee,
                    customs_fee=u.customs_fee,
                    manual_price=u.manual_price,
                    timeout=timeout,
                    use_playwright_fallback=use_pw,
                    import_settings=import_settings,
                )
                w_offers.append(res)
            offers_by_watch[w.id] = w_offers

    analyses: List[WatchAnalysis] = []
    for w in watches:
        analysis = analyze_watch_and_update_history(
            watch=w,
            offers=offers_by_watch.get(w.id, []),
            history=history,
        )
        analyses.append(analysis)

    save_history(history_path, history)

    index_path = os.path.join(docs_dir, "index.html")
    generate_html_report(analyses, history, settings, index_path)

    dashboard_url = os.environ.get("GITHUB_PAGES_URL", "")
    recap = build_daily_recap_message(analyses, dashboard_url=dashboard_url)

    print("\n" + "=" * 72)
    print(recap["title"])
    print("-" * 72)
    print(recap["body"])
    print("=" * 72)
    print(f"📊 Interface KeepaWatch générée : {index_path}")

    if not no_notify and recap.get("has_alert"):
        ntfy_topic = os.environ.get("NTFY_TOPIC") or settings.get("ntfy_topic", "")
        ntfy_server = settings.get("ntfy_server", "https://ntfy.sh")
        send_local_desktop_notification(recap)
        if ntfy_topic:
            ok = send_ntfy_chrome_push(ntfy_server, ntfy_topic, recap)
            if ok:
                print(f"🔔 Alerte Web Push envoyée sur {ntfy_server}/{ntfy_topic}")

    return analyses


# ==============================================================================
# CLI Helpers (Add/Remove Watch, Add/Remove URL, Set Thresholds, Suggest, Serve)
# ==============================================================================


def add_watch_to_config(
    config_path: str,
    brand: str,
    name: str,
    reference: str,
    target_price_new: Optional[float] = None,
    target_price_used: Optional[float] = None,
    reference_price: float = 0.0,
    features: str = "",
    image_url: str = "",
    ean: str = "",
    urls: Optional[List[str]] = None,
) -> str:
    settings, watches = load_config(config_path)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{brand}-{reference}".lower()).strip("-") or "watch"
    if any(w.id == slug for w in watches):
        raise ValueError(f"La référence '{slug}' existe déjà dans {config_path}.")

    watch_urls = [WatchURL(url=u, merchant=infer_merchant_name(u)) for u in (urls or []) if u.strip()]
    watches.append(
        WatchConfig(
            id=slug,
            name=name.strip(),
            brand=brand.strip(),
            reference=reference.strip(),
            features=features.strip() or f"Montre {brand} réf. {reference}",
            target_price_new=target_price_new,
            target_price_used=target_price_used,
            reference_price=reference_price,
            ean=ean.strip(),
            image_url=image_url.strip(),
            urls=watch_urls,
        )
    )
    save_config_from_watches(config_path, settings, watches)
    print(f"✅ Produit ajouté : {name} (id: {slug})")
    return slug


def remove_watch_from_config(config_path: str, identifier: str) -> bool:
    settings, watches = load_config(config_path)
    needle = identifier.strip().lower()
    kept = []
    removed = None
    for w in watches:
        if w.id.lower() == needle or w.reference.lower() == needle:
            removed = w
        else:
            kept.append(w)
    if not removed:
        print(f"⚠️ Aucun produit trouvé pour '{identifier}'")
        return False
    save_config_from_watches(config_path, settings, kept)
    print(f"🗑️ Produit supprimé : {removed.name}")
    return True


def add_url_to_config(
    config_path: str,
    watch_id: str,
    url: str,
    merchant: str = "",
    condition: str = "new",
    shipping_fee: Optional[float] = None,
    site_fee: Optional[float] = None,
    customs_fee: Optional[float] = None,
    manual_price: Optional[float] = None,
    auto_inspect: bool = True,
) -> None:
    settings, watches = load_config(config_path)
    target = next((w for w in watches if w.id == watch_id or w.reference.lower() == watch_id.lower()), None)
    if not target:
        raise ValueError(f"Référence '{watch_id}' introuvable dans {config_path}.")

    if auto_inspect and any(v is None for v in (shipping_fee, site_fee, customs_fee, manual_price)):
        info = inspect_product_url(url, import_settings=settings.get("japan_import"))
        merchant = merchant or info["merchant"]
        if manual_price is None and info["base_price"] is not None:
            manual_price = info["base_price"]
        if shipping_fee is None and info["shipping_detected"]:
            shipping_fee = info["shipping_fee"]
        if site_fee is None and info["site_fee_detected"]:
            site_fee = info["site_fee"]
        if customs_fee is None and info["customs_detected"]:
            customs_fee = info["customs_fee"]
        if not condition and info["condition"]:
            condition = info["condition"]

    target.urls.append(
        WatchURL(
            url=url.strip(),
            merchant=merchant or infer_merchant_name(url),
            condition=condition or "new",
            shipping_fee=shipping_fee if shipping_fee is not None else 0.0,
            site_fee=site_fee if site_fee is not None else 0.0,
            customs_fee=customs_fee if customs_fee is not None else 0.0,
            manual_price=manual_price,
        )
    )
    save_config_from_watches(config_path, settings, watches)
    print(f"✅ URL ajoutée à {target.reference} : {url}")


def remove_url_from_config(config_path: str, url: str, watch_id: str = "") -> bool:
    settings, watches = load_config(config_path)
    target_url = url.strip().rstrip("/")
    removed = False
    for w in watches:
        if watch_id and w.id != watch_id:
            continue
        before = len(w.urls)
        w.urls = [u for u in w.urls if u.url.strip().rstrip("/") != target_url]
        if len(w.urls) < before:
            removed = True
            print(f"🗑️ Lien supprimé de {w.name} : {url}")
    if removed:
        save_config_from_watches(config_path, settings, watches)
    return removed


def set_watch_thresholds(
    config_path: str,
    watch_id: str,
    threshold_new: Optional[float],
    threshold_used: Optional[float],
) -> None:
    settings, watches = load_config(config_path)
    target = next((w for w in watches if w.id == watch_id or w.reference.lower() == watch_id.lower()), None)
    if not target:
        raise ValueError(f"Référence '{watch_id}' introuvable.")
    if threshold_new is not None:
        target.target_price_new = threshold_new
    if threshold_used is not None:
        target.target_price_used = threshold_used
    save_config_from_watches(config_path, settings, watches)
    print(
        f"🔔 Seuils mis à jour pour {target.reference} : "
        f"Neuf={target.target_price_new} € | Occasion={target.target_price_used} €"
    )


def serve_interactive_app(
    config_path: str = DEFAULT_CONFIG_PATH,
    history_path: str = DEFAULT_HISTORY_PATH,
    docs_dir: str = DEFAULT_DOCS_DIR,
    port: int = 8000,
) -> None:
    """Start a local HTTP server serving docs/ and REST endpoints (/api/ping, /api/inspect-url, /api/save-state)."""

    class KeepaWatchHandler(BaseHTTPRequestHandler):
        def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path.startswith("/api/ping"):
                self._send_json(200, {"ok": True})
                return

            rel = self.path.split("?")[0].lstrip("/") or "index.html"
            file_path = os.path.abspath(os.path.join(docs_dir, rel))
            if not file_path.startswith(os.path.abspath(docs_dir)) or not os.path.isfile(file_path):
                self.send_error(404, "Not found")
                return

            ctype, _ = mimetypes.guess_type(file_path)
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype or "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                body = json.loads(raw_body)
            except Exception:
                body = {}

            if self.path.startswith("/api/inspect-url"):
                url = str(body.get("url", "")).strip()
                settings, _ = load_config(config_path)
                res = inspect_product_url(url, import_settings=settings.get("japan_import"))
                self._send_json(200, res)
                return

            if self.path.startswith("/api/save-state"):
                settings, _ = load_config(config_path)
                if isinstance(body.get("settings"), dict):
                    settings.update(body["settings"])
                new_watches: List[WatchConfig] = []
                for w in body.get("watches", []):
                    urls = [
                        WatchURL(
                            url=str(u.get("url", "")),
                            merchant=str(u.get("merchant", "")),
                            condition=str(u.get("condition", "new")),
                            shipping_fee=_opt_float(u.get("shipping_fee")),
                            site_fee=_opt_float(u.get("site_fee")),
                            customs_fee=_opt_float(u.get("customs_fee")),
                            manual_price=_opt_positive_price(u.get("base_price")),
                        )
                        for u in w.get("urls", [])
                        if u.get("url")
                    ]
                    sugg = [
                        SuggestedURL(
                            url=str(s.get("url", "")),
                            merchant=str(s.get("merchant", "")),
                            title=str(s.get("title", "")),
                            condition=str(s.get("condition", "new")),
                            estimated_base_price=_opt_float(s.get("estimated_base_price")),
                            shipping_fee=_opt_float(s.get("shipping_fee")),
                            site_fee=_opt_float(s.get("site_fee")),
                            customs_fee=_opt_float(s.get("customs_fee")),
                            fee_hint=str(s.get("fee_hint", "")),
                        )
                        for s in w.get("suggested_urls", [])
                        if s.get("url")
                    ]
                    new_watches.append(
                        WatchConfig(
                            id=str(w.get("id")),
                            name=str(w.get("name")),
                            brand=str(w.get("brand", "")),
                            reference=str(w.get("reference", "")),
                            features=str(w.get("features", "")),
                            target_price_new=_opt_float(w.get("target_price_new")),
                            target_price_used=_opt_float(w.get("target_price_used")),
                            reference_price=float(w.get("reference_price", 0) or 0),
                            ean=str(w.get("ean", "")),
                            asin=str(w.get("asin", "")),
                            image_url=str(w.get("image_url", "")),
                            specs=dict(w.get("specs", {}) or {}),
                            urls=urls,
                            suggested_urls=sugg,
                        )
                    )
                save_config_from_watches(config_path, settings, new_watches)
                self._send_json(200, {"saved": True})
                return

            self.send_error(404, "Unknown endpoint")

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), KeepaWatchHandler)
    print(f"🚀 Serveur KeepaWatch actif sur http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeepaWatch — Suivi Prix Montres Neuf & Occasion")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Relever les prix des URLs suivies et générer le rapport HTML")
    p_run.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_run.add_argument("--history", default=DEFAULT_HISTORY_PATH)
    p_run.add_argument("--docs-dir", default=DEFAULT_DOCS_DIR)
    p_run.add_argument("--demo", action="store_true", help="Utiliser les prix configurés & initialiser l'historique Keepa")
    p_run.add_argument("--no-notify", action="store_true")

    p_serve = sub.add_parser("serve", help="Lancer le serveur interactif local relié à watches.yaml")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_serve.add_argument("--docs-dir", default=DEFAULT_DOCS_DIR)

    p_add_w = sub.add_parser("add-watch", help="Ajouter une référence produit")
    p_add_w.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_add_w.add_argument("--brand", required=True)
    p_add_w.add_argument("--name", required=True)
    p_add_w.add_argument("--reference", required=True)
    p_add_w.add_argument("--target-new", type=float, default=None)
    p_add_w.add_argument("--target-used", type=float, default=None)
    p_add_w.add_argument("--reference-price", type=float, default=0.0)
    p_add_w.add_argument("--features", default="")
    p_add_w.add_argument("--image-url", default="")
    p_add_w.add_argument("--ean", default="")
    p_add_w.add_argument("--url", action="append", default=[])

    p_rm_w = sub.add_parser("remove-watch", help="Supprimer une référence produit")
    p_rm_w.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_rm_w.add_argument("--id", required=True)

    p_add_u = sub.add_parser("add-url", help="Ajouter une URL produit avec frais")
    p_add_u.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_add_u.add_argument("--watch-id", required=True)
    p_add_u.add_argument("--url", required=True)
    p_add_u.add_argument("--merchant", default="")
    p_add_u.add_argument("--condition", choices=["new", "used"], default="new")
    p_add_u.add_argument("--price", type=float, default=None)
    p_add_u.add_argument("--shipping-fee", type=float, default=None)
    p_add_u.add_argument("--site-fee", type=float, default=None)
    p_add_u.add_argument("--customs-fee", type=float, default=None)
    p_add_u.add_argument("--no-inspect", action="store_true")

    p_rm_u = sub.add_parser("remove-url", help="Supprimer une URL produit")
    p_rm_u.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_rm_u.add_argument("--url", required=True)
    p_rm_u.add_argument("--watch-id", default="")

    p_th = sub.add_parser("set-thresholds", help="Définir les seuils d'alerte Neuf & Occasion")
    p_th.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_th.add_argument("--watch-id", required=True)
    p_th.add_argument("--new", type=float, default=None)
    p_th.add_argument("--used", type=float, default=None)

    p_sug = sub.add_parser("suggest", help="Proposer des pages produit à ajouter pour une référence")
    p_sug.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p_sug.add_argument("--watch-id", required=True)

    p_test = sub.add_parser("test-notify", help="Tester l'envoi de notification")
    p_test.add_argument("--config", default=DEFAULT_CONFIG_PATH)

    return parser


def main() -> int:
    parser = build_cli()
    args = parser.parse_args()
    cmd = args.command or "run"

    if cmd == "run":
        run_comparator(
            config_path=getattr(args, "config", DEFAULT_CONFIG_PATH),
            history_path=getattr(args, "history", DEFAULT_HISTORY_PATH),
            docs_dir=getattr(args, "docs_dir", DEFAULT_DOCS_DIR),
            demo_mode=getattr(args, "demo", False),
            no_notify=getattr(args, "no_notify", False),
        )
        return 0

    if cmd == "serve":
        serve_interactive_app(
            config_path=args.config,
            docs_dir=args.docs_dir,
            port=args.port,
        )
        return 0

    if cmd == "add-watch":
        add_watch_to_config(
            config_path=args.config,
            brand=args.brand,
            name=args.name,
            reference=args.reference,
            target_price_new=args.target_new,
            target_price_used=args.target_used,
            reference_price=args.reference_price,
            features=args.features,
            image_url=args.image_url,
            ean=args.ean,
            urls=args.url,
        )
        return 0

    if cmd == "remove-watch":
        ok = remove_watch_from_config(args.config, args.id)
        return 0 if ok else 1

    if cmd == "add-url":
        add_url_to_config(
            config_path=args.config,
            watch_id=args.watch_id,
            url=args.url,
            merchant=args.merchant,
            condition=args.condition,
            shipping_fee=args.shipping_fee,
            site_fee=args.site_fee,
            customs_fee=args.customs_fee,
            manual_price=args.price,
            auto_inspect=not args.no_inspect,
        )
        return 0

    if cmd == "remove-url":
        ok = remove_url_from_config(args.config, args.url, args.watch_id)
        return 0 if ok else 1

    if cmd == "set-thresholds":
        set_watch_thresholds(args.config, args.watch_id, args.new, args.used)
        return 0

    if cmd == "suggest":
        _, watches = load_config(args.config)
        target = next((w for w in watches if w.id == args.watch_id or w.reference.lower() == args.watch_id.lower()), None)
        if not target:
            print(f"Référence '{args.watch_id}' introuvable.")
            return 1
        props = propose_product_pages(target, live_fetch=True)
        for p in props:
            print(f"• [{p['condition'].upper()}] {p['merchant']} — {p['url']} ({p.get('fee_hint', '')})")
        return 0

    if cmd == "test-notify":
        settings, _ = load_config(args.config)
        sample = {
            "title": "🔔 Test Alerte KeepaWatch (Neuf & Occasion)",
            "body": "Les alertes de seuil Neuf et Occasion sont opérationnelles !",
            "priority": "high",
            "tags": "watch,bell",
            "click_url": "https://ntfy.sh/app",
        }
        send_local_desktop_notification(sample)
        topic = os.environ.get("NTFY_TOPIC") or settings.get("ntfy_topic", "")
        if topic:
            send_ntfy_chrome_push(settings.get("ntfy_server", "https://ntfy.sh"), topic, sample)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
