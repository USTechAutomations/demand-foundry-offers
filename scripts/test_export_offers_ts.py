#!/usr/bin/env python3
"""Byte-level controls for the offers.ts exporter."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_offers_ts as exporter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Copy of usta-react/src/website/pages/offers/data/offers.ts as merged in USTA.
GOLDEN = Path(__file__).with_name("fixtures") / "offers.ts"


class ExportTests(unittest.TestCase):
    def test_repo_index_exports_the_usta_module_byte_for_byte(self):
        self.assertEqual(exporter.export(ROOT / "index.html").encode("utf-8"), GOLDEN.read_bytes())

    def test_parses_eleven_offers_with_every_field(self):
        offers, built = exporter.parse_offers((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(built, "2026-08-05")
        self.assertEqual(len(offers), 11)
        first = offers[0]
        self.assertEqual(first["slug"], "law-firm-client-intake-automation")
        self.assertEqual(first["buyerRole"], "Managing Attorney")
        self.assertEqual(first["organizationType"], "Legal practice handling high-volume client intakes")
        self.assertEqual(first["price"], "$400 one time")
        self.assertEqual(first["deliveryDays"], 7)
        self.assertEqual(len(first["questions"]), 2)

    def test_default_lead_articles_and_casing(self):
        self.assertEqual(
            exporter.default_lead("Clinic Director", "Aesthetic medicine clinic"),
            "For the clinic director of an aesthetic medicine clinic.",
        )
        self.assertEqual(
            exporter.default_lead("Managing Partner", "CPA firm serving small business clients"),
            "For the managing partner of a CPA firm serving small business clients.",
        )
        self.assertEqual(
            exporter.default_lead("Owner or Operations Manager", "Local contractor"),
            "For the owner or operations manager of a local contractor.",
        )

    def test_overrides_replace_generated_copy(self):
        offers, _ = exporter.parse_offers((ROOT / "index.html").read_text(encoding="utf-8"))
        by_slug = {offer["slug"]: offer for offer in offers}
        self.assertEqual(
            by_slug["mortgage-broker-doc-collection-bot"]["lead"],
            exporter.LEAD_OVERRIDES["mortgage-broker-doc-collection-bot"],
        )
        self.assertTrue(by_slug["window-install-lead-response-automation"]["problem"].startswith("You are losing"))
        for offer in offers:
            self.assertEqual(offer["deliverable"], exporter.DELIVERABLE_OVERRIDES[offer["slug"]])
            self.assertLess(len(offer["deliverable"].split()), 13, offer["slug"])
            self.assertFalse(offer["deliverable"].startswith(("Build of", "Setup of", "Implementation of", "Configuration of")))

    def test_every_offer_needs_a_title_override(self):
        saved = dict(exporter.DELIVERABLE_OVERRIDES)
        try:
            exporter.DELIVERABLE_OVERRIDES.pop("law-firm-client-intake-automation")
            with self.assertRaises(ValueError):
                exporter.parse_offers((ROOT / "index.html").read_text(encoding="utf-8"))
        finally:
            exporter.DELIVERABLE_OVERRIDES.update(saved)

    def test_prettier_wrapping_and_quoting(self):
        long_value = "x" * 95
        self.assertEqual(exporter.prop("lead", long_value), f"    lead: '{long_value}',\n")
        self.assertEqual(exporter.prop("problem", long_value), f"    problem:\n      '{long_value}',\n")
        self.assertEqual(exporter.prop("price", "$400 one time"), "    price: '$400 one time',\n")
        self.assertEqual(exporter.ts_string("it's"), '"it\'s"')
        self.assertEqual(exporter.ts_string('say "hi"'), "'say \"hi\"'")

    def test_missing_field_is_refused(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        broken = html.replace('<span class="price">$400 one time</span>', "", 1)
        with self.assertRaises(ValueError):
            exporter.parse_offers(broken)
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "index.html"
            page.write_text(broken, encoding="utf-8")
            self.assertEqual(exporter.main([str(page), "-o", str(Path(tmp) / "out.ts")]), 1)
            self.assertFalse((Path(tmp) / "out.ts").exists())


if __name__ == "__main__":
    unittest.main()
