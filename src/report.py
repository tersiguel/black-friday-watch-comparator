"""Interactive HTML report generator for GitHub Pages with Dark/Light Mode toggle, URL deletion, and multi-channel Chrome Notifications."""

import html
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.models import WatchAnalysis


def generate_html_report(
    analyses: List[WatchAnalysis],
    history: Dict[str, Any],
    settings: Dict[str, Any],
    summary: Dict[str, Any],
    output_dir: str = "docs",
) -> str:
    """Generate docs/index.html, docs/sw.js, and docs/latest_summary.json."""
    os.makedirs(output_dir, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
    now_iso = datetime.now(timezone.utc).isoformat()

    ntfy_topic = settings.get("ntfy_topic", "bf-montres-solaires-2026")
    ntfy_server = settings.get("ntfy_server", "https://ntfy.sh").rstrip("/")
    ntfy_web_url = f"{ntfy_server}/app"

    sorted_analyses = sorted(analyses, key=lambda a: a.bf_score, reverse=True)
    champion = sorted_analyses[0] if sorted_analyses else None

    latest_payload = {
        "updated_at": now_iso,
        "updated_at_human": now_str,
        "notification_title": summary["title"],
        "notification_body": summary["body"],
        "click_url": summary.get("click_url", ""),
        "ntfy_topic": ntfy_topic,
        "ntfy_server": ntfy_server,
        "watches": [
            {
                "id": a.watch.id,
                "name": a.watch.name,
                "reference": a.watch.reference,
                "best_price": a.best_offer.price if a.best_offer else None,
                "best_merchant": a.best_offer.merchant if a.best_offer else None,
                "best_url": a.best_offer.url if a.best_offer else None,
                "target_price": a.watch.target_price,
                "bf_score": a.bf_score,
                "verdict": a.bf_verdict,
            }
            for a in sorted_analyses
        ],
    }

    summary_path = os.path.join(output_dir, "latest_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(latest_payload, f, indent=2, ensure_ascii=False)

    # Write Service Worker (docs/sw.js) for Chrome registration.showNotification support
    sw_code = """self.addEventListener('install', (event) => {
    self.skipWaiting();
});
self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ('focus' in client) return client.focus();
            }
            if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
        })
    );
});
"""
    sw_path = os.path.join(output_dir, "sw.js")
    with open(sw_path, "w", encoding="utf-8") as f:
        f.write(sw_code)

    chart_data_by_watch: Dict[str, Any] = {}
    for a in sorted_analyses:
        w_hist = history.get("watches", {}).get(a.watch.id, {})
        entries = w_hist.get("entries", [])
        labels = []
        best_prices = []
        target_line = []
        msrp_line = []
        for e in entries[-30:]:
            ts = e.get("timestamp", "")
            label = ts[5:16].replace("T", " ") if len(ts) >= 16 else ts
            labels.append(label)
            best_prices.append(e.get("best_price"))
            target_line.append(a.watch.target_price)
            msrp_line.append(a.watch.reference_price)
        chart_data_by_watch[a.watch.id] = {
            "name": a.watch.name,
            "reference": a.watch.reference,
            "labels": labels,
            "best_prices": best_prices,
            "target_line": target_line,
            "msrp_line": msrp_line,
        }

    comparison_rows_html = []
    watch_cards_html = []
    discovered_cards_html = []

    badge_colors = {
        "exceptional": "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
        "target_reached": "bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/40",
        "good": "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/40",
        "fake_promo": "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/40",
        "wait": "bg-slate-200 dark:bg-slate-700/60 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-600",
    }

    for rank, a in enumerate(sorted_analyses, start=1):
        w = a.watch
        best = a.best_offer
        price_str = f"{best.price:.2f} €" if (best and best.price is not None) else "Indisponible"
        merchant_str = html.escape(best.merchant) if best else "—"
        url_str = html.escape(best.url) if best else "#"
        url_js = html.escape(json.dumps(best.url if best else ""))
        watch_id_js = html.escape(json.dumps(w.id))
        merchant_js = html.escape(json.dumps(best.merchant if best else ""))
        badge_cls = badge_colors.get(a.bf_verdict_level, badge_colors["wait"])

        diff_target = a.discount_vs_target_diff
        if best and best.price is not None:
            if diff_target <= 0:
                target_badge = f'<span class="text-emerald-600 dark:text-emerald-400 font-semibold">{diff_target:+.2f} € (Sous la cible !)</span>'
            else:
                target_badge = f'<span class="text-amber-600 dark:text-amber-300 font-medium">+{diff_target:.2f} € vs cible ({w.target_price:.0f} €)</span>'
        else:
            target_badge = "—"

        low_hist_str = f"{a.lowest_historical_price:.2f} €" if a.lowest_historical_price else "—"
        msrp_discount_str = f"-{a.discount_vs_msrp_pct:.0f}%" if a.discount_vs_msrp_pct > 0 else "0%"

        fake_alert_banner = ""
        if a.is_fake_promo and a.fake_promo_reason:
            fake_alert_banner = f"""
            <div class="mt-2 rounded-lg bg-rose-50 dark:bg-rose-950/70 border border-rose-300 dark:border-rose-500/40 px-3 py-2 text-xs text-rose-700 dark:text-rose-200 flex items-center gap-2">
                <span>🚨</span>
                <span><strong>Alerte Anti-Fausse Promo :</strong> {html.escape(a.fake_promo_reason)}</span>
            </div>
            """

        comparison_rows_html.append(f"""
        <tr data-offer-url="{url_str}" class="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-100/80 dark:hover:bg-slate-800/50 transition">
            <td class="py-3.5 px-4 font-bold text-amber-600 dark:text-amber-400">#{rank}</td>
            <td class="py-3.5 px-4">
                <div class="font-semibold text-slate-900 dark:text-white">{html.escape(w.name)}</div>
                <div class="text-xs text-slate-500 dark:text-slate-400">Réf: <code class="text-slate-700 dark:text-slate-300 font-mono">{html.escape(w.reference)}</code> • {html.escape(w.features)}</div>
                {fake_alert_banner}
            </td>
            <td class="py-3.5 px-4">
                <div class="text-xl font-extrabold text-slate-900 dark:text-white">{price_str}</div>
                <div class="text-xs text-slate-500 dark:text-slate-400">Prix public: <span class="line-through">{w.reference_price:.0f} €</span> (<span class="text-emerald-600 dark:text-emerald-400 font-semibold">{msrp_discount_str}</span>)</div>
            </td>
            <td class="py-3.5 px-4 text-sm">{target_badge}</td>
            <td class="py-3.5 px-4 text-sm text-slate-700 dark:text-slate-300 font-medium">{low_hist_str}</td>
            <td class="py-3.5 px-4">
                <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border {badge_cls}">
                    {html.escape(a.bf_verdict)}
                </span>
            </td>
            <td class="py-3.5 px-4 text-center">
                <div class="inline-flex items-center justify-center w-11 h-11 rounded-full bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 font-bold text-amber-600 dark:text-amber-400">
                    {a.bf_score}
                </div>
            </td>
            <td class="py-3.5 px-4 text-right">
                <div class="inline-flex items-center justify-end gap-1.5">
                    <a href="{url_str}" target="_blank" rel="noopener"
                       class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs transition shadow">
                       Voir chez {merchant_str} ↗
                    </a>
                    <button onclick="removeInvalidLink({watch_id_js}, {url_js}, {merchant_js})"
                       class="p-2 rounded-lg bg-rose-500/10 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 border border-rose-500/30 text-xs transition"
                       title="Signaler et supprimer ce lien s'il est invalide ou expiré">
                       🗑️
                    </button>
                </div>
            </td>
        </tr>
        """)

        offer_items_html = []
        all_watch_offers = sorted(
            a.offers,
            key=lambda o: (o.price is None, o.price if o.price is not None else 999999),
        )
        for o in all_watch_offers:
            o_url_escaped = html.escape(o.url)
            o_url_js = html.escape(json.dumps(o.url))
            o_merch_js = html.escape(json.dumps(o.merchant))
            if o.price is not None:
                old_p = f'<span class="line-through text-xs text-slate-400 dark:text-slate-500 ml-1">{o.original_price:.2f} €</span>' if o.original_price else ""
                promo_b = f'<span class="ml-2 px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-700 dark:text-purple-300 text-[10px] font-mono">Code: {html.escape(o.promo_code)}</span>' if o.promo_code else ""
                ship_b = f'<div class="text-[11px] text-amber-600 dark:text-amber-400 mt-0.5">{html.escape(o.shipping_note)}</div>' if o.shipping_note else ""
                stock_b = '<span class="text-emerald-600 dark:text-emerald-400 text-xs">● En stock</span>' if o.in_stock else '<span class="text-rose-600 dark:text-rose-400 text-xs">● Rupture</span>'
                offer_items_html.append(f"""
                <div data-offer-url="{o_url_escaped}" class="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-50 dark:bg-slate-950/70 border border-slate-200 dark:border-slate-800/80 transition">
                    <div>
                        <span class="font-medium text-slate-800 dark:text-slate-200 text-sm">{html.escape(o.merchant)}</span>
                        <span class="ml-2">{stock_b}</span>
                        {promo_b}
                        {ship_b}
                    </div>
                    <div class="flex items-center gap-2">
                        <div class="text-right mr-1">
                            <span class="font-bold text-slate-900 dark:text-white">{o.price:.2f} €</span>
                            {old_p}
                        </div>
                        <a href="{o_url_escaped}" target="_blank" rel="noopener" class="text-xs px-2.5 py-1 rounded bg-slate-200/80 hover:bg-slate-300 dark:bg-slate-800 dark:hover:bg-slate-700 text-amber-700 dark:text-amber-300 font-semibold transition">Lien ↗</a>
                        <button onclick="removeInvalidLink({watch_id_js}, {o_url_js}, {o_merch_js})"
                            class="px-2 py-1 rounded bg-rose-500/10 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 border border-rose-500/25 text-xs transition"
                            title="Supprimer ce lien invalide">
                            🗑️
                        </button>
                    </div>
                </div>
                """)
            else:
                offer_items_html.append(f"""
                <div data-offer-url="{o_url_escaped}" class="flex items-center justify-between py-2 px-3 rounded-lg bg-rose-50/70 dark:bg-rose-950/30 border border-rose-300 dark:border-rose-800/60 transition">
                    <div>
                        <span class="text-sm font-medium text-slate-700 dark:text-slate-300">{html.escape(o.merchant)}</span>
                        <span class="ml-2 text-xs text-rose-600 dark:text-rose-400">⚠️ {html.escape(o.error or 'Lien invalide / Prix non détecté')}</span>
                    </div>
                    <div class="flex items-center gap-2">
                        <a href="{o_url_escaped}" target="_blank" rel="noopener" class="text-xs px-2 py-1 rounded bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Vérifier ↗</a>
                        <button onclick="removeInvalidLink({watch_id_js}, {o_url_js}, {o_merch_js})"
                            class="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs shadow transition"
                            title="Supprimer ce lien invalide">
                            🗑️ Supprimer ce lien
                        </button>
                    </div>
                </div>
                """)

        watch_cards_html.append(f"""
        <div class="rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-5 flex flex-col justify-between shadow-lg transition-colors">
            <div>
                <div class="flex items-start justify-between gap-2 mb-3">
                    <div>
                        <span class="text-xs font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400">{html.escape(w.brand)} • Réf. {html.escape(w.reference)}</span>
                        <h3 class="text-lg font-bold text-slate-900 dark:text-white mt-0.5">{html.escape(w.name)}</h3>
                    </div>
                    <span class="px-2.5 py-1 rounded-full text-xs font-semibold border {badge_cls}">Score {a.bf_score}/100</span>
                </div>
                <p class="text-xs text-slate-500 dark:text-slate-400 mb-4">{html.escape(w.features)}</p>
                <div class="grid grid-cols-3 gap-2 mb-4 text-center">
                    <div class="rounded-lg bg-slate-50 dark:bg-slate-950/70 p-2.5 border border-slate-200 dark:border-slate-800">
                        <div class="text-[11px] text-slate-500 dark:text-slate-400">Meilleur Prix</div>
                        <div class="text-base font-extrabold text-emerald-600 dark:text-emerald-400">{price_str}</div>
                    </div>
                    <div class="rounded-lg bg-slate-50 dark:bg-slate-950/70 p-2.5 border border-slate-200 dark:border-slate-800">
                        <div class="text-[11px] text-slate-500 dark:text-slate-400">Ton Prix Cible</div>
                        <div class="text-base font-bold text-amber-600 dark:text-amber-300">{w.target_price:.0f} €</div>
                    </div>
                    <div class="rounded-lg bg-slate-50 dark:bg-slate-950/70 p-2.5 border border-slate-200 dark:border-slate-800">
                        <div class="text-[11px] text-slate-500 dark:text-slate-400">Plus Bas Observé</div>
                        <div class="text-base font-bold text-sky-600 dark:text-sky-300">{low_hist_str}</div>
                    </div>
                </div>
                <div class="space-y-2 mb-4">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Offres Marchands Surveillées</div>
                    {''.join(offer_items_html)}
                </div>
            </div>
            <div class="pt-3 border-t border-slate-200 dark:border-slate-800">
                <button onclick="selectWatchChart('{html.escape(w.id)}')" class="w-full py-2 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-xs font-semibold text-sky-700 dark:text-sky-300 transition">
                    📈 Afficher la courbe d'évolution de cette montre
                </button>
            </div>
        </div>
        """)

        for d in a.discovered_offers:
            if d.price is not None:
                d_url_escaped = html.escape(d.url)
                d_url_js = html.escape(json.dumps(d.url))
                d_merch_js = html.escape(json.dumps(d.merchant))
                temp_badge = f'<span class="px-2 py-0.5 rounded bg-orange-500/15 text-orange-600 dark:text-orange-300 text-xs font-bold">🔥 {html.escape(d.temperature)}</span>' if d.temperature else ""
                ship_note_html = f'<div class="text-xs text-amber-600 dark:text-amber-400 mt-0.5 font-medium">{html.escape(d.shipping_note)}</div>' if d.shipping_note else ""
                discovered_cards_html.append(f"""
                <div data-offer-url="{d_url_escaped}" class="rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-4 flex items-center justify-between gap-4 shadow-sm transition-colors">
                    <div>
                        <div class="flex items-center gap-2">
                            <span class="text-xs font-bold text-amber-600 dark:text-amber-400">{html.escape(w.reference)}</span>
                            <span class="text-xs text-slate-500 dark:text-slate-400">via {html.escape(d.merchant)}</span>
                            {temp_badge}
                        </div>
                        <div class="text-sm font-semibold text-slate-900 dark:text-white mt-1">{html.escape(d.title or w.name)}</div>
                        {ship_note_html}
                    </div>
                    <div class="flex items-center gap-2.5 shrink-0">
                        <div class="text-lg font-extrabold text-emerald-600 dark:text-emerald-400">{d.price:.2f} €</div>
                        <a href="{d_url_escaped}" target="_blank" rel="noopener"
                           class="px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs transition">
                           Voir l'offre ↗
                        </a>
                        <button onclick="removeInvalidLink({watch_id_js}, {d_url_js}, {d_merch_js})"
                           class="px-2.5 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 border border-rose-500/30 text-xs transition"
                           title="Supprimer cette offre si le lien est invalide">
                           🗑️
                        </button>
                    </div>
                </div>
                """)

    discovered_section_html = (
        "".join(discovered_cards_html)
        if discovered_cards_html
        else """
        <div class="rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 p-6 text-center text-sm text-slate-500 dark:text-slate-400">
            Aucune offre externe supplémentaire découverte sur ce cycle — les offres principales ci-dessus couvrent déjà les meilleurs tarifs trouvés.
        </div>
        """
    )

    champion_banner = ""
    if champion and champion.best_offer and champion.best_offer.price is not None:
        c_w = champion.watch
        c_o = champion.best_offer
        champion_banner = f"""
        <div data-offer-url="{html.escape(c_o.url)}" class="rounded-2xl bg-gradient-to-r from-amber-500/15 via-emerald-500/10 to-white dark:from-amber-500/20 dark:via-emerald-500/10 dark:to-slate-900 border border-amber-500/40 p-6 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 shadow-md transition-colors">
            <div>
                <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500 text-slate-950 font-extrabold text-xs uppercase tracking-wider mb-2">
                    🏆 Meilleure Opportunité Black Friday du Jour (Score {champion.bf_score}/100)
                </div>
                <h2 class="text-2xl font-extrabold text-slate-900 dark:text-white">{html.escape(c_w.name)}</h2>
                <p class="text-sm text-slate-700 dark:text-slate-300 mt-1">
                    En tête de la compétition à <strong class="text-emerald-600 dark:text-emerald-400 text-lg">{c_o.price:.2f} €</strong> chez <strong>{html.escape(c_o.merchant)}</strong>
                    (Prix public {c_w.reference_price:.0f} € • Remise réelle <strong>-{champion.discount_vs_msrp_pct:.0f}%</strong> • Cible {c_w.target_price:.0f} €)
                </p>
            </div>
            <a href="{html.escape(c_o.url)}" target="_blank" rel="noopener"
               class="px-5 py-3 rounded-xl bg-amber-400 hover:bg-amber-300 text-slate-950 font-extrabold text-sm shadow-lg shrink-0 transition">
               Accéder au Deal ({c_o.price:.2f} €) ↗
            </a>
        </div>
        """

    html_doc = f"""<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Radar Black Friday — Montres Solaires Radio-Pilotées</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            darkMode: 'class'
        }};
        (function() {{
            try {{
                const savedTheme = localStorage.getItem('bf_watch_theme');
                if (savedTheme === 'light') {{
                    document.documentElement.classList.remove('dark');
                }} else if (savedTheme === 'dark') {{
                    document.documentElement.classList.add('dark');
                }} else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {{
                    document.documentElement.classList.remove('dark');
                }} else {{
                    document.documentElement.classList.add('dark');
                }}
            }} catch (e) {{
                document.documentElement.classList.add('dark');
            }}
        }})();
    </script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body class="bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 min-h-screen font-sans selection:bg-amber-400 selection:text-slate-950 transition-colors duration-200">
    <!-- Toast Container for visual Chrome-style notifications & link removal actions -->
    <div id="chromeToastContainer" class="fixed top-4 right-4 z-50 flex flex-col gap-3 max-w-md w-full pointer-events-none px-4 sm:px-0"></div>

    <!-- Modal for permanent removal of invalid URLs from watches.yaml -->
    <div id="removeLinkModal" class="fixed inset-0 z-50 hidden items-center justify-center bg-slate-950/75 backdrop-blur-sm p-4">
        <div class="rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 max-w-lg w-full p-6 shadow-2xl">
            <div class="flex items-start justify-between gap-3 mb-3">
                <div class="flex items-center gap-2 text-rose-600 dark:text-rose-400 font-bold text-lg">
                    <span>🗑️</span>
                    <span>Lien invalide masqué du tableau de bord</span>
                </div>
                <button onclick="closeRemoveModal()" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-lg font-bold">✕</button>
            </div>
            <p class="text-xs text-slate-600 dark:text-slate-300 mb-3">
                Le lien <strong id="removedMerchantLabel" class="text-slate-900 dark:text-white"></strong> a été immédiatement retiré de ton affichage.
                Pour le supprimer définitivement de <code class="font-mono text-amber-600 dark:text-amber-400">watches.yaml</code> afin qu'il ne soit plus scanné aux prochains cycles :
            </p>
            <div class="space-y-3 text-xs">
                <div class="rounded-xl bg-slate-100 dark:bg-slate-950 p-3 border border-slate-200 dark:border-slate-800">
                    <div class="font-semibold text-slate-700 dark:text-slate-300 mb-1">Option 1 — En 1 commande dans le terminal :</div>
                    <div class="flex items-center gap-2">
                        <code id="cliRemoveCmd" class="flex-1 overflow-x-auto font-mono text-[11px] text-emerald-700 dark:text-emerald-400 bg-white dark:bg-slate-900 px-2.5 py-1.5 rounded border border-slate-200 dark:border-slate-800"></code>
                        <button onclick="copyCliCommand()" class="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold shrink-0">Copier</button>
                    </div>
                </div>
                <div class="rounded-xl bg-slate-100 dark:bg-slate-950 p-3 border border-slate-200 dark:border-slate-800">
                    <div class="font-semibold text-slate-700 dark:text-slate-300 mb-1">Option 2 — Directement sur GitHub :</div>
                    <div class="flex flex-wrap items-center gap-2 mt-2">
                        <a href="https://github.com/tersiguel/black-friday-watch-comparator/edit/feat/black-friday-watch-comparator/watches.yaml" target="_blank" rel="noopener"
                           class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-white font-semibold">
                           ✏️ Éditer watches.yaml sur GitHub ↗
                        </a>
                        <a href="https://github.com/tersiguel/black-friday-watch-comparator/actions/workflows/price-tracker.yml" target="_blank" rel="noopener"
                           class="px-3 py-1.5 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 text-sky-700 dark:text-sky-300 border border-sky-500/30 font-semibold">
                           ⚡ Lancer l'action remove_url sur GitHub ↗
                        </a>
                    </div>
                </div>
            </div>
            <div class="mt-5 flex items-center justify-between pt-3 border-t border-slate-200 dark:border-slate-800">
                <button onclick="restoreRemovedLinks()" class="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 underline">
                    Annuler et réafficher tous les liens masqués
                </button>
                <button onclick="closeRemoveModal()" class="px-4 py-2 rounded-xl bg-slate-900 dark:bg-slate-800 text-white text-xs font-bold">
                    Fermer
                </button>
            </div>
        </div>
    </div>

    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <!-- Header -->
        <header class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 pb-6 mb-8 border-b border-slate-200 dark:border-slate-800">
            <div>
                <div class="flex items-center gap-2 text-amber-600 dark:text-amber-400 text-xs font-bold uppercase tracking-widest">
                    <span>⌚ Tough Solar / Eco-Drive • Multi-Band 6 Radio-Controlled</span>
                </div>
                <h1 class="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white mt-1">
                    Comparateur Black Friday — Montres Solaires Radio-Pilotées
                </h1>
                <p class="text-sm text-slate-600 dark:text-slate-400 mt-1">
                    Dernier relevé automatique : <strong class="text-slate-900 dark:text-slate-200">{now_str}</strong> • Anti-fausse promo & récapitulatif quotidien actif
                </p>
            </div>

            <!-- Theme Toggle & Chrome Notification Controls -->
            <div class="flex flex-wrap items-center gap-2.5">
                <button id="btnThemeToggle" onclick="toggleDarkMode()"
                    class="inline-flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-white dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-semibold text-xs border border-slate-300 dark:border-slate-700 shadow-sm transition"
                    title="Basculer entre le mode sombre (Dark Mode) et le mode clair">
                    <span id="themeToggleIcon">☀️</span>
                    <span id="themeToggleText">Mode Clair</span>
                </button>
                <button id="btnChromeNotif" onclick="enableBrowserNotifications()"
                    class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs shadow transition">
                    🔔 Activer les notifications Chrome
                </button>
                <button onclick="sendTestChromeNotification()"
                    class="inline-flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs shadow transition">
                    🧪 Tester la notif Chrome
                </button>
                <a href="{html.escape(ntfy_web_url)}" target="_blank" rel="noopener"
                    class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-700 dark:text-emerald-300 border border-emerald-500/40 font-semibold text-xs transition"
                    title="Recevoir les notifications Chrome même quand cet onglet est fermé">
                    📲 Web Push Chrome ({html.escape(ntfy_topic)}) ↗
                </a>
            </div>
        </header>

        <!-- Chrome Notification Setup Helper Box -->
        <div class="rounded-xl bg-white dark:bg-slate-900/90 border border-slate-200 dark:border-slate-800 p-4 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-xs text-slate-600 dark:text-slate-300 shadow-sm transition-colors">
            <div class="space-y-1">
                <div class="font-bold text-slate-900 dark:text-white flex flex-wrap items-center gap-2">
                    <span>💡 État des notifications Google Chrome :</span>
                    <span id="chromePermStatus" class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-amber-600 dark:text-amber-300">Vérification...</span>
                    <button id="btnRestoreLinksBadge" onclick="restoreRemovedLinks()" class="hidden px-2 py-0.5 rounded bg-rose-500/15 text-rose-600 dark:text-rose-300 border border-rose-500/30 hover:bg-rose-500/25 transition">
                        🔄 Réafficher les liens supprimés
                    </button>
                </div>
                <p>
                    • Clique sur <strong>« 🧪 Tester la notif Chrome »</strong> : déclenche à la fois la notification native Chrome (si tu es sur la page <a href="https://tersiguel.github.io/black-friday-watch-comparator/" target="_blank" class="text-sky-600 dark:text-sky-400 underline font-semibold">GitHub Pages</a> hors iframe), un aperçu visuel immédiat + un envoi réel sur ton canal Web Push <code class="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-950 text-amber-700 dark:text-amber-300 font-mono">{html.escape(ntfy_topic)}</code>.<br/>
                    • Si un lien marchand est mort ou invalide, clique sur le bouton <strong>🗑️</strong> en face de l'offre pour le supprimer.
                </p>
            </div>
        </div>

        {champion_banner}

        <!-- Podium / Comparison Table -->
        <section class="mb-10">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-bold text-slate-900 dark:text-white">🏁 Classement des Modèles en Compétition</h2>
                <span class="text-xs text-slate-500 dark:text-slate-400">Trié par Score Black Friday (vraie remise vs prix public & prix cible)</span>
            </div>
            <div class="overflow-x-auto rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/80 shadow-xl transition-colors">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-200 dark:border-slate-800 text-[11px] uppercase tracking-wider text-slate-500 dark:text-slate-400 bg-slate-100/80 dark:bg-slate-950/60">
                            <th class="py-3 px-4">Rang</th>
                            <th class="py-3 px-4">Modèle & Caractéristiques</th>
                            <th class="py-3 px-4">Meilleur Prix</th>
                            <th class="py-3 px-4">Écart Cible</th>
                            <th class="py-3 px-4">Plus Bas Hist.</th>
                            <th class="py-3 px-4">Verdict Black Friday</th>
                            <th class="py-3 px-4 text-center">Score BF</th>
                            <th class="py-3 px-4 text-right">Meilleure Offre / Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(comparison_rows_html)}
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Price Evolution Chart -->
        <section class="mb-10 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-6 shadow-xl transition-colors">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
                <div>
                    <h2 class="text-xl font-bold text-slate-900 dark:text-white">📈 Historique des Prix & Détection des Fausses Promos</h2>
                    <p class="text-xs text-slate-500 dark:text-slate-400">Compare le meilleur prix relevé (vert) avec ton prix cible (ambre) et le prix public officiel (gris)</p>
                </div>
                <select id="watchChartSelector" onchange="selectWatchChart(this.value)"
                    class="rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-slate-700 px-3.5 py-2 text-sm text-slate-900 dark:text-white font-medium">
                    {''.join(f'<option value="{html.escape(a.watch.id)}">{html.escape(a.watch.name)}</option>' for a in sorted_analyses)}
                </select>
            </div>
            <div class="h-72 w-full">
                <canvas id="priceHistoryChart"></canvas>
            </div>
        </section>

        <!-- Detailed Cards per Watch -->
        <section class="mb-10">
            <h2 class="text-xl font-bold text-slate-900 dark:text-white mb-4">🔍 Détail des Offres par Montre (avec suppression des liens invalides)</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                {''.join(watch_cards_html)}
            </div>
        </section>

        <!-- Auto-Discovered Deals Section -->
        <section class="mb-12">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-bold text-slate-900 dark:text-white">🛰️ Nouvelles Offres & Deals Découverts par Référence</h2>
                <span class="text-xs text-slate-500 dark:text-slate-400">Recherche automatique Dealabs & comparateurs</span>
            </div>
            <div class="space-y-3">
                {discovered_section_html}
            </div>
        </section>

        <footer class="text-center text-xs text-slate-500 dark:text-slate-500 pt-6 border-t border-slate-200 dark:border-slate-900">
            Propulsé par GitHub Actions & Python • Configuration dans <code>watches.yaml</code> • Historique versionné dans <code>data/history.json</code>
        </footer>
    </div>

    <script>
        const CHART_DATA = {json.dumps(chart_data_by_watch, ensure_ascii=False)};
        const LATEST_SUMMARY = {json.dumps(latest_payload, ensure_ascii=False)};
        const REMOVED_URLS_KEY = 'bf_watch_removed_urls';
        let priceChart = null;
        let currentWatchId = null;
        let lastSeenTimestamp = LATEST_SUMMARY.updated_at;
        let swRegistration = null;

        // Register Service Worker if hosted over HTTP/HTTPS (GitHub Pages)
        if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.protocol === 'http:')) {{
            navigator.serviceWorker.register('sw.js').then((reg) => {{
                swRegistration = reg;
            }}).catch(() => {{}});
        }}

        function isInCrossOriginIframe() {{
            try {{
                return window.self !== window.top;
            }} catch (e) {{
                return true;
            }}
        }}

        // Visual Chrome-style notification banner + optional Web Audio chime
        function showVisualChromeNotification(title, body, clickUrl, statusNote) {{
            const container = document.getElementById('chromeToastContainer');
            if (!container) return;

            // Play subtle notification chime
            try {{
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) {{
                    const ctx = new AudioCtx();
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
                    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.12); // A5
                    gain.gain.setValueAtTime(0.08, ctx.currentTime);
                    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start();
                    osc.stop(ctx.currentTime + 0.45);
                }}
            }} catch (e) {{}}

            const toast = document.createElement('div');
            toast.className = 'pointer-events-auto rounded-2xl bg-slate-900/95 dark:bg-slate-900 border-2 border-amber-400/80 text-white p-4 shadow-2xl transition-all duration-300 transform translate-y-0';
            const firstLines = (body || '').split('\\n').slice(0, 3).join('<br/>');
            const noteHtml = statusNote ? `<div class="mt-2 pt-2 border-t border-slate-800 text-[11px] text-sky-300">${{statusNote}}</div>` : '';

            toast.innerHTML = `
                <div class="flex items-start justify-between gap-3">
                    <div class="flex items-center gap-2 text-xs font-bold text-amber-400 uppercase tracking-wider">
                        <span>🔔 Notification Google Chrome</span>
                    </div>
                    <button class="text-slate-400 hover:text-white text-sm font-bold" onclick="this.closest('.pointer-events-auto').remove()">✕</button>
                </div>
                <div class="font-bold text-sm text-white mt-1">${{title}}</div>
                <div class="text-xs text-slate-300 mt-1.5 leading-relaxed">${{firstLines}}</div>
                ${{noteHtml}}
            `;
            if (clickUrl) {{
                toast.style.cursor = 'pointer';
                toast.addEventListener('click', (ev) => {{
                    if (ev.target.tagName.toLowerCase() === 'button') return;
                    window.open(clickUrl, '_blank');
                }});
            }}
            container.prepend(toast);
            setTimeout(() => {{
                if (toast.parentNode) toast.remove();
            }}, 10000);
        }}

        function updateChromePermUI() {{
            const badge = document.getElementById('chromePermStatus');
            const btn = document.getElementById('btnChromeNotif');
            if (!badge || !btn) return;

            if (isInCrossOriginIframe()) {{
                badge.textContent = 'Aperçu intégré (Notif visuelle + Web Push ntfy.sh actifs)';
                badge.className = 'px-2 py-0.5 rounded bg-sky-500/20 text-sky-700 dark:text-sky-300';
                return;
            }}
            if (!('Notification' in window)) {{
                badge.textContent = 'Mode Notification Visuelle + Web Push ntfy.sh';
                return;
            }}
            if (Notification.permission === 'granted') {{
                badge.textContent = '✅ Notifications Chrome natives actives';
                badge.className = 'px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-700 dark:text-emerald-300';
                btn.textContent = '🔔 Notifications Chrome Activées';
            }} else if (Notification.permission === 'denied') {{
                badge.textContent = '⚠️ Permission native bloquée (Toast visuel + ntfy.sh actifs)';
                badge.className = 'px-2 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-300';
            }} else {{
                badge.textContent = 'Prêt à activer (Clique sur Activer ou Tester)';
            }}
        }}

        async function enableBrowserNotifications() {{
            if (isInCrossOriginIframe()) {{
                showVisualChromeNotification(
                    LATEST_SUMMARY.notification_title,
                    LATEST_SUMMARY.notification_body,
                    LATEST_SUMMARY.click_url,
                    '💡 Tu es dans l\\'aperçu intégré : les iframes bloquent la popup système OS. Ouvre la page GitHub Pages dans un onglet Chrome ou abonne-toi à ntfy.sh pour la popup système !'
                );
                return;
            }}
            if (!('Notification' in window)) {{
                showVisualChromeNotification(
                    LATEST_SUMMARY.notification_title,
                    LATEST_SUMMARY.notification_body,
                    LATEST_SUMMARY.click_url,
                    'ℹ️ Ton navigateur utilise le mode d\\'alerte visuel intégré.'
                );
                return;
            }}
            try {{
                const perm = await Notification.requestPermission();
                updateChromePermUI();
                await sendTestChromeNotification();
            }} catch (e) {{
                await sendTestChromeNotification();
            }}
        }}

        async function triggerNativeOrSwNotification(title, body, clickUrl) {{
            if (!('Notification' in window) || Notification.permission !== 'granted' || isInCrossOriginIframe()) {{
                return false;
            }}
            try {{
                if (swRegistration && swRegistration.showNotification) {{
                    await swRegistration.showNotification(title, {{
                        body: body,
                        tag: 'bf-watch-comparator-' + Date.now(),
                        data: {{ url: clickUrl }}
                    }});
                    return true;
                }}
            }} catch (e) {{}}
            try {{
                const n = new Notification(title, {{
                    body: body,
                    tag: 'bf-watch-comparator-' + Date.now()
                }});
                n.onclick = () => {{
                    window.focus();
                    if (clickUrl) window.open(clickUrl, '_blank');
                }};
                return true;
            }} catch (e) {{
                return false;
            }}
        }}

        async function sendTestChromeNotification() {{
            // 1. If permission is 'default' and not in iframe, request it first
            if ('Notification' in window && Notification.permission === 'default' && !isInCrossOriginIframe()) {{
                try {{
                    await Notification.requestPermission();
                    updateChromePermUI();
                }} catch (e) {{}}
            }}

            // 2. Try native OS Chrome notification (works on GitHub Pages / localhost)
            const nativeShown = await triggerNativeOrSwNotification(
                LATEST_SUMMARY.notification_title,
                LATEST_SUMMARY.notification_body,
                LATEST_SUMMARY.click_url
            );

            // 3. Also send real Web Push to ntfy.sh topic from browser so subscribed Chrome gets it even in background
            let ntfySent = false;
            if (LATEST_SUMMARY.ntfy_topic && LATEST_SUMMARY.ntfy_server) {{
                try {{
                    const res = await fetch(LATEST_SUMMARY.ntfy_server + '/' + LATEST_SUMMARY.ntfy_topic, {{
                        method: 'POST',
                        body: LATEST_SUMMARY.notification_body,
                        headers: {{
                            'Title': 'Test Radar Black Friday Montres',
                            'Priority': 'high',
                            'Tags': 'watch,fire'
                        }}
                    }});
                    ntfySent = res.ok;
                }} catch (e) {{}}
            }}

            // 4. Always show visual Chrome notification toast so user gets immediate feedback in all contexts
            let statusNote = '';
            if (nativeShown && ntfySent) {{
                statusNote = '✅ Notification système Chrome + Web Push ntfy.sh (' + LATEST_SUMMARY.ntfy_topic + ') envoyés !';
            }} else if (nativeShown) {{
                statusNote = '✅ Notification système Chrome affichée !';
            }} else if (ntfySent) {{
                statusNote = '📲 Web Push envoyé sur ntfy.sh/' + LATEST_SUMMARY.ntfy_topic + ' ! (Ouvre le lien GitHub Pages hors aperçu pour la popup native de l\\'onglet)';
            }} else if (isInCrossOriginIframe()) {{
                statusNote = '💡 Aperçu intégré : clique sur la carte "Radar Black Friday — Tableau de Bord GitHub Pages" pour autoriser les notifications natives Chrome.';
            }} else {{
                statusNote = '🔔 Aperçu de ta notification Chrome (Vérifie que les notifications sont autorisées à gauche de l\\'URL dans Chrome).';
            }}

            showVisualChromeNotification(
                LATEST_SUMMARY.notification_title,
                LATEST_SUMMARY.notification_body,
                LATEST_SUMMARY.click_url,
                statusNote
            );
        }}

        // Invalid link removal management
        function getRemovedUrls() {{
            try {{
                const raw = localStorage.getItem(REMOVED_URLS_KEY);
                return raw ? JSON.parse(raw) : [];
            }} catch (e) {{
                return [];
            }}
        }}

        function saveRemovedUrls(list) {{
            try {{
                localStorage.setItem(REMOVED_URLS_KEY, JSON.stringify(list));
            }} catch (e) {{}}
        }}

        function applyRemovedUrlsFilter() {{
            const removed = new Set(getRemovedUrls());
            const elements = document.querySelectorAll('[data-offer-url]');
            elements.forEach((el) => {{
                const url = el.getAttribute('data-offer-url');
                if (url && removed.has(url)) {{
                    el.classList.add('hidden');
                }} else {{
                    el.classList.remove('hidden');
                }}
            }});
            const restoreBtn = document.getElementById('btnRestoreLinksBadge');
            if (restoreBtn) {{
                if (removed.size > 0) {{
                    restoreBtn.classList.remove('hidden');
                    restoreBtn.textContent = `🔄 Réafficher ${{removed.size}} lien(s) supprimé(s)`;
                }} else {{
                    restoreBtn.classList.add('hidden');
                }}
            }}
        }}

        function removeInvalidLink(watchId, url, merchant) {{
            const list = getRemovedUrls();
            if (!list.includes(url)) {{
                list.push(url);
                saveRemovedUrls(list);
            }}
            applyRemovedUrlsFilter();

            const modal = document.getElementById('removeLinkModal');
            const label = document.getElementById('removedMerchantLabel');
            const cmd = document.getElementById('cliRemoveCmd');
            if (label) label.textContent = `${{merchant}} (${{url}})`;
            if (cmd) cmd.textContent = `python3 tracker.py remove-url --watch ${{watchId}} --url "${{url}}"`;
            if (modal) {{
                modal.classList.remove('hidden');
                modal.classList.add('flex');
            }}
        }}

        function closeRemoveModal() {{
            const modal = document.getElementById('removeLinkModal');
            if (modal) {{
                modal.classList.add('hidden');
                modal.classList.remove('flex');
            }}
        }}

        function copyCliCommand() {{
            const cmd = document.getElementById('cliRemoveCmd');
            if (!cmd) return;
            navigator.clipboard.writeText(cmd.textContent).then(() => {{
                showVisualChromeNotification(
                    '📋 Commande copiée !',
                    cmd.textContent,
                    '',
                    'Colle cette commande dans ton terminal pour retirer définitivement l\\'URL de watches.yaml.'
                );
            }}).catch(() => {{}});
        }}

        function restoreRemovedLinks() {{
            saveRemovedUrls([]);
            applyRemovedUrlsFilter();
            closeRemoveModal();
        }}

        function isDarkMode() {{
            return document.documentElement.classList.contains('dark');
        }}

        function updateThemeToggleButton() {{
            const icon = document.getElementById('themeToggleIcon');
            const text = document.getElementById('themeToggleText');
            if (!icon || !text) return;
            if (isDarkMode()) {{
                icon.textContent = '☀️';
                text.textContent = 'Mode Clair';
            }} else {{
                icon.textContent = '🌙';
                text.textContent = 'Dark Mode';
            }}
        }}

        function toggleDarkMode() {{
            const root = document.documentElement;
            if (root.classList.contains('dark')) {{
                root.classList.remove('dark');
                try {{ localStorage.setItem('bf_watch_theme', 'light'); }} catch (e) {{}}
            }} else {{
                root.classList.add('dark');
                try {{ localStorage.setItem('bf_watch_theme', 'dark'); }} catch (e) {{}}
            }}
            updateThemeToggleButton();
            if (currentWatchId) {{
                selectWatchChart(currentWatchId);
            }}
        }}

        function selectWatchChart(watchId) {{
            currentWatchId = watchId;
            const selector = document.getElementById('watchChartSelector');
            if (selector && selector.value !== watchId) {{
                selector.value = watchId;
            }}
            const item = CHART_DATA[watchId];
            if (!item) return;

            const dark = isDarkMode();
            const legendColor = dark ? '#cbd5e1' : '#334155';
            const tickColor = dark ? '#94a3b8' : '#475569';
            const gridColor = dark ? 'rgba(148, 163, 184, 0.12)' : 'rgba(100, 116, 139, 0.16)';

            const ctx = document.getElementById('priceHistoryChart').getContext('2d');
            if (priceChart) {{
                priceChart.destroy();
            }}
            priceChart = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: item.labels,
                    datasets: [
                        {{
                            label: 'Meilleur Prix Relevé (€)',
                            data: item.best_prices,
                            borderColor: dark ? '#34d399' : '#059669',
                            backgroundColor: dark ? 'rgba(52, 211, 153, 0.12)' : 'rgba(5, 150, 105, 0.12)',
                            borderWidth: 3,
                            tension: 0.25,
                            fill: true,
                            pointRadius: 4
                        }},
                        {{
                            label: 'Ton Prix Cible (€)',
                            data: item.target_line,
                            borderColor: dark ? '#fbbf24' : '#d97706',
                            borderWidth: 2,
                            borderDash: [6, 6],
                            pointRadius: 0,
                            fill: false
                        }},
                        {{
                            label: 'Prix Public Officiel MSRP (€)',
                            data: item.msrp_line,
                            borderColor: dark ? '#64748b' : '#94a3b8',
                            borderWidth: 1.5,
                            borderDash: [3, 3],
                            pointRadius: 0,
                            fill: false
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            labels: {{ color: legendColor }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            ticks: {{ color: tickColor }},
                            grid: {{ color: gridColor }}
                        }},
                        y: {{
                            ticks: {{
                                color: tickColor,
                                callback: (v) => v + ' €'
                            }},
                            grid: {{ color: gridColor }}
                        }}
                    }}
                }}
            }});
        }}

        setInterval(async () => {{
            try {{
                const res = await fetch('latest_summary.json?t=' + Date.now());
                if (!res.ok) return;
                const data = await res.json();
                if (data.updated_at && data.updated_at !== lastSeenTimestamp) {{
                    lastSeenTimestamp = data.updated_at;
                    await triggerNativeOrSwNotification(
                        data.notification_title,
                        data.notification_body,
                        data.click_url
                    );
                    window.location.reload();
                }}
            }} catch (e) {{}}
        }}, 15 * 60 * 1000);

        window.addEventListener('DOMContentLoaded', () => {{
            updateThemeToggleButton();
            updateChromePermUI();
            applyRemovedUrlsFilter();
            const firstId = Object.keys(CHART_DATA)[0];
            if (firstId) selectWatchChart(firstId);
        }});
    </script>
</body>
</html>
"""

    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    return index_path
