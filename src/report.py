"""Interactive HTML report generator for GitHub Pages with built-in Chrome Notifications and Chart.js."""

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
    """Generate docs/index.html and docs/latest_summary.json for GitHub Pages and Chrome notifications."""
    os.makedirs(output_dir, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
    now_iso = datetime.now(timezone.utc).isoformat()

    ntfy_topic = settings.get("ntfy_topic", "bf-montres-solaires-2026")
    ntfy_server = settings.get("ntfy_server", "https://ntfy.sh").rstrip("/")
    ntfy_web_url = f"{ntfy_server}/app"

    # Sort analyses by BF Score descending for podium
    sorted_analyses = sorted(analyses, key=lambda a: a.bf_score, reverse=True)
    champion = sorted_analyses[0] if sorted_analyses else None

    # Save latest_summary.json so the open Chrome tab can poll and trigger native Notification API
    latest_payload = {
        "updated_at": now_iso,
        "updated_at_human": now_str,
        "notification_title": summary["title"],
        "notification_body": summary["body"],
        "click_url": summary.get("click_url", ""),
        "ntfy_topic": ntfy_topic,
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

    # Prepare Chart.js datasets per watch
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

    # Build HTML rows for competing watches table
    comparison_rows_html = []
    watch_cards_html = []
    discovered_cards_html = []

    badge_colors = {
        "exceptional": "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
        "target_reached": "bg-green-500/20 text-green-300 border-green-500/40",
        "good": "bg-amber-500/20 text-amber-300 border-amber-500/40",
        "fake_promo": "bg-rose-500/20 text-rose-300 border-rose-500/40",
        "wait": "bg-slate-700/60 text-slate-300 border-slate-600",
    }

    for rank, a in enumerate(sorted_analyses, start=1):
        w = a.watch
        best = a.best_offer
        price_str = f"{best.price:.2f} €" if (best and best.price is not None) else "Indisponible"
        merchant_str = html.escape(best.merchant) if best else "—"
        url_str = html.escape(best.url) if best else "#"
        badge_cls = badge_colors.get(a.bf_verdict_level, badge_colors["wait"])

        diff_target = a.discount_vs_target_diff
        if best and best.price is not None:
            if diff_target <= 0:
                target_badge = f'<span class="text-emerald-400 font-semibold">{diff_target:+.2f} € (Sous la cible !)</span>'
            else:
                target_badge = f'<span class="text-amber-300">+{diff_target:.2f} € vs cible ({w.target_price:.0f} €)</span>'
        else:
            target_badge = "—"

        low_hist_str = f"{a.lowest_historical_price:.2f} €" if a.lowest_historical_price else "—"
        msrp_discount_str = f"-{a.discount_vs_msrp_pct:.0f}%" if a.discount_vs_msrp_pct > 0 else "0%"

        fake_alert_banner = ""
        if a.is_fake_promo and a.fake_promo_reason:
            fake_alert_banner = f"""
            <div class="mt-2 rounded-lg bg-rose-950/70 border border-rose-500/40 px-3 py-2 text-xs text-rose-200 flex items-center gap-2">
                <span>🚨</span>
                <span><strong>Alerte Anti-Fausse Promo :</strong> {html.escape(a.fake_promo_reason)}</span>
            </div>
            """

        comparison_rows_html.append(f"""
        <tr class="border-b border-slate-800 hover:bg-slate-800/50 transition">
            <td class="py-3.5 px-4 font-bold text-amber-400">#{rank}</td>
            <td class="py-3.5 px-4">
                <div class="font-semibold text-white">{html.escape(w.name)}</div>
                <div class="text-xs text-slate-400">Réf: <code class="text-slate-300">{html.escape(w.reference)}</code> • {html.escape(w.features)}</div>
                {fake_alert_banner}
            </td>
            <td class="py-3.5 px-4">
                <div class="text-xl font-extrabold text-white">{price_str}</div>
                <div class="text-xs text-slate-400">Prix public: <span class="line-through">{w.reference_price:.0f} €</span> (<span class="text-emerald-400 font-semibold">{msrp_discount_str}</span>)</div>
            </td>
            <td class="py-3.5 px-4 text-sm">{target_badge}</td>
            <td class="py-3.5 px-4 text-sm text-slate-300">{low_hist_str}</td>
            <td class="py-3.5 px-4">
                <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border {badge_cls}">
                    {html.escape(a.bf_verdict)}
                </span>
            </td>
            <td class="py-3.5 px-4 text-center">
                <div class="inline-flex items-center justify-center w-11 h-11 rounded-full bg-slate-800 border border-slate-700 font-bold text-amber-400">
                    {a.bf_score}
                </div>
            </td>
            <td class="py-3.5 px-4 text-right">
                <a href="{url_str}" target="_blank" rel="noopener"
                   class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs transition shadow">
                   Voir chez {merchant_str} ↗
                </a>
            </td>
        </tr>
        """)

        # Per-watch merchant offers list
        offer_items_html = []
        all_watch_offers = sorted(
            a.offers,
            key=lambda o: (o.price is None, o.price if o.price is not None else 999999),
        )
        for o in all_watch_offers:
            if o.price is not None:
                old_p = f'<span class="line-through text-xs text-slate-500 ml-1">{o.original_price:.2f} €</span>' if o.original_price else ""
                promo_b = f'<span class="ml-2 px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 text-[10px] font-mono">Code: {html.escape(o.promo_code)}</span>' if o.promo_code else ""
                stock_b = '<span class="text-emerald-400 text-xs">● En stock</span>' if o.in_stock else '<span class="text-rose-400 text-xs">● Rupture</span>'
                offer_items_html.append(f"""
                <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-900/70 border border-slate-800/80">
                    <div>
                        <span class="font-medium text-slate-200 text-sm">{html.escape(o.merchant)}</span>
                        <span class="ml-2">{stock_b}</span>
                        {promo_b}
                    </div>
                    <div class="flex items-center gap-3">
                        <div class="text-right">
                            <span class="font-bold text-white">{o.price:.2f} €</span>
                            {old_p}
                        </div>
                        <a href="{html.escape(o.url)}" target="_blank" rel="noopener" class="text-xs px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-amber-300">Lien ↗</a>
                    </div>
                </div>
                """)
            else:
                offer_items_html.append(f"""
                <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-900/40 border border-slate-800/40 opacity-70">
                    <span class="text-sm text-slate-400">{html.escape(o.merchant)}</span>
                    <div class="flex items-center gap-2">
                        <span class="text-xs text-slate-500">{html.escape(o.error or 'Non relevé')}</span>
                        <a href="{html.escape(o.url)}" target="_blank" rel="noopener" class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300">Vérifier ↗</a>
                    </div>
                </div>
                """)

        watch_cards_html.append(f"""
        <div class="rounded-2xl bg-slate-900 border border-slate-800 p-5 flex flex-col justify-between shadow-lg">
            <div>
                <div class="flex items-start justify-between gap-2 mb-3">
                    <div>
                        <span class="text-xs font-bold uppercase tracking-wider text-amber-400">{html.escape(w.brand)} • Réf. {html.escape(w.reference)}</span>
                        <h3 class="text-lg font-bold text-white mt-0.5">{html.escape(w.name)}</h3>
                    </div>
                    <span class="px-2.5 py-1 rounded-full text-xs font-semibold border {badge_cls}">Score {a.bf_score}/100</span>
                </div>
                <p class="text-xs text-slate-400 mb-4">{html.escape(w.features)}</p>
                <div class="grid grid-cols-3 gap-2 mb-4 text-center">
                    <div class="rounded-lg bg-slate-950/70 p-2.5 border border-slate-800">
                        <div class="text-[11px] text-slate-400">Meilleur Prix</div>
                        <div class="text-base font-extrabold text-emerald-400">{price_str}</div>
                    </div>
                    <div class="rounded-lg bg-slate-950/70 p-2.5 border border-slate-800">
                        <div class="text-[11px] text-slate-400">Ton Prix Cible</div>
                        <div class="text-base font-bold text-amber-300">{w.target_price:.0f} €</div>
                    </div>
                    <div class="rounded-lg bg-slate-950/70 p-2.5 border border-slate-800">
                        <div class="text-[11px] text-slate-400">Plus Bas Observé</div>
                        <div class="text-base font-bold text-sky-300">{low_hist_str}</div>
                    </div>
                </div>
                <div class="space-y-2 mb-4">
                    <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">Offres Marchands Surveillées</div>
                    {''.join(offer_items_html)}
                </div>
            </div>
            <div class="pt-3 border-t border-slate-800">
                <button onclick="selectWatchChart('{html.escape(w.id)}')" class="w-full py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-sky-300 transition">
                    📈 Afficher la courbe d'évolution de cette montre
                </button>
            </div>
        </div>
        """)

        for d in a.discovered_offers:
            if d.price is not None:
                temp_badge = f'<span class="px-2 py-0.5 rounded bg-orange-500/20 text-orange-300 text-xs font-bold">🔥 {html.escape(d.temperature)}</span>' if d.temperature else ""
                discovered_cards_html.append(f"""
                <div class="rounded-xl bg-slate-900 border border-slate-800 p-4 flex items-center justify-between gap-4">
                    <div>
                        <div class="flex items-center gap-2">
                            <span class="text-xs font-bold text-amber-400">{html.escape(w.reference)}</span>
                            <span class="text-xs text-slate-400">via {html.escape(d.merchant)}</span>
                            {temp_badge}
                        </div>
                        <div class="text-sm font-semibold text-white mt-1">{html.escape(d.title or w.name)}</div>
                    </div>
                    <div class="flex items-center gap-3 shrink-0">
                        <div class="text-lg font-extrabold text-emerald-400">{d.price:.2f} €</div>
                        <a href="{html.escape(d.url)}" target="_blank" rel="noopener"
                           class="px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs">
                           Voir l'offre ↗
                        </a>
                    </div>
                </div>
                """)

    discovered_section_html = (
        "".join(discovered_cards_html)
        if discovered_cards_html
        else """
        <div class="rounded-xl bg-slate-900/60 border border-slate-800 p-6 text-center text-sm text-slate-400">
            Aucune offre externe supplémentaire découverte sur ce cycle — les offres principales ci-dessus couvrent déjà les meilleurs tarifs trouvés.
        </div>
        """
    )

    champion_banner = ""
    if champion and champion.best_offer and champion.best_offer.price is not None:
        c_w = champion.watch
        c_o = champion.best_offer
        champion_banner = f"""
        <div class="rounded-2xl bg-gradient-to-r from-amber-500/20 via-emerald-500/10 to-slate-900 border border-amber-500/40 p-6 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div>
                <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500 text-slate-950 font-extrabold text-xs uppercase tracking-wider mb-2">
                    🏆 Meilleure Opportunité Black Friday du Jour (Score {champion.bf_score}/100)
                </div>
                <h2 class="text-2xl font-extrabold text-white">{html.escape(c_w.name)}</h2>
                <p class="text-sm text-slate-300 mt-1">
                    En tête de la compétition à <strong class="text-emerald-400 text-lg">{c_o.price:.2f} €</strong> chez <strong>{html.escape(c_o.merchant)}</strong>
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
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans selection:bg-amber-400 selection:text-slate-950">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <!-- Header -->
        <header class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 pb-6 mb-8 border-b border-slate-800">
            <div>
                <div class="flex items-center gap-2 text-amber-400 text-xs font-bold uppercase tracking-widest">
                    <span>⌚ Tough Solar / Eco-Drive • Multi-Band 6 Radio-Controlled</span>
                </div>
                <h1 class="text-3xl sm:text-4xl font-extrabold text-white mt-1">
                    Comparateur Black Friday — Montres Solaires Radio-Pilotées
                </h1>
                <p class="text-sm text-slate-400 mt-1">
                    Dernier relevé automatique : <strong class="text-slate-200">{now_str}</strong> • Anti-fausse promo & récapitulatif quotidien actif
                </p>
            </div>

            <!-- Chrome Notification Controls -->
            <div class="flex flex-wrap items-center gap-3">
                <button id="btnChromeNotif" onclick="enableBrowserNotifications()"
                    class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs shadow transition">
                    🔔 Activer les notifications Chrome (Onglet)
                </button>
                <button onclick="sendTestChromeNotification()"
                    class="inline-flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold text-xs border border-slate-700 transition">
                    🧪 Tester la notif Chrome
                </button>
                <a href="{html.escape(ntfy_web_url)}" target="_blank" rel="noopener"
                    class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 font-semibold text-xs transition"
                    title="Recevoir les notifications Chrome même quand cet onglet est fermé">
                    📲 Web Push Chrome (Canal: {html.escape(ntfy_topic)}) ↗
                </a>
            </div>
        </header>

        <!-- Chrome Notification Setup Helper Box -->
        <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-xs text-slate-300">
            <div class="space-y-1">
                <div class="font-bold text-white flex items-center gap-2">
                    <span>💡 Deux modes de notifications Google Chrome sont prêts :</span>
                    <span id="chromePermStatus" class="px-2 py-0.5 rounded bg-slate-800 text-amber-300">Statut : Non activé</span>
                </div>
                <p>
                    1. <strong>Directement depuis cette page :</strong> clique sur <em>« Activer les notifications Chrome »</em> ci-dessus. La page vérifie automatiquement les nouveaux relevés et affiche une notification Chrome.<br/>
                    2. <strong>Même onglet fermé (Web Push via ntfy.sh) :</strong> ouvre <a href="{html.escape(ntfy_web_url)}" target="_blank" class="text-sky-400 underline">ntfy.sh/app</a> dans Chrome, clique sur <em>« Subscribe to topic »</em> et entre <code class="px-1.5 py-0.5 rounded bg-slate-950 text-amber-300 font-mono">{html.escape(ntfy_topic)}</code>.
                </p>
            </div>
        </div>

        {champion_banner}

        <!-- Podium / Comparison Table -->
        <section class="mb-10">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-bold text-white">🏁 Classement des Modèles en Compétition</h2>
                <span class="text-xs text-slate-400">Trié par Score Black Friday (vraie remise vs prix public & prix cible)</span>
            </div>
            <div class="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/80 shadow-xl">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-400 bg-slate-950/60">
                            <th class="py-3 px-4">Rang</th>
                            <th class="py-3 px-4">Modèle & Caractéristiques</th>
                            <th class="py-3 px-4">Meilleur Prix</th>
                            <th class="py-3 px-4">Écart Cible</th>
                            <th class="py-3 px-4">Plus Bas Hist.</th>
                            <th class="py-3 px-4">Verdict Black Friday</th>
                            <th class="py-3 px-4 text-center">Score BF</th>
                            <th class="py-3 px-4 text-right">Meilleure Offre</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(comparison_rows_html)}
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Price Evolution Chart -->
        <section class="mb-10 rounded-2xl bg-slate-900 border border-slate-800 p-6 shadow-xl">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
                <div>
                    <h2 class="text-xl font-bold text-white">📈 Historique des Prix & Détection des Fausses Promos</h2>
                    <p class="text-xs text-slate-400">Compare le meilleur prix relevé (vert) avec ton prix cible (ambre) et le prix public officiel (gris)</p>
                </div>
                <select id="watchChartSelector" onchange="selectWatchChart(this.value)"
                    class="rounded-xl bg-slate-950 border border-slate-700 px-3.5 py-2 text-sm text-white font-medium">
                    {''.join(f'<option value="{html.escape(a.watch.id)}">{html.escape(a.watch.name)}</option>' for a in sorted_analyses)}
                </select>
            </div>
            <div class="h-72 w-full">
                <canvas id="priceHistoryChart"></canvas>
            </div>
        </section>

        <!-- Detailed Cards per Watch -->
        <section class="mb-10">
            <h2 class="text-xl font-bold text-white mb-4">🔍 Détail des Offres par Montre</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                {''.join(watch_cards_html)}
            </div>
        </section>

        <!-- Auto-Discovered Deals Section -->
        <section class="mb-12">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-bold text-white">🛰️ Nouvelles Offres & Deals Découverts par Référence</h2>
                <span class="text-xs text-slate-400">Recherche automatique Dealabs & comparateurs</span>
            </div>
            <div class="space-y-3">
                {discovered_section_html}
            </div>
        </section>

        <footer class="text-center text-xs text-slate-500 pt-6 border-t border-slate-900">
            Propulsé par GitHub Actions & Python • Configuration dans <code>watches.yaml</code> • Historique versionné dans <code>data/history.json</code>
        </footer>
    </div>

    <script>
        const CHART_DATA = {json.dumps(chart_data_by_watch, ensure_ascii=False)};
        const LATEST_SUMMARY = {json.dumps(latest_payload, ensure_ascii=False)};
        let priceChart = null;
        let lastSeenTimestamp = LATEST_SUMMARY.updated_at;

        function selectWatchChart(watchId) {{
            const selector = document.getElementById('watchChartSelector');
            if (selector && selector.value !== watchId) {{
                selector.value = watchId;
            }}
            const item = CHART_DATA[watchId];
            if (!item) return;

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
                            borderColor: '#34d399',
                            backgroundColor: 'rgba(52, 211, 153, 0.12)',
                            borderWidth: 3,
                            tension: 0.25,
                            fill: true,
                            pointRadius: 4
                        }},
                        {{
                            label: 'Ton Prix Cible (€)',
                            data: item.target_line,
                            borderColor: '#fbbf24',
                            borderWidth: 2,
                            borderDash: [6, 6],
                            pointRadius: 0,
                            fill: false
                        }},
                        {{
                            label: 'Prix Public Officiel MSRP (€)',
                            data: item.msrp_line,
                            borderColor: '#64748b',
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
                            labels: {{ color: '#cbd5e1' }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            ticks: {{ color: '#94a3b8' }},
                            grid: {{ color: 'rgba(148, 163, 184, 0.1)' }}
                        }},
                        y: {{
                            ticks: {{
                                color: '#94a3b8',
                                callback: (v) => v + ' €'
                            }},
                            grid: {{ color: 'rgba(148, 163, 184, 0.1)' }}
                        }}
                    }}
                }}
            }});
        }}

        function updateChromePermUI() {{
            const badge = document.getElementById('chromePermStatus');
            const btn = document.getElementById('btnChromeNotif');
            if (!('Notification' in window)) {{
                badge.textContent = 'Non supporté par ce navigateur';
                return;
            }}
            if (Notification.permission === 'granted') {{
                badge.textContent = '✅ Notifications Chrome actives';
                badge.className = 'px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300';
                btn.textContent = '🔔 Notifications Chrome Activées';
            }} else if (Notification.permission === 'denied') {{
                badge.textContent = '❌ Bloqué dans les paramètres Chrome';
                badge.className = 'px-2 py-0.5 rounded bg-rose-500/20 text-rose-300';
            }}
        }}

        async function enableBrowserNotifications() {{
            if (!('Notification' in window)) {{
                alert('Les notifications web ne sont pas supportées sur ce navigateur.');
                return;
            }}
            const perm = await Notification.requestPermission();
            updateChromePermUI();
            if (perm === 'granted') {{
                sendTestChromeNotification();
            }}
        }}

        function sendTestChromeNotification() {{
            if (!('Notification' in window)) return;
            if (Notification.permission !== 'granted') {{
                enableBrowserNotifications();
                return;
            }}
            const n = new Notification(LATEST_SUMMARY.notification_title, {{
                body: LATEST_SUMMARY.notification_body,
                tag: 'bf-watch-comparator',
            }});
            n.onclick = () => {{
                window.focus();
                if (LATEST_SUMMARY.click_url) {{
                    window.open(LATEST_SUMMARY.click_url, '_blank');
                }}
            }};
        }}

        // Poll latest_summary.json every 15 minutes when tab is kept open in Chrome
        setInterval(async () => {{
            try {{
                const res = await fetch('latest_summary.json?t=' + Date.now());
                if (!res.ok) return;
                const data = await res.json();
                if (data.updated_at && data.updated_at !== lastSeenTimestamp) {{
                    lastSeenTimestamp = data.updated_at;
                    if ('Notification' in window && Notification.permission === 'granted') {{
                        new Notification(data.notification_title, {{
                            body: data.notification_body,
                            tag: 'bf-watch-comparator-update'
                        }});
                    }}
                    window.location.reload();
                }}
            }} catch (e) {{}}
        }}, 15 * 60 * 1000);

        window.addEventListener('DOMContentLoaded', () => {{
            updateChromePermUI();
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
