#!/usr/bin/env python3
"""Idempotently attach the generated estate catalog to offers discovery."""

from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SITEMAP = ROOT / "sitemap.xml"
CANONICAL = "https://ustechautomations.com/offers/catalog/"
LINK = (
    ' The <a href="https://ustechautomations.com/offers/catalog/">signed sealed-estate '
    "catalog</a> names every counted clock, held range, cadence, health state and "
    "coverage gap, then carries each canonical offer's price and request path without "
    "calling every offer machine-purchasable."
)
ANCHOR = (
    "The companion <a href=\"https://ustechautomations.com/offers/charter/\">"
    "forward-provenance charter</a> publishes the rail's guarantee, its checkpoint "
    "exemption and every counted legacy gap."
)


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def update_index() -> None:
    text = INDEX.read_text(encoding="utf-8")
    if CANONICAL in text:
        return
    if text.count(ANCHOR) != 1:
        fail("generated offers index anchor differs")
    INDEX.write_text(text.replace(ANCHOR, ANCHOR + LINK), encoding="utf-8")


def update_sitemap() -> None:
    tree = ET.parse(SITEMAP)
    root = tree.getroot()
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    locs = {
        node.text
        for node in root.findall(f"{{{namespace}}}url/{{{namespace}}}loc")
    }
    if CANONICAL not in locs:
        url = ET.SubElement(root, f"{{{namespace}}}url")
        ET.SubElement(url, f"{{{namespace}}}loc").text = CANONICAL
    ET.register_namespace("", namespace)
    ET.indent(tree, space="  ")
    tree.write(SITEMAP, encoding="utf-8", xml_declaration=True)
    with SITEMAP.open("a", encoding="utf-8") as handle:
        handle.write("\n")


def main() -> int:
    update_index()
    update_sitemap()
    print("PASS: catalog linked from offers root and sitemap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
