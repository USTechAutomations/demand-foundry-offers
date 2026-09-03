#!/usr/bin/env python3
"""Push this repo's verification artifacts into a USTA checkout.

The canonical /offers pages are React routes in `US-Tech-Automations/USTA`; the
files an outside reader downloads and verifies are served verbatim from
`usta-react/public/offers/`. This script is the only rail between the
generators here and those served files.

    sync_to_usta.py --usta ~/Developer/USTA            # --check: report drift, exit 1
    sync_to_usta.py --usta ~/Developer/USTA --write    # copy, then re-run --check yourself

`USTA_REPO` in the environment stands in for `--usta`. Before anything is
compared or copied the catalog's Ed25519 signature is verified with
`catalog/verify_catalog.py`; a catalog that does not verify is never synced.
`--write` also regenerates `offers.ts` from `index.html` on every run (the
exporter is deterministic, so an unchanged page is a no-op).

Only the paths listed in TARGETS are ever written.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_offers_ts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = "usta-react/public/offers"
DATA = "usta-react/src/website/pages/offers/data"
OFFERS_TS = f"{DATA}/offers.ts"

# (source relative to this repo, destination relative to the USTA checkout)
TARGETS = (
    ("catalog/catalog.json", f"{PUBLIC}/catalog/catalog.json"),
    ("catalog/catalog.json", f"{DATA}/catalog.json"),
    ("catalog/public-key.pem", f"{PUBLIC}/catalog/public-key.pem"),
    ("catalog/verify_catalog.py", f"{PUBLIC}/catalog/verify_catalog.py"),
    *(
        (f"certificates/cand-467-question-seal/{name}", f"{PUBLIC}/certificates/cand-467-question-seal/{name}")
        for name in ("certificate.json", "payload.json", "signature.bin", "public-key.pem", "verify_certificate.py")
    ),
    *(
        (f"charter/{name}", f"{PUBLIC}/charter/{name}")
        for name in ("rail-snapshot.json", "recorder-policy.json", "rederive.py")
    ),
    ("sitemap.xml", f"{PUBLIC}/sitemap.xml"),
)
ALLOWED_PREFIXES = (PUBLIC + "/", f"{DATA}/catalog.json", OFFERS_TS)


class Refused(Exception):
    pass


def verify_catalog(source: Path) -> None:
    catalog = source / "catalog"
    result = subprocess.run(
        [sys.executable, str(catalog / "verify_catalog.py"), str(catalog / "catalog.json"), str(catalog / "public-key.pem")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout.startswith("VALID "):
        raise Refused(f"catalog/catalog.json does not verify against catalog/public-key.pem ({result.stdout.strip() or result.stderr.strip()})")


def plan(source: Path, usta: Path) -> list[tuple[Path, bytes]]:
    """Every (destination, bytes) pair this script may write."""
    items = [(usta / dest, (source / src).read_bytes()) for src, dest in TARGETS]
    items.append((usta / OFFERS_TS, export_offers_ts.export(source / "index.html").encode("utf-8")))
    for dest, _ in items:
        rel = dest.relative_to(usta).as_posix()
        if not rel.startswith(ALLOWED_PREFIXES):
            raise Refused(f"destination outside the allowed paths: {rel}")
    return items


def run(source: Path, usta: Path, write: bool) -> int:
    if not (usta / PUBLIC).is_dir():
        raise Refused(f"{usta} is not a USTA checkout ({PUBLIC} missing)")
    verify_catalog(source)
    drift = 0
    for dest, payload in plan(source, usta):
        rel = dest.relative_to(usta).as_posix()
        same = dest.is_file() and dest.read_bytes() == payload
        if write:
            if not same:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)
            print(f"{'unchanged' if same else 'wrote'} {dest}")
        else:
            print(f"{'OK   ' if same else 'DRIFT'} {rel}")
            drift += not same
    if write:
        return 0
    print("clean" if not drift else f"{drift} target(s) differ; run with --write")
    return 1 if drift else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--usta", type=Path, default=os.environ.get("USTA_REPO"), help="USTA checkout (default: $USTA_REPO)")
    parser.add_argument("--source", type=Path, default=ROOT, help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report byte-level drift without writing (default)")
    mode.add_argument("--write", action="store_true", help="copy every target into the checkout")
    args = parser.parse_args(argv)
    if args.usta is None:
        parser.error("pass --usta PATH or set USTA_REPO")
    try:
        return run(args.source.resolve(), args.usta.resolve(), write=args.write)
    except (Refused, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
