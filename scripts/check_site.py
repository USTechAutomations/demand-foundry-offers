#!/usr/bin/env python3
"""Fail closed on broken certificate navigation or sitemap membership."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CERT = ROOT / "certificates/cand-467-question-seal"
CANONICAL = "https://ustechautomations.com/offers/certificates/cand-467-question-seal/"

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.hrefs = set()
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            value = dict(attrs).get("href")
            if value: self.hrefs.add(value)

def fail(message):
    print(f"FAIL: {message}", file=sys.stderr); raise SystemExit(1)

required = ("index.html", "certificate.json", "payload.json", "signature.bin", "public-key.pem", "verify_certificate.py")
for name in required:
    if not (CERT / name).is_file() or (CERT / name).stat().st_size == 0: fail(f"missing or empty {name}")

page = (CERT / "index.html").read_text(encoding="utf-8")
for marker in ("$249", "Ed25519", "How to verify", "Request the $249 verification certificate"):
    if marker not in page: fail(f"certificate page lacks {marker!r}")

links = Links(); links.feed((ROOT / "certificates/index.html").read_text(encoding="utf-8"))
if "cand-467-question-seal/" not in links.hrefs: fail("certificate index does not link the certificate")

tree = ET.parse(ROOT / "sitemap.xml")
locs = {node.text for node in tree.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")}
if CANONICAL not in locs: fail("certificate canonical absent from sitemap")
print(f"PASS: {len(required)} certificate files, buyer/price/CTA/verification markers, navigation, and sitemap")
