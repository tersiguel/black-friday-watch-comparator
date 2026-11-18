"""Unit and integration tests for the Black Friday Watch Price Comparator (runnable via unittest or pytest)."""

import os
import shutil
import tempfile
import unittest

from src.models import WatchConfig, OfferResult
from src.scraper import (
    parse_price_string,
    extract_from_html,
    compute_catawiki_price_with_fees,
    compute_japan_import_price,
    is_non_eu_import_url,
)
from src.discovery import parse_dealabs_html_or_rss, parse_catawiki_html
from src.analyzer import (
    detect_fake_promo,
    compute_bf_score_and_verdict,
)
from tracker import (
    run_comparator,
    remove_url_from_config,
    add_watch_to_config,
    remove_watch_from_config,
    load_config,
    DEFAULT_CONFIG_PATH,
)


class TestBlackFridayWatchComparator(unittest.TestCase):
    def test_parse_price_string_formats(self):
        self.assertEqual(parse_price_string("94,90 €"), 94.90)
        self.assertEqual(parse_price_string("1 249,00 €"), 1249.00)
        self.assertEqual(parse_price_string("129€90"), 129.90)
        self.assertEqual(parse_price_string("EUR 184.50"), 184.50)
        self.assertEqual(parse_price_string(264), 264.0)

    def test_extract_from_json_ld_and_selector_enrichment(self):
        sample_html = """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org/",
              "@type": "Product",
              "name": "Casio G-Shock GW-M5610U-1ER",
              "offers": {
                "@type": "Offer",
                "priceCurrency": "EUR",
                "price": "99.90",
                "availability": "https://schema.org/InStock"
              }
            }
            </script>
          </head>
          <body>
            <span class="regular-price">149,00 €</span>
            <p>Profitez de -10% supplémentaires avec le code BFWATCH10 dès maintenant !</p>
          </body>
        </html>
        """
        res = extract_from_html(sample_html, "https://ocarat.com/montre-casio.html")
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["price"], 99.90)
        self.assertEqual(res["original_price"], 149.00)
        self.assertEqual(res["promo_code"], "BFWATCH10")
        self.assertTrue(res["in_stock"])
        self.assertEqual(res["method"], "json-ld")

    def test_fake_promo_detection_and_bf_score(self):
        watch = WatchConfig(
            id="citizen-test",
            name="Citizen Promaster AT8110-61E",
            brand="Citizen",
            reference="AT8110-61E",
            features="Eco-Drive Radio-Controlled",
            target_price=319.0,
            reference_price=459.0,
        )
        fake_offer = OfferResult(
            watch_id="citizen-test",
            merchant="Amazon FR",
            url="https://www.amazon.fr/dp/B00WG04A1M",
            price=349.0,
            original_price=529.0,
        )
        is_fake, reason = detect_fake_promo(fake_offer, watch, lowest_historical=329.0)
        self.assertTrue(is_fake)
        self.assertIn("gonflé", reason or "")

        score_fake, verdict_fake, level_fake = compute_bf_score_and_verdict(
            349.0, watch, lowest_historical=329.0, is_fake_promo=True
        )
        self.assertEqual(level_fake, "fake_promo")
        self.assertIn("Fausse Promo", verdict_fake)

        score_good, verdict_good, level_good = compute_bf_score_and_verdict(
            289.0, watch, lowest_historical=315.0, is_fake_promo=False
        )
        self.assertGreaterEqual(score_good, 80)
        self.assertIn(level_good, ("exceptional", "target_reached"))

    def test_dealabs_discovery_parsing(self):
        watch = WatchConfig(
            id="casio-gwm5610u",
            name="Casio G-Shock GW-M5610U-1ER",
            brand="Casio",
            reference="GW-M5610U-1ER",
            features="Tough Solar",
            target_price=99.0,
            reference_price=149.0,
        )
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Montre Casio G-Shock GW-M5610U-1ER Solaire Radio-Pilotée à 89,99 €</title>
              <link>https://www.dealabs.com/bons-plans/casio-gw-m5610u-12345</link>
              <description>Super promo Black Friday à 89,99 € au lieu de 149 €</description>
            </item>
          </channel>
        </rss>
        """
        deals = parse_dealabs_html_or_rss(rss_xml, watch)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0].price, 89.99)
        self.assertTrue(deals[0].is_discovered)

    def test_catawiki_discovery_and_buyer_fees(self):
        self.assertEqual(compute_catawiki_price_with_fees(400.0), 439.0)
        watch = WatchConfig(
            id="junghans-max-bill-mega-solar",
            name="Junghans Max Bill MEGA Solar",
            brand="Junghans",
            reference="059/2020.04",
            features="Titane Saphir",
            target_price=799.0,
            reference_price=1090.0,
        )
        sample_catawiki = """
        <div>
          <article class="c-lot-card">
            <a href="/fr/l/106104294-junghans-max-bill-mega-solar">
              <h3 class="c-lot-card__title">Junghans - Max Bill MEGA Solar - 059.2021.02</h3>
              <div class="c-lot-card__price">400 €</div>
            </a>
          </article>
        </div>
        """
        lots = parse_catawiki_html(sample_catawiki, watch)
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].price, 439.0)
        self.assertIn("9% + 3€", lots[0].shipping_note or "")

    def test_japan_import_customs_and_shipping(self):
        self.assertTrue(is_non_eu_import_url("https://www.sakurawatches.com/seiko-selection-sbtm323"))
        self.assertFalse(is_non_eu_import_url("https://ocarat.com/montre-seiko.html"))

        # 272€ HT + 24€ DHL + 0.80€ duty + 20% VAT on (272 + 24 + 0.80) [= 59.36€] + 18€ DHL fee = 374.16€
        total_ttc, note = compute_japan_import_price(272.0)
        self.assertEqual(total_ttc, 374.16)
        self.assertIn("Prix HT Tokyo 272 €", note)
        self.assertIn("port DHL", note)
        self.assertIn("TVA/douane (20%)", note)

    def test_remove_invalid_url_from_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_copy = os.path.join(tmpdir, "watches.yaml")
            shutil.copyfile(DEFAULT_CONFIG_PATH, cfg_copy)

            _, initial_watches = load_config(cfg_copy)
            first_watch = initial_watches[0]
            target_url = first_watch.urls[0].url

            removed = remove_url_from_config(target_url, watch_id=first_watch.id, config_path=cfg_copy)
            self.assertTrue(removed)

            _, watches = load_config(cfg_copy)
            updated = next(w for w in watches if w.id == first_watch.id)
            remaining_urls = [u.url for u in updated.urls]
            self.assertNotIn(target_url, remaining_urls)

    def test_add_and_remove_watch_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_copy = os.path.join(tmpdir, "watches.yaml")
            shutil.copyfile(DEFAULT_CONFIG_PATH, cfg_copy)
            _, before = load_config(cfg_copy)

            added = add_watch_to_config(
                name="Casio Oceanus OCW-T200S-1AJF",
                brand="Casio",
                reference="OCW-T200S-1AJF",
                target_price=349.0,
                reference_price=499.0,
                url="https://www.sakurawatches.com/casio-oceanus-ocw-t200s-1ajf",
                config_path=cfg_copy,
            )
            self.assertTrue(added)
            _, watches = load_config(cfg_copy)
            self.assertEqual(len(watches), len(before) + 1)

            removed = remove_watch_from_config("OCW-T200S-1AJF", config_path=cfg_copy)
            self.assertTrue(removed)
            _, watches_after = load_config(cfg_copy)
            self.assertEqual(len(watches_after), len(before))

    def test_end_to_end_demo_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_path = os.path.join(tmpdir, "history.json")
            docs_dir = os.path.join(tmpdir, "docs")
            _, configured = load_config(DEFAULT_CONFIG_PATH)
            analyses = run_comparator(
                history_path=hist_path,
                docs_dir=docs_dir,
                demo_mode=True,
                no_notify=True,
            )
            self.assertEqual(len(analyses), len(configured))
            self.assertTrue(os.path.isfile(os.path.join(docs_dir, "index.html")))
            self.assertTrue(os.path.isfile(os.path.join(docs_dir, "sw.js")))
            self.assertTrue(os.path.isfile(os.path.join(docs_dir, "latest_summary.json")))
            self.assertTrue(os.path.isfile(hist_path))


if __name__ == "__main__":
    unittest.main()
