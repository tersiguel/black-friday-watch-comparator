#!/usr/bin/env python3
"""
Black Friday Solar Radio-Controlled Watch Price Comparator CLI & Orchestrator.

Commands:
  python3 tracker.py run [--demo] [--no-notify]
  python3 tracker.py add-url --watch <watch_id> --url <url> [--merchant <name>]
  python3 tracker.py remove-url --url <url> [--watch <watch_id>]
  python3 tracker.py test-notify
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple

import yaml

from src.models import WatchConfig, WatchURL, OfferResult, WatchAnalysis
from src.scraper import scrape_offer, infer_merchant_name
from src.discovery import discover_offers_for_watch
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


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Tuple[Dict[str, Any], List[WatchConfig]]:
    """Load settings and competing watch models from watches.yaml."""
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    settings = raw.get("settings", {})
    watches: List[WatchConfig] = []
    for item in raw.get("watches", []):
        urls = [
            WatchURL(
                url=u["url"] if isinstance(u, dict) else str(u),
                merchant=(u.get("merchant", "") if isinstance(u, dict) else ""),
            )
            for u in item.get("urls", [])
        ]
        watches.append(
            WatchConfig(
                id=str(item["id"]),
                name=str(item["name"]),
                brand=str(item.get("brand", "")),
                reference=str(item.get("reference", "")),
                features=str(item.get("features", "")),
                target_price=float(item.get("target_price", 0.0)),
                reference_price=float(item.get("reference_price", 0.0)),
                search_queries=list(item.get("search_queries", [])),
                urls=urls,
            )
        )
    return settings, watches


def generate_demo_offers_and_seed_history(
    watches: List[WatchConfig],
    history: Dict[str, Any],
) -> Tuple[Dict[str, List[OfferResult]], Dict[str, List[OfferResult]]]:
    """
    Generate realistic Black Friday solar radio-controlled watch data and 7-day history
    so the HTML dashboard, anti-fake-promo detector, and Chrome notifications can be
    tested offline or when run with --demo.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    demo_profiles: Dict[str, Dict[str, Any]] = {
        "casio-gwm5610u": {
            "past_prices": [129.0, 125.0, 119.0, 115.0, 109.0, 104.90],
            "offers": [
                OfferResult(
                    watch_id="casio-gwm5610u",
                    merchant="Amazon FR",
                    url="https://www.amazon.fr/dp/B09CGR4FFM",
                    price=94.90,
                    original_price=149.00,
                    in_stock=True,
                    title="Casio G-Shock GW-M5610U-1ER Montre Solaire Radio-Pilotée",
                    extraction_method="json-ld",
                    timestamp=now_iso,
                ),
                OfferResult(
                    watch_id="casio-gwm5610u",
                    merchant="Ocarat",
                    url="https://ocarat.com/montre-g-shock-origin-gw-m5610u-1er-casio-79831.html",
                    price=119.00,
                    original_price=149.00,
                    in_stock=True,
                    title="Montre Casio G-Shock GW-M5610U-1ER",
                    extraction_method="json-ld",
                    promo_code="BFWATCH10",
                    timestamp=now_iso,
                ),
                OfferResult(
                    watch_id="casio-gwm5610u",
                    merchant="Montres & Co",
                    url="https://www.montresandco.com/montre-casio-g-shock-gw-m5610u-1er-p-74248.html",
                    price=124.00,
                    original_price=149.00,
                    in_stock=True,
                    title="Casio G-Shock GW-M5610U-1ER",
                    extraction_method="opengraph-meta",
                    timestamp=now_iso,
                ),
            ],
            "discovered": [
                OfferResult(
                    watch_id="casio-gwm5610u",
                    merchant="Dealabs • Amazon DE",
                    url="https://www.dealabs.com/search?q=GW-M5610U-1ER",
                    price=89.99,
                    original_price=149.00,
                    title="Casio G-Shock GW-M5610U-1ER Tough Solar Multi-Band 6",
                    extraction_method="dealabs-search",
                    timestamp=now_iso,
                    is_discovered=True,
                    temperature="412°",
                )
            ],
        },
        "casio-lineage-titanium": {
            "past_prices": [249.0, 239.0, 229.0, 219.0, 209.0, 199.0],
            "offers": [
                OfferResult(
                    watch_id="casio-lineage-titanium",
                    merchant="Amazon FR",
                    url="https://www.amazon.fr/dp/B07571V4V5",
                    price=184.50,
                    original_price=279.00,
                    in_stock=True,
                    title="Casio Lineage LCW-M100TSE-1AER Titane & Verre Saphir",
                    extraction_method="json-ld",
                    timestamp=now_iso,
                ),
                OfferResult(
                    watch_id="casio-lineage-titanium",
                    merchant="Ocarat",
                    url="https://ocarat.com/montre-lineage-lcw-m100tse-1aer-casio-48155.html",
                    price=215.00,
                    original_price=279.00,
                    in_stock=True,
                    title="Casio Lineage LCW-M100TSE-1AER",
                    extraction_method="json-ld",
                    timestamp=now_iso,
                ),
            ],
            "discovered": [
                OfferResult(
                    watch_id="casio-lineage-titanium",
                    merchant="Idealo Comparateur",
                    url="https://www.idealo.fr/prechcat.html?q=LCW-M100TSE-1AER",
                    price=179.90,
                    title="Casio Lineage LCW-M100TSE-1AER Titane Saphir",
                    extraction_method="idealo-discovery",
                    timestamp=now_iso,
                    is_discovered=True,
                )
            ],
        },
        "citizen-ecodrive-cb0250": {
            "past_prices": [339.0, 329.0, 315.0, 299.0, 289.0, 279.0],
            "offers": [
                OfferResult(
                    watch_id="citizen-ecodrive-cb0250",
                    merchant="Ocarat",
                    url="https://ocarat.com/montre-radio-controlled-cb0250-84e-citizen-86531.html",
                    price=264.00,
                    original_price=399.00,
                    in_stock=True,
                    title="Citizen Eco-Drive Radio-Controlled CB0250-84E",
                    extraction_method="json-ld",
                    promo_code="BLACKCITIZEN",
                    timestamp=now_iso,
                ),
                OfferResult(
                    watch_id="citizen-ecodrive-cb0250",
                    merchant="Amazon FR",
                    url="https://www.amazon.fr/dp/B09WVH883J",
                    price=279.00,
                    original_price=399.00,
                    in_stock=True,
                    title="Citizen CB0250-84E Eco-Drive",
                    extraction_method="json-ld",
                    timestamp=now_iso,
                ),
            ],
            "discovered": [],
        },
        "citizen-promaster-as4020": {
            "past_prices": [329.0, 335.0, 349.0, 359.0, 355.0, 349.0],
            "offers": [
                OfferResult(
                    watch_id="citizen-promaster-as4020",
                    merchant="Amazon FR",
                    url="https://www.amazon.fr/dp/B00WG04A1M",
                    price=349.00,
                    original_price=529.00,
                    in_stock=True,
                    title="Citizen Promaster Sky AT8110-61E Eco-Drive Radio-Controlled",
                    extraction_method="css-selector",
                    timestamp=now_iso,
                ),
                OfferResult(
                    watch_id="citizen-promaster-as4020",
                    merchant="Ocarat",
                    url="https://ocarat.com/montre-chrono-radio-controlled-at8110-61e-citizen-42191.html",
                    price=369.00,
                    original_price=459.00,
                    in_stock=True,
                    title="Citizen AT8110-61E",
                    extraction_method="json-ld",
                    timestamp=now_iso,
                ),
            ],
            "discovered": [],
        },
        "seiko-solar-radio-sbtm323": {
            "past_prices": [325.0, 319.0, 310.0, 299.0, 295.0, 289.0],
            "offers": [
                OfferResult(
                    watch_id="seiko-solar-radio-sbtm323",
                    merchant="Sakura Watches",
                    url="https://www.sakurawatches.com/seiko-selection-sbtm323",
                    price=272.00,
                    original_price=395.00,
                    in_stock=True,
                    title="Seiko Selection SBTM323 Solar Radio-Controlled",
                    extraction_method="json-ld",
                    timestamp=now_iso,
                ),
                OfferResult(
                    watch_id="seiko-solar-radio-sbtm323",
                    merchant="Chrono24",
                    url="https://www.chrono24.fr/search/index.htm?query=SBTM323",
                    price=298.00,
                    original_price=395.00,
                    in_stock=True,
                    title="Seiko SBTM323 Solar",
                    extraction_method="opengraph-meta",
                    timestamp=now_iso,
                ),
            ],
            "discovered": [],
        },
    }

    direct_by_watch: Dict[str, List[OfferResult]] = {}
    disc_by_watch: Dict[str, List[OfferResult]] = {}

    for w in watches:
        prof = demo_profiles.get(w.id)
        configured_urls = {u.url for u in w.urls}
        if not prof:
            direct_by_watch[w.id] = [
                OfferResult(
                    watch_id=w.id,
                    merchant=u.merchant or infer_merchant_name(u.url),
                    url=u.url,
                    price=round(w.target_price * 0.98, 2),
                    original_price=w.reference_price,
                    in_stock=True,
                    title=w.name,
                    extraction_method="demo",
                    timestamp=now_iso,
                )
                for u in w.urls
            ]
            disc_by_watch[w.id] = []
            continue

        # Only include demo offers whose URL is still in watches.yaml (respects removed URLs!)
        filtered_offers = [o for o in prof["offers"] if o.url in configured_urls]
        direct_by_watch[w.id] = filtered_offers
        disc_by_watch[w.id] = prof["discovered"]

        w_hist = history.setdefault("watches", {}).setdefault(
            w.id,
            {
                "name": w.name,
                "reference": w.reference,
                "target_price": w.target_price,
                "reference_price": w.reference_price,
                "entries": [],
            },
        )
        if not w_hist["entries"] and filtered_offers:
            for idx, past_p in enumerate(prof["past_prices"]):
                day_ts = (now - timedelta(days=len(prof["past_prices"]) - idx)).isoformat()
                w_hist["entries"].append(
                    {
                        "timestamp": day_ts,
                        "best_price": past_p,
                        "best_merchant": filtered_offers[0].merchant,
                        "best_url": filtered_offers[0].url,
                        "merchant_prices": {filtered_offers[0].merchant: past_p},
                        "bf_score": 70,
                    }
                )

    return direct_by_watch, disc_by_watch


