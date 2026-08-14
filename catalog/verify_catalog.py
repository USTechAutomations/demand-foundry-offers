#!/usr/bin/env python3
"""Verify a cand-494 public catalog. Requires the cryptography package."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


HEX64 = re.compile(r"^[0-9a-f]{64}$")


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print("usage: verify_catalog.py CATALOG_JSON [PUBLIC_KEY_PEM]", file=sys.stderr)
        return 2
    try:
        catalog_path = Path(sys.argv[1])
        public_key_path = Path(sys.argv[2]) if len(sys.argv) == 3 else catalog_path.with_name("public-key.pem")
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") != "usta.estate-catalog.v1":
            raise ValueError("catalog schema differs")
        signature = document.pop("signature")
        if not isinstance(signature, dict) or set(signature) != {
            "algorithm",
            "payload_sha256",
            "value_base64",
            "public_key",
        }:
            raise ValueError("signature schema differs")
        if signature["algorithm"] != "Ed25519":
            raise ValueError("signature algorithm differs")
        public = signature["public_key"]
        if not isinstance(public, dict) or set(public) != {
            "encoding",
            "value",
            "sha256_raw",
            "scope",
        }:
            raise ValueError("public-key schema differs")
        if (
            public["encoding"] != "raw-base64"
            or public["scope"] != "one-time-unanchored-cand494-release-key"
            or not HEX64.fullmatch(str(public["sha256_raw"]))
        ):
            raise ValueError("public-key metadata differs")
        payload = canonical(document)
        payload_sha = hashlib.sha256(payload).hexdigest()
        raw_key = base64.b64decode(public["value"], validate=True)
        raw_signature = base64.b64decode(signature["value_base64"], validate=True)
        external_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        if not isinstance(external_key, Ed25519PublicKey):
            raise ValueError("external public key is not Ed25519")
        external_raw = external_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        if external_raw != raw_key:
            raise ValueError("external public key differs from embedded key")
        if payload_sha != signature["payload_sha256"]:
            raise ValueError("payload digest mismatch")
        if hashlib.sha256(raw_key).hexdigest() != public["sha256_raw"]:
            raise ValueError("public-key digest mismatch")
        external_key.verify(raw_signature, payload)
    except (OSError, ValueError, KeyError, TypeError, InvalidSignature) as exc:
        print(f"INVALID: {type(exc).__name__}")
        return 1
    print(f"VALID {payload_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
