#!/usr/bin/env python3
"""Check a released catalog against the canonical live offer projection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen


SOURCE = "https://ustechautomations.com/permits/agent-quotable-offers/offers.json"
FIELDS = ("price", "request_url", "offer_url", "not_covered")


def fail(message: str, code: int = 1) -> None:
    print(f"{'UNKNOWN' if code == 2 else 'FAIL'}: {message}", file=sys.stderr)
    raise SystemExit(code)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_catalog_source.py CATALOG_JSON", file=sys.stderr)
        return 2
    try:
        catalog = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        request = Request(SOURCE, headers={"User-Agent": "USTA-catalog-source-check/1.0"})
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                fail(f"canonical source returned HTTP {response.status}", 2)
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            fail("canonical source exceeds 4 MiB", 2)
        source = json.loads(raw)
    except (OSError, ValueError, TypeError) as exc:
        fail(f"source comparison unavailable ({type(exc).__name__})", 2)
    source_rows = source.get("offers")
    catalog_rows = catalog.get("skus")
    if not isinstance(source_rows, list) or not isinstance(catalog_rows, list):
        fail("offer or catalog row list differs")
    try:
        source_by_sku = {row["sku"]: row for row in source_rows}
        catalog_by_sku = {row["sku"]: row for row in catalog_rows}
    except (KeyError, TypeError):
        fail("SKU shape differs")
    if len(source_by_sku) != len(source_rows) or len(catalog_by_sku) != len(catalog_rows):
        fail("duplicate SKU")
    if set(source_by_sku) != set(catalog_by_sku):
        fail("SKU sets differ")
    mismatches = [
        (sku, field)
        for sku in sorted(source_by_sku)
        for field in FIELDS
        if source_by_sku[sku].get(field) != catalog_by_sku[sku].get(field)
    ]
    source_hash = hashlib.sha256(raw).hexdigest()
    recorded_hash = catalog.get("sources", {}).get("offer_catalog", {}).get("sha256")
    if source_hash != recorded_hash:
        fail("live offer-source bytes changed since this release", 2)
    if mismatches:
        fail(f"{len(mismatches)} projected fields differ")
    if not all(isinstance(row.get("request_url"), str) and row["request_url"] for row in catalog_rows):
        fail("a released SKU has no request URL")
    print(
        json.dumps(
            {
                "state": "PASS",
                "offer_rows": len(catalog_rows),
                "fields_compared_per_row": len(FIELDS),
                "field_values_compared": len(catalog_rows) * len(FIELDS),
                "request_urls_present": len(catalog_rows),
                "source_sha256": source_hash,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