def run_comparator(
    config_path: str = DEFAULT_CONFIG_PATH,
    history_path: str = DEFAULT_HISTORY_PATH,
    docs_dir: str = DEFAULT_DOCS_DIR,
    demo_mode: bool = False,
    no_notify: bool = False,
) -> List[WatchAnalysis]:
    """Run the full Black Friday watch comparison pipeline."""
    settings, watches = load_config(config_path)
    history = load_history(history_path)

    timeout = int(settings.get("request_timeout", 15))
    use_pw = bool(settings.get("use_playwright_fallback", True))
    auto_disc = bool(settings.get("auto_discovery", True))

    direct_by_watch: Dict[str, List[OfferResult]] = {}
    disc_by_watch: Dict[str, List[OfferResult]] = {}

    if demo_mode:
        direct_by_watch, disc_by_watch = generate_demo_offers_and_seed_history(watches, history)
    else:
        any_live_price = False
        for w in watches:
            print(f"🔎 Analyse de {w.name} ({len(w.urls)} URLs)...")
            w_offers: List[OfferResult] = []
            existing_urls = set()
            for u in w.urls:
                existing_urls.add(u.url)
                res = scrape_offer(
                    watch_id=w.id,
                    url=u.url,
                    merchant=u.merchant,
                    timeout=timeout,
                    use_playwright_fallback=use_pw,
                )
                if res.price is not None:
                    any_live_price = True
                w_offers.append(res)
            direct_by_watch[w.id] = w_offers

            if auto_disc:
                disc = discover_offers_for_watch(w, existing_urls, timeout=timeout)
                if any(d.price is not None for d in disc):
                    any_live_price = True
                disc_by_watch[w.id] = disc
            else:
                disc_by_watch[w.id] = []

        if not any_live_price:
            print("ℹ️ Accès réseau marchand restreint dans cet environnement : chargement des données de démonstration Black Friday.")
            direct_by_watch, disc_by_watch = generate_demo_offers_and_seed_history(watches, history)

    analyses: List[WatchAnalysis] = []
    for w in watches:
        analysis = analyze_watch_and_update_history(
            watch=w,
            direct_offers=direct_by_watch.get(w.id, []),
            discovered_offers=disc_by_watch.get(w.id, []),
            history=history,
        )
        analyses.append(analysis)

    save_history(history_path, history)

    dashboard_url = os.environ.get("GITHUB_PAGES_URL", "")
    summary = build_daily_recap_message(analyses, dashboard_url=dashboard_url)

    report_path = generate_html_report(
        analyses=analyses,
        history=history,
        settings=settings,
        summary=summary,
        output_dir=docs_dir,
    )

    print("\n" + "=" * 72)
    print(summary["title"])
    print("-" * 72)
    print(summary["body"])
    print("=" * 72)
    print(f"📊 Rapport HTML généré : {report_path}")

    if not no_notify:
        ntfy_topic = os.environ.get("NTFY_TOPIC") or settings.get("ntfy_topic", "")
        ntfy_server = settings.get("ntfy_server", "https://ntfy.sh")
        if ntfy_topic:
            sent = send_ntfy_chrome_push(ntfy_server, ntfy_topic, summary)
            status = "✅ envoyée" if sent else "⚠️ ignorée (réseau/sandbox)"
            print(f"📲 Notification Web Push Chrome (ntfy.sh/{ntfy_topic}) : {status}")
        send_local_desktop_notification(summary)

    return analyses


