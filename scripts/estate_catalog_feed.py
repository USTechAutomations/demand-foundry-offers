#!/usr/bin/env python3
"""Derive a signed sealed-estate catalog without hand-kept clock rows.

Production joins the generated revenue-surface estate universe to the generated
collector census, opens every named clock DB with SQLite ``mode=ro`` and
``query_only``, and projects prices/request URLs verbatim from the canonical
offer feed.  An absent or unreadable per-clock DB remains in the denominator as
UNKNOWN.  A whole-universe input failure emits no catalog and exits 2.

The pinned cand-494 grader uses ``--signing-key-file`` and checks a deterministic
HMAC fixture.  The public build uses ``--ephemeral-ed25519`` so anyone can verify
the catalog without receiving a shared secret.  The public key is release-local
and unanchored; HTTPS/Git history supplies distribution provenance, not the key.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import hmac
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any
from urllib.parse import quote, urlsplit
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCHEMA = "usta.estate-catalog.v1"
PUBLIC_CANONICAL = "https://ustechautomations.com/offers/catalog/"
OFFER_FEED_CANONICAL = (
    "https://ustechautomations.com/permits/agent-quotable-offers/offers.json"
)
RAW_RELEASE_BASE = (
    "https://raw.githubusercontent.com/USTechAutomations/"
    "demand-foundry-offers/main/catalog/"
)
EXCLUDED_TABLES = frozenset({"collection_runs", "blobs", "raw_fetches"})
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SURFACE_HEADER = "| Clock | Rows | Productized as |"


class Unknown(Exception):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json_file(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise Unknown(f"{label} unreadable: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise Unknown(f"{label} is not a JSON object")
    return value, raw


def load_offer_url(url: str) -> tuple[dict[str, Any], bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise Unknown("offer URL must be public HTTPS")
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if host in {"localhost", "localhost.localdomain"} or (
        address is not None
        and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        )
    ):
        raise Unknown("offer URL is not a public host")
    request = urllib.request.Request(
        url, headers={"User-Agent": "USTA-estate-catalog-builder/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise Unknown(f"offer URL returned HTTP {response.status}")
            raw = response.read(4 * 1024 * 1024 + 1)
    except (OSError, ValueError) as exc:
        raise Unknown(f"offer URL unreadable: {type(exc).__name__}") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise Unknown("offer URL exceeds 4 MiB")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise Unknown("offer URL is not JSON") from exc
    if not isinstance(value, dict):
        raise Unknown("offer URL is not a JSON object")
    return value, raw


def parse_surface_universe(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise Unknown(f"surface census unreadable: {type(exc).__name__}") from exc
    lines = text.splitlines()
    try:
        header_index = lines.index(SURFACE_HEADER)
    except ValueError as exc:
        raise Unknown("surface census lacks the clock estate table") from exc
    generated_at = None
    for line in lines[:12]:
        match = re.search(r"Generated\s+([0-9-]+\s+[0-9:]+Z)", line)
        if match:
            generated_at = match.group(1).replace(" ", "T")
            break
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) != 3:
            raise Unknown("surface census clock row shape differs")
        clock, rows_text, productized = parts
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]{1,63}", clock):
            raise Unknown("surface census clock identifier differs")
        if clock in seen:
            raise Unknown("surface census repeats a clock")
        seen.add(clock)
        if rows_text == "no-db":
            observed_rows = None
            db_expected = False
        else:
            try:
                observed_rows = int(rows_text.replace(",", ""))
            except ValueError as exc:
                raise Unknown("surface census row count differs") from exc
            if observed_rows < 0:
                raise Unknown("surface census row count is negative")
            db_expected = True
        rows.append(
            {
                "clock": clock,
                "surface_observed_rows": observed_rows,
                "db_expected": db_expected,
                "productized_as": None if productized == "—" else productized,
            }
        )
    if not rows:
        raise Unknown("surface census clock universe is empty")
    return rows, {
        "name": "REVENUE_SURFACES.md",
        "sha256": sha256_bytes(raw),
        "generated_at": generated_at,
        "clock_rows": len(rows),
    }


def census_rows(census: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], str]:
    rows = census.get("collectors")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise Unknown("collector census rows are unreadable")
    by_clock: dict[str, dict[str, Any]] = {}
    for row in rows:
        clock = row.get("clock")
        if not isinstance(clock, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_]{1,63}", clock
        ):
            raise Unknown("collector census has an invalid clock identifier")
        if clock in by_clock:
            raise Unknown("collector census repeats a clock")
        by_clock[clock] = row
    checked_at = census.get("checked_at")
    if not isinstance(checked_at, str) or not checked_at:
        raise Unknown("collector census has no checked_at")
    return by_clock, checked_at


def merge_universe(
    census: dict[str, Any], surfaces_path: Path | None
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    by_clock, checked_at = census_rows(census)
    if surfaces_path is None:
        rows = [
            {
                "clock": clock,
                "surface_observed_rows": row.get("payload_rows"),
                "db_expected": row.get("payload_rows") is not None,
                "productized_as": row.get("product"),
            }
            for clock, row in sorted(by_clock.items())
        ]
        surface_meta = {
            "name": None,
            "sha256": None,
            "generated_at": None,
            "clock_rows": len(rows),
        }
    else:
        rows, surface_meta = parse_surface_universe(surfaces_path)
        surface_names = {row["clock"] for row in rows}
        # A generated collector row absent from the broader generated estate is
        # a denominator disagreement, not permission to drop the clock.
        for clock in sorted(set(by_clock) - surface_names):
            source = by_clock[clock]
            rows.append(
                {
                    "clock": clock,
                    "surface_observed_rows": source.get("payload_rows"),
                    "db_expected": source.get("payload_rows") is not None,
                    "productized_as": source.get("product"),
                }
            )
        rows.sort(key=lambda row: row["clock"])
    return rows, surface_meta, checked_at


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ro_uri(path: Path) -> str:
    return f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"


def read_clock(
    clocks_root: Path,
    universe_row: dict[str, Any],
    census_row: dict[str, Any] | None,
    *,
    query_budget_seconds: float = 20.0,
) -> dict[str, Any]:
    clock = universe_row["clock"]
    db = clocks_root / clock / "data" / f"{clock}.db"
    cadence = (census_row or {}).get("cadence")
    base: dict[str, Any] = {
        "clock": clock,
        "health": "UNKNOWN",
        "payload_rows": None,
        "held_range": None,
        "tables": None,
        "cadence": cadence if isinstance(cadence, str) and cadence else "UNKNOWN",
        "collector_disposition": (census_row or {}).get("disposition") or "UNKNOWN",
        "write_freshness": (census_row or {}).get("write_freshness") or "UNKNOWN",
        "productized_as": universe_row.get("productized_as"),
        "census_alignment": "UNKNOWN",
        "issues": list((census_row or {}).get("issues") or []),
    }
    if not db.is_file():
        base["issues"] = sorted(set([*base["issues"], "canonical DB absent"]))
        return base
    started = time.monotonic()
    try:
        conn = sqlite3.connect(ro_uri(db), uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise sqlite3.OperationalError("query_only did not engage")

        def deadline() -> int:
            return 1 if time.monotonic() - started > query_budget_seconds else 0

        conn.set_progress_handler(deadline, 10_000)
        conn.execute("BEGIN")
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if row[0] not in EXCLUDED_TABLES and not row[0].startswith("sqlite_")
        ]
        counts: dict[str, int] = {}
        date_mins: list[str] = []
        date_maxs: list[str] = []
        for table in tables:
            quoted = quote_identifier(table)
            counts[table] = int(
                conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            )
            columns = {
                row[1] for row in conn.execute(f"PRAGMA table_info({quoted})")
            }
            if "snapshot_date" in columns:
                low, high = conn.execute(
                    f"SELECT MIN(snapshot_date),MAX(snapshot_date) FROM {quoted}"
                ).fetchone()
                if low:
                    date_mins.append(str(low))
                if high:
                    date_maxs.append(str(high))
        has_runs = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='collection_runs'"
        ).fetchone()
        if has_runs:
            run_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(collection_runs)")
            }
            if "snapshot_date" in run_columns:
                low, high = conn.execute(
                    "SELECT MIN(snapshot_date),MAX(snapshot_date) FROM collection_runs"
                ).fetchone()
                if low:
                    date_mins.append(str(low))
                if high:
                    date_maxs.append(str(high))
        conn.rollback()
        payload_rows = sum(counts.values())
        expected = universe_row.get("surface_observed_rows")
        if expected is None and census_row is not None:
            expected = census_row.get("payload_rows")
        alignment = (
            "UNKNOWN"
            if expected is None
            else "MATCH"
            if int(expected) == payload_rows
            else "MISMATCH"
        )
        base.update(
            health="READABLE",
            payload_rows=payload_rows,
            tables=counts,
            held_range={"from": min(date_mins), "to": max(date_maxs)}
            if date_mins and date_maxs
            else None,
            census_alignment=alignment,
        )
        if alignment == "MISMATCH":
            base["issues"] = sorted(
                set([*base["issues"], "generated census count differs from DB snapshot"])
            )
        return base
    except (OSError, sqlite3.Error, ValueError) as exc:
        base["issues"] = sorted(
            set([*base["issues"], f"DB read UNKNOWN ({type(exc).__name__})"])
        )
        return base
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def validate_price(price: Any) -> dict[str, Any]:
    if not isinstance(price, dict):
        raise Unknown("canonical offer price is not an object")
    amount = price.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise Unknown("canonical offer amount_cents is invalid")
    if not isinstance(price.get("currency"), str) or not price["currency"]:
        raise Unknown("canonical offer currency is invalid")
    if not isinstance(price.get("cadence"), str) or not price["cadence"]:
        raise Unknown("canonical offer cadence is invalid")
    return json.loads(json.dumps(price))


def build_skus(
    offers: dict[str, Any], clocks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_rows = offers.get("offers")
    if not isinstance(source_rows, list) or not all(
        isinstance(row, dict) for row in source_rows
    ):
        raise Unknown("canonical offer projection has no offers list")
    by_clock = {row["clock"]: row for row in clocks}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offer in source_rows:
        sku = offer.get("sku")
        if not isinstance(sku, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{1,127}", sku
        ):
            raise Unknown("canonical offer has an invalid SKU")
        if sku in seen:
            raise Unknown("canonical offer repeats a SKU")
        seen.add(sku)
        price = validate_price(offer.get("price"))
        source_clock = offer.get("source_clock")
        requested = offer.get("requested_range")
        source = by_clock.get(source_clock) if isinstance(source_clock, str) else None
        if not source_clock:
            coverage = "NOT-COVERED"
            coverage_reason = "offer declares no source_clock"
        elif source is None or source.get("health") != "READABLE":
            coverage = "UNKNOWN"
            coverage_reason = "source clock is absent or unreadable"
        elif (
            not isinstance(requested, dict)
            or not isinstance(requested.get("from"), str)
            or not isinstance(requested.get("to"), str)
            or source.get("held_range") is None
        ):
            coverage = "NOT-COVERED"
            coverage_reason = "offer declares no verifiable requested range"
        elif (
            requested["from"] >= source["held_range"]["from"]
            and requested["to"] <= source["held_range"]["to"]
        ):
            coverage = "HELD"
            coverage_reason = "requested range is within the held clock range"
        else:
            coverage = "NOT-COVERED"
            coverage_reason = "requested range exceeds the held clock range"
        endpoint = offer.get("endpoint")
        if endpoint is None:
            endpoint = offer.get("request_url")
        row = {
            "sku": sku,
            "label": offer.get("label"),
            "price": price,
            "endpoint": endpoint,
            "request_url": offer.get("request_url"),
            "offer_url": offer.get("offer_url"),
            "checkout_armed": bool(offer.get("checkout_armed", False)),
            "machine_purchase": offer.get("machine_purchase"),
            "source_clock": source_clock,
            "requested_range": requested,
            "coverage": coverage,
            "coverage_reason": coverage_reason,
            "not_covered": offer.get("not_covered") or [],
        }
        result.append(row)
    result.sort(key=lambda row: row["sku"])
    machine_skus = offers.get("machine_skus") or []
    if not isinstance(machine_skus, list) or not all(
        isinstance(row, dict) for row in machine_skus
    ):
        raise Unknown("machine_skus has an invalid shape")
    summary = {
        "offers_total": len(result),
        "human_request_urls": sum(bool(row.get("request_url")) for row in result),
        "checkout_armed_offers": sum(row["checkout_armed"] for row in result),
        "coverage": {
            state: sum(row["coverage"] == state for row in result)
            for state in ("HELD", "NOT-COVERED", "UNKNOWN")
        },
        "machine_sku_candidates": len(machine_skus),
        "machine_payable_skus": sum(
            row.get("status") == "MACHINE-PAYABLE" for row in machine_skus
        ),
        "machine_purchase_readiness": offers.get("machine_purchase_readiness"),
        "machine_sku_readiness": offers.get("machine_sku_readiness"),
    }
    return result, summary


def latest_source_time(*values: str | None) -> str:
    parsed: list[tuple[datetime, str]] = []
    for value in values:
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        parsed.append((dt, value))
    if not parsed:
        raise Unknown("source inputs have no usable generation timestamp")
    return max(parsed)[1]


def build_document(
    *,
    clocks_root: Path,
    census: dict[str, Any],
    census_raw: bytes,
    offers: dict[str, Any],
    offers_raw: bytes,
    offers_source: str,
    surfaces_path: Path | None,
) -> dict[str, Any]:
    universe, surface_meta, census_time = merge_universe(census, surfaces_path)
    by_census, _ = census_rows(census)
    clocks = [
        read_clock(clocks_root, row, by_census.get(row["clock"])) for row in universe
    ]
    skus, offer_summary = build_skus(offers, clocks)
    generated_at = latest_source_time(census_time, surface_meta.get("generated_at"))
    health = {
        state: sum(row["health"] == state for row in clocks)
        for state in ("READABLE", "UNKNOWN")
    }
    clock_summary = {
        "total": len(clocks),
        "health": health,
        "with_held_range": sum(row["held_range"] is not None for row in clocks),
        "payload_rows_readable": sum(
            row["payload_rows"] or 0 for row in clocks if row["health"] == "READABLE"
        ),
        "census_alignment": {
            state: sum(row["census_alignment"] == state for row in clocks)
            for state in ("MATCH", "MISMATCH", "UNKNOWN")
        },
    }
    return {
        "schema": SCHEMA,
        "canonical_url": PUBLIC_CANONICAL,
        "generated_at": generated_at,
        "sources": {
            "collector_census": {
                "name": "collector_exhaust_census.v1.json",
                "sha256": sha256_bytes(census_raw),
                "checked_at": census_time,
                "collector_rows": len(by_census),
            },
            "surface_census": surface_meta,
            "offer_catalog": {
                "source": offers_source,
                "sha256": sha256_bytes(offers_raw),
                "schema": offers.get("schema"),
                "offer_rows": len(offers.get("offers") or []),
            },
        },
        "clock_summary": clock_summary,
        "offer_summary": offer_summary,
        "clocks": clocks,
        "skus": skus,
        "boundaries": {
            "clock_unreadable": "UNKNOWN, never omitted and never zero",
            "sku_without_source_clock_or_range": "NOT-COVERED",
            "offer_count_is_not_machine_purchase_count": True,
            "fetch_is_not_demand": True,
            "signature_identity": "UNANCHORED_RELEASE_KEY",
        },
    }


def sign_document(
    document: dict[str, Any],
    *,
    hmac_key: bytes | None,
    ephemeral_ed25519: bool,
) -> tuple[dict[str, Any], bytes | None]:
    payload = canonical(document)
    payload_sha256 = sha256_bytes(payload)
    if hmac_key is not None:
        signature = {
            "algorithm": "hmac-sha256",
            "payload_sha256": payload_sha256,
            "value": hmac.new(hmac_key, payload, hashlib.sha256).hexdigest(),
        }
        return {**document, "signature": signature}, None
    if not ephemeral_ed25519:
        raise Unknown("no signing mode selected")
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signature = {
        "algorithm": "Ed25519",
        "payload_sha256": payload_sha256,
        "value_base64": base64.b64encode(private_key.sign(payload)).decode("ascii"),
        "public_key": {
            "encoding": "raw-base64",
            "value": base64.b64encode(public_raw).decode("ascii"),
            "sha256_raw": sha256_bytes(public_raw),
            "scope": "one-time-unanchored-cand494-release-key",
        },
    }
    return {**document, "signature": signature}, public_pem


def money(price: dict[str, Any]) -> str:
    if isinstance(price.get("display"), str) and price["display"]:
        return price["display"]
    amount = price["amount_cents"] / 100
    cadence = str(price["cadence"]).replace("_", " ")
    suffix = "" if cadence == "one time" else f" / {cadence}"
    return f"${amount:,.2f}{suffix}"


def safe_href(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    if not parsed.scheme and value.startswith("/"):
        return value
    return None


def render_html(document: dict[str, Any]) -> str:
    clock_summary = document["clock_summary"]
    offer_summary = document["offer_summary"]
    clock_rows = []
    for row in document["clocks"]:
        held = (
            f"{row['held_range']['from']} to {row['held_range']['to']}"
            if row["held_range"]
            else "UNKNOWN"
        )
        count = (
            f"{row['payload_rows']:,}"
            if isinstance(row["payload_rows"], int)
            else "UNKNOWN"
        )
        clock_rows.append(
            "<tr>"
            f"<td><code>{html.escape(row['clock'])}</code></td>"
            f"<td><span class='state {row['health'].lower()}'>{row['health']}</span></td>"
            f"<td>{count}</td><td>{html.escape(held)}</td>"
            f"<td>{html.escape(str(row['cadence']))}</td>"
            f"<td>{html.escape(str(row['collector_disposition']))}</td>"
            "</tr>"
        )
    sku_rows = []
    for row in document["skus"]:
        href = safe_href(row.get("request_url")) or safe_href(row.get("endpoint"))
        action = (
            f"<a href='{html.escape(href, quote=True)}'>Request</a>"
            if href
            else "No request endpoint"
        )
        label = row.get("label") or row["sku"]
        sku_rows.append(
            "<tr>"
            f"<td><strong>{html.escape(str(label))}</strong><br><code>{html.escape(row['sku'])}</code></td>"
            f"<td>{html.escape(money(row['price']))}</td>"
            f"<td><span class='state coverage'>{html.escape(row['coverage'])}</span><br>"
            f"<small>{html.escape(row['coverage_reason'])}</small></td>"
            f"<td>{'Yes' if row['checkout_armed'] else 'No'}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    machine_candidates = offer_summary["machine_sku_candidates"]
    machine_payable = offer_summary["machine_payable_skus"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signed sealed-estate catalog | US Tech Automations</title>
<meta name="description" content="A signed, machine-readable catalog of the sealed data estate: held ranges, row counts, cadence, health, prices, request endpoints and explicit gaps.">
<link rel="canonical" href="{PUBLIC_CANONICAL}">
<style>
:root{{--bg:#fff;--fg:#151821;--muted:#5c6473;--line:#dfe3ea;--panel:#f7f9fc;--accent:#1749c6;--ok:#116530;--unknown:#8a4b08}}
@media(prefers-color-scheme:dark){{:root{{--bg:#101217;--fg:#edf0f5;--muted:#a6afbf;--line:#2b313b;--panel:#171b23;--accent:#79a2ff;--ok:#7bd69a;--unknown:#f3bd73}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.58 system-ui,sans-serif}}
main,header,footer{{max-width:1120px;margin:auto;padding:0 24px}} header{{padding-top:54px}} h1{{line-height:1.15;margin-bottom:12px}} h2{{margin-top:46px}}
.lede{{max-width:78ch;color:var(--muted);font-size:1.08rem}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:28px 0}}
.card{{border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:18px}} .big{{font-size:1.55rem;font-weight:700}} .label{{color:var(--muted)}}
.notice{{border-left:4px solid var(--unknown);padding:12px 16px;background:var(--panel);max-width:85ch}}
.actions{{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}} .button{{display:inline-block;padding:10px 15px;border-radius:8px;background:var(--accent);color:white;text-decoration:none;font-weight:650}}
.button.secondary{{background:var(--panel);color:var(--accent);border:1px solid var(--line)}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:10px}} table{{border-collapse:collapse;width:100%;min-width:760px}} th,td{{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--line)}} th{{background:var(--panel);position:sticky;top:0}} small{{color:var(--muted)}}
.state{{font-weight:700}} .readable{{color:var(--ok)}} .unknown{{color:var(--unknown)}} .coverage{{color:var(--unknown)}} code{{font-size:.86em}} footer{{color:var(--muted);padding-top:34px;padding-bottom:54px}} a{{color:var(--accent)}}
</style>
</head>
<body>
<header>
  <p><a href="https://ustechautomations.com/offers">Offers</a> / sealed estate</p>
  <h1>Signed catalog of what we hold — and what we do not</h1>
  <p class="lede">Every clock row below is derived from the generated estate universe and a read-only database probe. Every price and request URL is copied from the canonical live offer feed. Missing data stays visible as <strong>UNKNOWN</strong>; an offer without a verifiable source clock and requested range is <strong>NOT-COVERED</strong>.</p>
  <div class="actions">
    <a class="button" href="{RAW_RELEASE_BASE}catalog.json">Download signed JSON</a>
    <a class="button secondary" href="{RAW_RELEASE_BASE}verify_catalog.py">Download verifier</a>
    <a class="button secondary" href="{RAW_RELEASE_BASE}public-key.pem">Download public key</a>
    <a class="button secondary" href="{OFFER_FEED_CANONICAL}">Canonical offer feed</a>
  </div>
</header>
<main>
  <div class="grid">
    <div class="card"><div class="big">{clock_summary['total']}</div><div class="label">clocks retained in the denominator</div></div>
    <div class="card"><div class="big">{clock_summary['health']['READABLE']}</div><div class="label">clock DBs readable</div></div>
    <div class="card"><div class="big">{clock_summary['health']['UNKNOWN']}</div><div class="label">clock DBs UNKNOWN</div></div>
    <div class="card"><div class="big">{offer_summary['offers_total']}</div><div class="label">human offer rows</div></div>
    <div class="card"><div class="big">{offer_summary['checkout_armed_offers']}</div><div class="label">offers with checkout armed</div></div>
    <div class="card"><div class="big">{machine_payable} / {machine_candidates}</div><div class="label">machine SKU candidates marked payable</div></div>
  </div>
  <div class="notice"><strong>{offer_summary['offers_total']} human offers does not mean {offer_summary['offers_total']} machine-purchasable products.</strong> The source feed currently marks {offer_summary['checkout_armed_offers']} offer checkouts armed and {machine_payable} of {machine_candidates} separate machine-SKU candidates as MACHINE-PAYABLE. This page copies those states; it does not promote them.</div>

  <h2>Clock coverage and health</h2>
  <p>Readable means this build opened the canonical DB with SQLite <code>mode=ro</code> and <code>query_only</code>, counted its payload tables, and derived its held range. It does not mean every collector is current or commercially usable; cadence, collector disposition, and disagreement stay separate.</p>
  <div class="table-wrap"><table><thead><tr><th>Clock</th><th>DB read</th><th>Rows</th><th>Held range</th><th>Cadence</th><th>Collector state</th></tr></thead><tbody>{''.join(clock_rows)}</tbody></table></div>

  <h2>Offer coverage and action path</h2>
  <p>Prices and request endpoints below are verbatim projections from the signed build's offer-source digest. Coverage is narrower: <strong>HELD</strong> requires a named source clock and a requested range fully inside the clock's held range. Everything else is NOT-COVERED or UNKNOWN.</p>
  <div class="table-wrap"><table><thead><tr><th>Offer</th><th>Price</th><th>Evidence coverage</th><th>Checkout armed</th><th>Action</th></tr></thead><tbody>{''.join(sku_rows)}</tbody></table></div>

  <h2>Verify without trusting this page</h2>
  <ol>
    <li>Download <a href="{RAW_RELEASE_BASE}catalog.json"><code>catalog.json</code></a>, <a href="{RAW_RELEASE_BASE}verify_catalog.py"><code>verify_catalog.py</code></a>, and <a href="{RAW_RELEASE_BASE}public-key.pem"><code>public-key.pem</code></a> into one directory.</li>
    <li>Run <code>python3 verify_catalog.py catalog.json</code> with Python and the <code>cryptography</code> package.</li>
    <li>The verifier matches the standalone public key to the embedded key, removes the signature object, canonicalizes the exact remaining JSON, checks its SHA-256, verifies the Ed25519 signature, and rejects a modified count, price, endpoint, or coverage state.</li>
  </ol>
  <p class="notice"><strong>Signature limit.</strong> The one-time release key is not an external identity certificate. The signature detects byte changes after release; the HTTPS URL and public Git history establish where this release was served.</p>

  <h2>Source snapshot</h2>
  <p>Generated from source observations through <strong>{html.escape(document['generated_at'])}</strong>. Catalog payload SHA-256: <code>{html.escape(document['signature']['payload_sha256'])}</code>. Fetches of this page are telemetry, not requests, referrals, settlements, or payments.</p>
</main>
<footer><p>US Tech Automations · <a href="https://ustechautomations.com/offers">See all offers</a> · <a href="https://ustechautomations.com/partner">Talk to our team</a></p></footer>
</body></html>
"""


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temp, flags, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clocks-root", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    offer = parser.add_mutually_exclusive_group(required=True)
    offer.add_argument("--offers", type=Path)
    offer.add_argument("--offers-url")
    parser.add_argument("--surfaces", type=Path)
    signing = parser.add_mutually_exclusive_group(required=True)
    signing.add_argument("--signing-key-file", type=Path)
    signing.add_argument("--ephemeral-ed25519", action="store_true")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--html-out", type=Path, required=True)
    parser.add_argument("--public-key-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        census, census_raw = load_json_file(args.census, label="collector census")
        if args.offers is not None:
            offers, offers_raw = load_json_file(args.offers, label="offer projection")
            offers_source = "supplied canonical offer projection"
        else:
            offers, offers_raw = load_offer_url(args.offers_url)
            offers_source = args.offers_url
        hmac_key = None
        if args.signing_key_file is not None:
            try:
                hmac_key = args.signing_key_file.read_bytes()
            except OSError as exc:
                raise Unknown(f"signing key unreadable: {type(exc).__name__}") from exc
            if not hmac_key:
                raise Unknown("signing key is empty")
        document = build_document(
            clocks_root=args.clocks_root,
            census=census,
            census_raw=census_raw,
            offers=offers,
            offers_raw=offers_raw,
            offers_source=offers_source,
            surfaces_path=args.surfaces,
        )
        signed, public_pem = sign_document(
            document,
            hmac_key=hmac_key,
            ephemeral_ed25519=args.ephemeral_ed25519,
        )
        json_bytes = canonical(signed) + b"\n"
        html_bytes = render_html(signed).encode("utf-8")
        atomic_write(args.json_out, json_bytes)
        atomic_write(args.html_out, html_bytes)
        if args.public_key_out is not None:
            if public_pem is None:
                raise Unknown("public key output requires Ed25519 signing")
            atomic_write(args.public_key_out, public_pem)
    except Unknown as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"UNKNOWN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "state": "PASS",
                "clocks": signed["clock_summary"],
                "offers": signed["offer_summary"],
                "payload_sha256": signed["signature"]["payload_sha256"],
                "signature_algorithm": signed["signature"]["algorithm"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
