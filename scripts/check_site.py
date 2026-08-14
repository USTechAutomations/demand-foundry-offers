#!/usr/bin/env python3
"""Fail closed on broken public-proof navigation or sitemap membership."""
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CERT = ROOT / "certificates/cand-467-question-seal"
CHARTER = ROOT / "charter"
CATALOG = ROOT / "catalog"
ORDER = ROOT / "verification-certificate"
CANONICAL = "https://ustechautomations.com/offers/certificates/cand-467-question-seal/"
CHARTER_CANONICAL = "https://ustechautomations.com/offers/charter/"
CATALOG_CANONICAL = "https://ustechautomations.com/offers/catalog/"
ORDER_CANONICAL = "https://ustechautomations.com/offers/verification-certificate/"

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
for name in ("index.html", "rail-snapshot.json", "recorder-policy.json", "rederive.py"):
    if not (CHARTER / name).is_file() or (CHARTER / name).stat().st_size == 0: fail(f"missing or empty charter/{name}")
for name in ("index.html", "catalog.json", "public-key.pem", "verify_catalog.py"):
    if not (CATALOG / name).is_file() or (CATALOG / name).stat().st_size == 0: fail(f"missing or empty catalog/{name}")
if not (ORDER / "index.html").is_file() or (ORDER / "index.html").stat().st_size == 0: fail("missing or empty verification-certificate/index.html")

page = (CERT / "index.html").read_text(encoding="utf-8")
for marker in ("$249", "Ed25519", "How to verify", "Request the $249 verification certificate"):
    if marker not in page: fail(f"certificate page lacks {marker!r}")
if CHARTER_CANONICAL not in page: fail("certificate page does not link the provenance charter")
if ORDER_CANONICAL not in page: fail("certificate page does not link the dedicated order path")

links = Links(); links.feed((ROOT / "certificates/index.html").read_text(encoding="utf-8"))
if "cand-467-question-seal/" not in links.hrefs: fail("certificate index does not link the certificate")

tree = ET.parse(ROOT / "sitemap.xml")
locs = {node.text for node in tree.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")}
if CANONICAL not in locs: fail("certificate canonical absent from sitemap")
if CHARTER_CANONICAL not in locs: fail("charter canonical absent from sitemap")
if CATALOG_CANONICAL not in locs: fail("catalog canonical absent from sitemap")
if ORDER_CANONICAL not in locs: fail("verification-certificate order path absent from sitemap")
root_links = Links(); root_links.feed((ROOT / "index.html").read_text(encoding="utf-8"))
if not {CHARTER_CANONICAL, CATALOG_CANONICAL, "https://ustechautomations.com/offers/certificates/"}.issubset(root_links.hrefs): fail("offers root does not link all trust surfaces")
charter_page = (CHARTER / "index.html").read_text(encoding="utf-8")
for marker in ("The guarantee", "The exemption, stated plainly", "Recount it yourself", "$249"):
    if marker not in charter_page: fail(f"charter page lacks {marker!r}")
catalog_page = (CATALOG / "index.html").read_text(encoding="utf-8")
for marker in ("Signed catalog of what we hold", "UNKNOWN", "NOT-COVERED", "machine-purchasable", "Download verifier"):
    if marker not in catalog_page: fail(f"catalog page lacks {marker!r}")
try:
    catalog = json.loads((CATALOG / "catalog.json").read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    fail(f"catalog JSON unreadable: {type(exc).__name__}")
if catalog.get("clock_summary", {}).get("total") != 49: fail("catalog denominator is not 49 clocks")
if catalog.get("clock_summary", {}).get("health", {}).get("UNKNOWN", 0) < 1: fail("catalog suppresses UNKNOWN clocks")
offers_total = catalog.get("offer_summary", {}).get("offers_total")
machine_candidates = catalog.get("offer_summary", {}).get("machine_sku_candidates")
if offers_total != len(catalog.get("skus", [])): fail("catalog offer summary differs from SKU rows")
if offers_total == machine_candidates: fail("catalog conflates human offers with machine candidates")
if not all(row.get("request_url") for row in catalog.get("skus", [])): fail("catalog SKU lacks canonical request URL")
verification = subprocess.run(
    [sys.executable, str(CATALOG / "verify_catalog.py"), str(CATALOG / "catalog.json")],
    capture_output=True,
    text=True,
    timeout=10,
)
if verification.returncode != 0 or not verification.stdout.startswith("VALID "):
    fail("catalog Ed25519 verifier did not validate the published JSON")
with tempfile.TemporaryDirectory(prefix="cand494-tamper-") as temp_name:
    temp = Path(temp_name)
    tampered = json.loads((CATALOG / "catalog.json").read_text(encoding="utf-8"))
    tampered["clock_summary"]["total"] += 1
    tampered_path = temp / "catalog.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    tampered_verification = subprocess.run(
        [sys.executable, str(CATALOG / "verify_catalog.py"), str(tampered_path), str(CATALOG / "public-key.pem")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if tampered_verification.returncode == 0: fail("catalog verifier accepted a changed denominator")
order_page = (ORDER / "index.html").read_text(encoding="utf-8")
for marker in ("$249", "one signed HTML and JSON verification certificate", "within two business days", "Cancel before generation begins", "https://api.ustechautomations.com/api/partnership/submit", "partnership_form", "[Interest: Verification certificate]"):
    if marker not in order_page: fail(f"order page lacks {marker!r}")
for html_path in ROOT.rglob("*.html"):
    if "partner?interest=verification-certificate" in html_path.read_text(encoding="utf-8"):
        fail(f"stale generic certificate CTA remains in {html_path.relative_to(ROOT)}")
print(f"PASS: {len(required)} certificate files, 4 charter files, 4 catalog files, attributed order form, signatures, truthful counts, navigation, and sitemap")