def add_url_to_config(
    watch_id: str,
    url: str,
    merchant: str = "",
    config_path: str = DEFAULT_CONFIG_PATH,
) -> bool:
    """Add any new product URL to an existing watch in watches.yaml."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    for item in data.get("watches", []):
        if item.get("id") == watch_id:
            urls = item.setdefault("urls", [])
            merchant_label = merchant or infer_merchant_name(url)
            urls.append({"url": url, "merchant": merchant_label})
            with open(config_path, "w", encoding="utf-8") as out:
                yaml.safe_dump(data, out, allow_unicode=True, sort_keys=False)
            print(f"✅ URL ajoutée à {item.get('name')} ({merchant_label}) : {url}")
            return True

    print(f"❌ Montre introuvable avec l'identifiant '{watch_id}'.")
    return False


def remove_url_from_config(
    url: str,
    watch_id: str = "",
    config_path: str = DEFAULT_CONFIG_PATH,
) -> bool:
    """Remove an invalid or unwanted product URL from watches.yaml."""
    target_url = url.strip()
    if not target_url:
        print("❌ URL vide.")
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    removed_count = 0
    for item in data.get("watches", []):
        if watch_id and item.get("id") != watch_id:
            continue
        urls = item.get("urls", [])
        new_urls = []
        for u in urls:
            u_str = u.get("url", "") if isinstance(u, dict) else str(u)
            if u_str.strip() == target_url:
                removed_count += 1
                print(f"🗑️ Lien supprimé de {item.get('name')} : {u_str}")
            else:
                new_urls.append(u)
        item["urls"] = new_urls

    if removed_count > 0:
        with open(config_path, "w", encoding="utf-8") as out:
            yaml.safe_dump(data, out, allow_unicode=True, sort_keys=False)
        return True

    print(f"⚠️ Aucun lien correspondant à '{target_url}' trouvé dans {config_path}.")
    return False


def slugify_id(text: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "montre"


def add_watch_to_config(
    name: str,
    brand: str,
    reference: str,
    target_price: float,
    reference_price: float,
    url: str = "",
    features: str = "Solaire • Radio-pilotée",
    watch_id: str = "",
    config_path: str = DEFAULT_CONFIG_PATH,
) -> bool:
    """Add a new competing watch model to watches.yaml."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    watches = data.setdefault("watches", [])
    final_id = watch_id.strip() or slugify_id(f"{brand}-{reference}")

    if any(w.get("id") == final_id for w in watches):
        print(f"⚠️ Un modèle avec l'identifiant '{final_id}' existe déjà.")
        return False

    urls_list = []
    if url.strip():
        urls_list.append({"url": url.strip(), "merchant": infer_merchant_name(url.strip())})

    new_entry = {
        "id": final_id,
        "name": name,
        "brand": brand,
        "reference": reference,
        "features": features,
        "target_price": float(target_price),
        "reference_price": float(reference_price),
        "search_queries": [reference, f"{brand} {reference}"],
        "urls": urls_list,
    }
    watches.append(new_entry)

    with open(config_path, "w", encoding="utf-8") as out:
        yaml.safe_dump(data, out, allow_unicode=True, sort_keys=False)

    print(f"✅ Nouveau modèle ajouté : {name} (id: {final_id})")
    return True


