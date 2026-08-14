#!/usr/bin/env python3
"""Count non-self, non-bot fetches of catalog/discovery paths from LB logs.

The production mode reads Google Cloud load-balancer logs without modifying
them.  ``--input-json`` accepts the same exported JSON array for deterministic
fixtures.  A missing/unreadable source, malformed row, truncated query, absent
general LB heartbeat, future timestamp, or unclassifiable source state is
UNKNOWN (exit 2), never a zero.

Raw IP addresses and User-Agents are used only in memory.  A missing User-Agent
is excluded in the explicit unknown-client bucket; it can never become a
stranger count. Output contains
counts and timestamps, not client identifiers.  Any public IP associated with
a derived first-party User-Agent is excluded across all of its rows, so a fleet
probe cannot become "external" by changing to a generic browser string.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit


HOME = Path.home()
GCLOUD_CANDIDATES = (
    HOME / "google-cloud-sdk/bin/gcloud",
    Path("/usr/bin/gcloud"),
)
CLASSIFIER = (
    HOME / ".hermes/state/revenue-readiness/analysis/demand_read.py"
)
SCHEMA = "usta.catalog-fetches-external.v1"
METRIC = "catalog_fetches_external"
MAX_ROWS = 10_001
CATALOG_PREFIXES = (
    "/offers/catalog",
    "/demand-foundry-offers/catalog",
)
DISCOVERY_PATHS = frozenset(
    {
        "/.well-known/x402",
        "/.well-known/agent-card.json",
        "/.well-known/mcp.json",
        "/.well-known/mcp/server.json",
        "/agents.json",
        "/offers.json",
        "/agent-card.json",
    }
)


class Unknown(Exception):
    pass


def load_classifier():
    if not CLASSIFIER.is_file():
        raise Unknown("shared demand classifier absent")
    try:
        spec = importlib.util.spec_from_file_location("cand494_demand_read", CLASSIFIER)
        if spec is None or spec.loader is None:
            raise ImportError("classifier spec absent")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        declared = module.runtime_declared_agent_strings()
        classify = module.classify_user_agent
    except Exception as exc:
        raise Unknown(f"shared demand classifier unreadable ({type(exc).__name__})") from exc
    return declared, classify


def parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise Unknown("log row timestamp absent")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unknown("log row timestamp unreadable") from exc
    if parsed.tzinfo is None:
        raise Unknown("log row timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def scoped_path(url: str) -> str | None:
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    if any(path == prefix or path.startswith(prefix + "/") for prefix in CATALOG_PREFIXES):
        return "catalog"
    if path in DISCOVERY_PATHS:
        return "discovery"
    return None


def validate_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise Unknown("load-balancer log export is not an array")
    if len(rows) >= MAX_ROWS:
        raise Unknown("load-balancer query reached its row limit")
    checked: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for row in rows:
        if not isinstance(row, dict):
            raise Unknown("load-balancer log row is not an object")
        request = row.get("httpRequest")
        if not isinstance(request, dict):
            raise Unknown("load-balancer log row lacks httpRequest")
        timestamp = parse_time(row.get("timestamp"))
        if timestamp > now + timedelta(minutes=5):
            raise Unknown("load-balancer log row is future-dated")
        url = request.get("requestUrl")
        ua = request.get("userAgent")
        remote_ip = request.get("remoteIp")
        status = request.get("status")
        if (
            not isinstance(url, str)
            or (ua is not None and not isinstance(ua, str))
            or not isinstance(remote_ip, str)
            or isinstance(status, bool)
            or not isinstance(status, int)
        ):
            raise Unknown("load-balancer log httpRequest fields differ")
        checked.append(
            {
                "timestamp": timestamp,
                "url": url,
                "ua": ua or "",
                "remote_ip": remote_ip,
                "status": status,
            }
        )
    return checked


def count_rows(rows: list[dict[str, Any]], *, source_observed: bool) -> dict[str, Any]:
    if not source_observed:
        raise Unknown("no general load-balancer observation proves the source is active")
    declared, classify = load_classifier()
    for row in rows:
        row["client_class"] = classify(row["ua"], declared)
        if row["client_class"] not in {"self", "bot", "stranger", "unknown"}:
            raise Unknown("shared classifier returned an unknown state")
    self_ips = {row["remote_ip"] for row in rows if row["client_class"] == "self"}
    counts = Counter()
    scoped_success = []
    for row in rows:
        scope = scoped_path(row["url"])
        if scope is None or not 200 <= row["status"] < 400:
            continue
        client_class = row["client_class"]
        if row["remote_ip"] in self_ips:
            client_class = "self"
        counts[f"{scope}_{client_class}"] += 1
        counts[client_class] += 1
        scoped_success.append(row["timestamp"])
    return {
        "schema": SCHEMA,
        "metric": METRIC,
        "state": "COUNTED",
        "unit": "fetches",
        "value": counts["stranger"],
        "scope": {
            "catalog_external": counts["catalog_stranger"],
            "discovery_external": counts["discovery_stranger"],
            "self_excluded": counts["self"],
            "bots_excluded": counts["bot"],
            "unknown_clients_excluded": counts["unknown"],
        },
        "source_rows": len(rows),
        "successful_scoped_rows": len(scoped_success),
        "last_scoped_observed_at": max(scoped_success).isoformat().replace("+00:00", "Z")
        if scoped_success
        else None,
        "raw_identifiers_emitted": 0,
    }


def gcloud_path() -> Path:
    for path in GCLOUD_CANDIDATES:
        if path.is_file() and path.stat().st_mode & 0o111:
            return path
    raise Unknown("gcloud executable absent")


def run_gcloud(filter_text: str, *, project: str, account: str, freshness: str, limit: int) -> list[dict[str, Any]]:
    command = [
        str(gcloud_path()),
        "logging",
        "read",
        filter_text,
        f"--project={project}",
        f"--account={account}",
        f"--freshness={freshness}",
        f"--limit={limit}",
        "--format=json",
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unknown(f"gcloud log query unavailable ({type(exc).__name__})") from exc
    if proc.returncode != 0:
        raise Unknown("gcloud log query failed")
    try:
        value = json.loads(proc.stdout)
    except ValueError as exc:
        raise Unknown("gcloud log output is not JSON") from exc
    if not isinstance(value, list):
        raise Unknown("gcloud log output is not an array")
    return value


def production_rows(project: str, account: str, freshness: str) -> tuple[list[dict[str, Any]], bool]:
    heartbeat = run_gcloud(
        'resource.type="http_load_balancer"',
        project=project,
        account=account,
        freshness=freshness,
        limit=1,
    )
    source_observed = bool(heartbeat)
    path_filter = (
        'resource.type="http_load_balancer" AND ('
        'httpRequest.requestUrl:"/offers/catalog" OR '
        'httpRequest.requestUrl:"/demand-foundry-offers/catalog" OR '
        'httpRequest.requestUrl:"/.well-known/" OR '
        'httpRequest.requestUrl:"/agents.json" OR '
        'httpRequest.requestUrl:"/offers.json" OR '
        'httpRequest.requestUrl:"/agent-card.json")'
    )
    rows = run_gcloud(
        path_filter,
        project=project,
        account=account,
        freshness=freshness,
        limit=MAX_ROWS,
    )
    return rows, source_observed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", type=Path)
    parser.add_argument("--source-observed", action="store_true")
    parser.add_argument("--project", default="usta-prod")
    parser.add_argument("--account", default="admin@ustechautomations.com")
    parser.add_argument("--freshness", default="30d")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.input_json is not None:
            rows = json.loads(args.input_json.read_text(encoding="utf-8"))
            source_observed = args.source_observed
        else:
            rows, source_observed = production_rows(
                args.project, args.account, args.freshness
            )
        result = count_rows(validate_rows(rows), source_observed=source_observed)
    except (OSError, ValueError, Unknown) as exc:
        result = {
            "schema": SCHEMA,
            "metric": METRIC,
            "state": "UNKNOWN",
            "unit": "fetches",
            "value": None,
            "reason": str(exc),
            "raw_identifiers_emitted": 0,
        }
        print(json.dumps(result, sort_keys=True))
        return 2
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
