#!/usr/bin/env python3
"""Fetch every catalog request URL and require a direct HTTP 200."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


USER_AGENT = "USTA-catalog-link-check/1.0"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url: str) -> tuple[str, int | None]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "ustechautomations.com":
        return "invalid", None
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with build_opener(NoRedirect).open(request, timeout=20) as response:
            return "http", int(response.status)
    except HTTPError as exc:
        return "http", int(exc.code)
    except (OSError, URLError, ValueError):
        return "unknown", None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_catalog_actions.py CATALOG_JSON", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        rows = document["skus"]
        urls = [row["request_url"] for row in rows]
        if not isinstance(rows, list) or not all(isinstance(url, str) and url for url in urls):
            raise ValueError("request URL shape differs")
        if len(set(urls)) != len(urls):
            raise ValueError("request URLs are not one-to-one with SKUs")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"UNKNOWN: catalog actions unreadable ({type(exc).__name__})", file=sys.stderr)
        return 2
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, urls))
    buckets = Counter(f"{kind}:{status}" for kind, status in results)
    unknown = sum(kind == "unknown" for kind, _ in results)
    invalid = sum(kind == "invalid" for kind, _ in results)
    direct_200 = sum(kind == "http" and status == 200 for kind, status in results)
    output = {
        "state": "PASS" if direct_200 == len(urls) else "UNKNOWN" if unknown else "FAIL",
        "request_urls": len(urls),
        "distinct_request_urls": len(set(urls)),
        "direct_http_200": direct_200,
        "invalid_hosts_or_schemes": invalid,
        "unreadable": unknown,
        "result_buckets": dict(sorted(buckets.items())),
        "raw_urls_emitted": 0,
    }
    print(json.dumps(output, sort_keys=True))
    if unknown:
        return 2
    return 0 if direct_200 == len(urls) else 1


if __name__ == "__main__":
    sys.exit(main())
