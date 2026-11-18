"""Unit and integration tests for KeepaWatch (Neuf/Occasion dual curves, fee pre-filling, thresholds, suggestions)."""

import os
import shutil
import tempfile
import unittest

from src.models import WatchConfig, WatchURL, OfferResult
from src.scraper import (
    parse_price_string,
    extract_from_html,
    inspect_product_url,
    compute_catawiki_fee_only,
    compute_japan_customs_only,
)
from src.analyzer import analyze_watch_and_update_history
from src.suggest import propose_product_pages
from tracker import (
    run_comparator,
    load_config,
    add_watch_to_config,
    remove_watch_from_config,
    add_url_to_config,
    remove_url_from_config,
    set_watch_thresholds,
)


class TestKeepaWatchComparator(unittest.TestCase):
    def test_parse_price_string_formats(self):
        self.assertEqual(parse_price_string("129,99 €"), 129.99)
        self.assertEqual(parse_price_string("1 249,90 €"), 1249.90)
        self.assertEqual(parse_price_string("94€90"), 94.90)
        self.assertEqual(parse_price_string("Citizen CB1160-55E à 435,89 €"), 435.89)

    def test_inspect_url_prefills_clear_fees_or_leaves_manual(self):
        # 1. Explicit shipping & used condition stated in clear text on page
        html_clear = """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org/",
              "@type": "Product",
              "name": "Seiko Selection SBTM323",
              "offers": {
                "@type": "Offer",
                "priceCurrency": "EUR",
                "price": "278.00",
                "itemCondition": "https://schema.org/UsedCondition"
              }
            }
            </script>
          </head>
          <body>
            <div>État : Occasion</div>
            <div>+ 28 € de frais de port</div>
            <div>Expédié depuis le Japon</div>
          </body>
        </html>
        """
        res = inspect_product_url("https://www.chrono24.fr/seiko/ref-sbtm323.htm", html_str=html_clear)
        self.assertEqual(res["base_price"], 278.00)
        self.assertEqual(res["condition"], "used")
        self.assertTrue(res["shipping_detected"])
        self.assertEqual(res["shipping_fee"], 28.00)
        self.assertTrue(res["site_fee_detected"])
        self.assertEqual(res["site_fee"], 0.0)
        self.assertTrue(res["customs_detected"])
        # (278 + 28 + 0.80) * 0.20 + 0.80 + 18 = 61.36 + 0.80 + 18 = 80.16
        self.assertEqual(res["customs_fee"], 80.16)

        # 2. Unknown boutique with NO shipping/site/customs stated in clear text -> leaves None for user input
        html_unknown = """
        <html>
          <head><meta property="product:price:amount" content="350.00" /></head>
          <body><h1>Montre Solaire Rare</h1></body>
        </html>
        """
        res_unknown = inspect_product_url("https://boutique-inconnue-exemple.org/montre-1", html_str=html_unknown)
        self.assertEqual(res_unknown["base_price"], 350.00)
        self.assertFalse(res_unknown["shipping_detected"])
        self.assertIsNone(res_unknown["shipping_fee"])
        self.assertFalse(res_unknown["site_fee_detected"])
        self.assertIsNone(res_unknown["site_fee"])
        self.assertFalse(res_unknown["customs_detected"])
        self.assertIsNone(res_unknown["customs_fee"])

    def test_catawiki_and_sakura_fee_formulas(self):
        self.assertEqual(compute_catawiki_fee_only(400.0), 39.0)
        # Sakura 312 € HT + 24 € DHL -> customs = (312+24+0.80)*0.20 + 0.80 + 18 = 86.16? Wait: 336.8*0.2=67.36 + 0.8 + 18 = 86.16
        self.assertEqual(compute_japan_customs_only(312.0, shipping_eur=24.0), 86.16)

    def test_dual_curve_history_and_separate_thresholds(self):
        watch = WatchConfig(
            id="citizen-cb1160-55e",
            name="Citizen CB1160-55E",
            brand="Citizen",
            reference="CB1160-55E",
            features="Super Titanium",
            target_price_new=430.0,
            target_price_used=350.0,
            reference_price=549.0,
        )
        offers = [
            OfferResult(
                watch_id="citizen-cb1160-55e",
                merchant="Sakura Watches (Tokyo)",
                url="https://www.sakurawatches.com/citizen-collection-cb1160-55e-15415",
                price=422.16,
                base_price=312.0,
                condition="new",
                shipping_fee=24.0,
                site_fee=0.0,
                customs_fee=86.16,
            ),
            OfferResult(
                watch_id="citizen-cb1160-55e",
                merchant="Chrono24 (UE)",
                url="https://www.chrono24.fr/search/index.htm?query=CB1160-55E&usedOrNew=used",
                price=339.0,
                base_price=325.0,
                condition="used",
                shipping_fee=14.0,
                site_fee=0.0,
                customs_fee=0.0,
            ),
        ]
        history = {"updated_at": None, "watches": {}}
        analysis = analyze_watch_and_update_history(watch, offers, history)
        self.assertIsNotNone(analysis.best_new_offer)
        self.assertEqual(analysis.best_new_offer.price, 422.16)
        self.assertIsNotNone(analysis.best_used_offer)
        self.assertEqual(analysis.best_used_offer.price, 339.0)
        self.assertTrue(analysis.alert_new_triggered)
        self.assertTrue(analysis.alert_used_triggered)
        self.assertEqual(len(history["watches"]["citizen-cb1160-55e"]["entries"]), 1)

    def test_on_demand_suggestions_never_modify_watch_urls(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _, watches = load_config(os.path.join(base_dir, "watches.yaml"))
        w = watches[0]
        before_count = len(w.urls)
        suggestions = propose_product_pages(w, live_fetch=False)
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(len(w.urls), before_count)

    def test_cli_crud_and_end_to_end_html_generation(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src_cfg = os.path.join(base_dir, "watches.yaml")

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_copy = os.path.join(tmpdir, "watches.yaml")
            shutil.copyfile(src_cfg, cfg_copy)
            hist_path = os.path.join(tmpdir, "data", "history.json")
            docs_dir = os.path.join(tmpdir, "docs")

            # Add & remove watch
            new_id = add_watch_to_config(
                config_path=cfg_copy,
                brand="Casio",
                name="Casio Oceanus OCW-T200S-1AJF",
                reference="OCW-T200S-1AJF",
                target_price_new=380.0,
                target_price_used=280.0,
            )
            add_url_to_config(
                config_path=cfg_copy,
                watch_id=new_id,
                url="https://www.sakurawatches.com/casio-oceanus-ocw-t200s-1ajf",
                condition="new",
                manual_price=290.0,
                shipping_fee=24.0,
                site_fee=0.0,
                customs_fee=81.76,
                auto_inspect=False,
            )
            set_watch_thresholds(cfg_copy, new_id, 400.0, 275.0)
            self.assertTrue(
                remove_url_from_config(
                    cfg_copy,
                    "https://www.sakurawatches.com/casio-oceanus-ocw-t200s-1ajf",
                    new_id,
                )
            )
            self.assertTrue(remove_watch_from_config(cfg_copy, new_id))

            # Full pipeline run
            analyses = run_comparator(
                config_path=cfg_copy,
                history_path=hist_path,
                docs_dir=docs_dir,
                demo_mode=True,
                no_notify=True,
            )
            self.assertEqual(len(analyses), 9)
            index_html = os.path.join(docs_dir, "index.html")
            self.assertTrue(os.path.exists(index_html))
            with open(index_html, "r", encoding="utf-8") as f:
                html = f.read()
            self.assertIn("KeepaWatch", html)
            self.assertIn("CB1160-55E", html)
            self.assertIn("Proposer des pages produit", html)
            self.assertIn("Frais de douane", html)


if __name__ == "__main__":
    unittest.main()