def remove_watch_from_config(
    watch_id_or_ref: str,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> bool:
    """Remove an entire watch model by its id or reference from watches.yaml."""
    key = watch_id_or_ref.strip().lower()
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    watches = data.get("watches", [])
    kept = []
    removed = []
    for w in watches:
        if str(w.get("id", "")).lower() == key or str(w.get("reference", "")).lower() == key:
            removed.append(w.get("name", key))
        else:
            kept.append(w)

    if not removed:
        print(f"⚠️ Aucune montre trouvée avec l'id ou la référence '{watch_id_or_ref}'.")
        return False

    data["watches"] = kept
    with open(config_path, "w", encoding="utf-8") as out:
        yaml.safe_dump(data, out, allow_unicode=True, sort_keys=False)

    for r in removed:
        print(f"🗑️ Modèle supprimé : {r}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Comparateur de Prix Black Friday — Montres Solaires Radio-Pilotées"
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Lancer le relevé des prix, l'analyse et générer le rapport HTML")
    run_p.add_argument("--demo", action="store_true", help="Utiliser des données de simulation Black Friday réalistes")
    run_p.add_argument("--no-notify", action="store_true", help="Ne pas envoyer de notification push")
    run_p.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Chemin vers watches.yaml")

    add_w = sub.add_parser("add-watch", help="Ajouter un nouveau modèle de montre en compétition dans watches.yaml")
    add_w.add_argument("--name", required=True, help="Nom complet (ex: 'Casio Oceanus OCW-T200S-1AJF')")
    add_w.add_argument("--brand", required=True, help="Marque (ex: Casio, Citizen, Seiko, Junghans)")
    add_w.add_argument("--ref", required=True, help="Référence exacte (ex: OCW-T200S-1AJF)")
    add_w.add_argument("--target", required=True, type=float, help="Prix cible Black Friday en € (ex: 349)")
    add_w.add_argument("--msrp", required=True, type=float, help="Prix public conseillé officiel en € (ex: 499)")
    add_w.add_argument("--url", default="", help="Première URL marchand (optionnel)")
    add_w.add_argument("--features", default="Solaire • Radio-pilotée", help="Caractéristiques clés")
    add_w.add_argument("--id", default="", help="Identifiant court personnalisé (optionnel)")
    add_w.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Chemin vers watches.yaml")

    rem_w = sub.add_parser("remove-watch", help="Supprimer un modèle de montre de watches.yaml")
    rem_w.add_argument("--watch", required=True, help="ID ou référence de la montre (ex: citizen-promaster-as4020 ou AT8110-61E)")
    rem_w.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Chemin vers watches.yaml")

    add_p = sub.add_parser("add-url", help="Ajouter une URL de marchand à une montre dans watches.yaml")
    add_p.add_argument("--watch", required=True, help="Identifiant de la montre (ex: casio-gwm5610u)")
    add_p.add_argument("--url", required=True, help="URL complète de la fiche produit")
    add_p.add_argument("--merchant", default="", help="Nom du marchand (optionnel, détecté auto)")

    rem_p = sub.add_parser("remove-url", help="Supprimer un lien invalide ou obsolète de watches.yaml")
    rem_p.add_argument("--url", required=True, help="URL complète à supprimer")
    rem_p.add_argument("--watch", default="", help="Identifiant de la montre (optionnel)")
    rem_p.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Chemin vers watches.yaml")

    sub.add_parser("test-notify", help="Envoyer une notification de test vers Chrome (ntfy.sh & local)")

    args = parser.parse_args()

    if args.command == "add-watch":
        add_watch_to_config(
            name=args.name,
            brand=args.brand,
            reference=args.ref,
            target_price=args.target,
            reference_price=args.msrp,
            url=args.url,
            features=args.features,
            watch_id=args.id,
            config_path=args.config,
        )
    elif args.command == "remove-watch":
        remove_watch_from_config(args.watch, config_path=args.config)
    elif args.command == "add-url":
        add_url_to_config(args.watch, args.url, args.merchant)
    elif args.command == "remove-url":
        remove_url_from_config(args.url, args.watch, config_path=args.config)
    elif args.command == "test-notify":
        settings, _ = load_config()
        dummy_summary = {
            "title": "🧪 Test Radar Black Friday — Notifications Chrome Opérationnelles !",
            "body": "Tu recevras ici le récapitulatif quotidien et les alertes de baisse sur tes montres solaires radio-pilotées.",
            "priority": "high",
            "tags": "watch,white_check_mark",
            "click_url": "",
        }
        topic = os.environ.get("NTFY_TOPIC") or settings.get("ntfy_topic", "")
        server = settings.get("ntfy_server", "https://ntfy.sh")
        ok = send_ntfy_chrome_push(server, topic, dummy_summary)
        send_local_desktop_notification(dummy_summary)
        print(f"Notification de test envoyée sur {server}/{topic} (succès={ok})")
    else:
        demo = getattr(args, "demo", False)
        no_notify = getattr(args, "no_notify", False)
        cfg = getattr(args, "config", DEFAULT_CONFIG_PATH)
        run_comparator(config_path=cfg, demo_mode=demo, no_notify=no_notify)


if __name__ == "__main__":
    main()
