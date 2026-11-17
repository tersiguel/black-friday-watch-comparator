"""Unit and integration tests for the Black Friday Watch Price Comparator (runnable via unittest or pytest)."""

import os
import tempfile
import unittest

from src.models import WatchConfig, OfferResult
from src.scraper import parse_price_string, extract_from_html
from src.discovery import parse_dealabs_html_or_rss
from src.analyzer import (
    detect_fake_promo,
    compute_bf_score_and_verdict,
)
from tracker import run_comparator


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

    def test_end_to_end_demo_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_path = os.path.join(tmpdir, "history.json")
            docs_dir = os.path.join(tmpdir, "docs")
            analyses = run_comparator(
                history_path=hist_path,
                docs_dir=docs_dir,
                demo_mode=True,
                no_notify=True,
            )
            self.assertEqual(len(analyses), 5)
            self.assertTrue(os.path.isfile(os.path.join(docs_dir, "index.html")))
            self.assertTrue(os.path.isfile(os.path.join(docs_dir, "latest_summary.json")))
            self.assertTrue(os.path.isfile(hist_path))


if __name__ == "__main__":
    unittest.main()
