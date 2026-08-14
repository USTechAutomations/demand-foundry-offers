#!/usr/bin/env python3
"""Deterministic controls for the privacy-safe catalog fetch counter."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).with_name("catalog_fetch_counter.py")
spec = importlib.util.spec_from_file_location("catalog_fetch_counter", SCRIPT)
if spec is None or spec.loader is None:
    raise SystemExit("FAIL: counter module cannot be loaded")
counter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(counter)


def row(path: str, ua: str | None, remote_ip: str, status: int = 200) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "httpRequest": {
            "requestUrl": path,
            "userAgent": ua,
            "remoteIp": remote_ip,
            "status": status,
        },
    }


def expect_unknown(rows: object, *, source_observed: bool) -> None:
    try:
        checked = counter.validate_rows(rows)
        counter.count_rows(checked, source_observed=source_observed)
    except counter.Unknown:
        return
    raise AssertionError("expected UNKNOWN")


def main() -> int:
    rows = [
        row("https://ustechautomations.com/offers/catalog/", "USTA-probe/1.0", "203.0.113.1"),
        # Same address as a derived first-party probe: exclude even with browser UA.
        row("/offers/catalog/catalog.json", "Mozilla/5.0 Browser", "203.0.113.1"),
        row("/offers/catalog/", "ExampleCrawler/1.0", "203.0.113.2"),
        row("/offers/catalog/", "Mozilla/5.0 Browser", "203.0.113.3"),
        row("/.well-known/agent-card.json", "Mozilla/5.0 Browser", "203.0.113.4", 304),
        row("/offers/catalog/", "curl/8.0", "203.0.113.5"),
        row("/offers/catalog/", None, "203.0.113.8"),
        row("/offers/catalog/", "Mozilla/5.0 Browser", "203.0.113.6", 503),
        row("/unrelated", "Mozilla/5.0 Browser", "203.0.113.7"),
    ]
    result = counter.count_rows(counter.validate_rows(rows), source_observed=True)
    assert result["state"] == "COUNTED"
    assert result["value"] == 2
    assert result["scope"] == {
        "catalog_external": 1,
        "discovery_external": 1,
        "self_excluded": 2,
        "bots_excluded": 1,
        "unknown_clients_excluded": 2,
    }
    assert result["successful_scoped_rows"] == 7
    assert result["raw_identifiers_emitted"] == 0

    expect_unknown([], source_observed=False)
    expect_unknown([{"timestamp": "not-a-time", "httpRequest": {}}], source_observed=True)
    expect_unknown("not-an-array", source_observed=True)
    print("PASS: external, self-associated, bot, unknown, HTTP-failure, and source-UNKNOWN controls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
