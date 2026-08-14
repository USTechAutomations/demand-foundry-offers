#!/usr/bin/env python3
"""Verify a USTA Ed25519 certificate. Requires the cryptography package."""
import base64, hashlib, json, sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
def main():
    if len(sys.argv) != 3:
        print("usage: verify_certificate.py CERTIFICATE_JSON PUBLIC_KEY_PEM", file=sys.stderr); return 2
    try:
        doc=json.loads(Path(sys.argv[1]).read_text()); key=serialization.load_pem_public_key(Path(sys.argv[2]).read_bytes())
        if not isinstance(key, Ed25519PublicKey) or doc.get("algorithm") != "Ed25519": return 1
        raw = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        if doc.get("payload", {}).get("public_key", {}).get("sha256_raw") != hashlib.sha256(raw).hexdigest(): return 1
        key.verify(base64.b64decode(doc["signature"], validate=True), canonical(doc["payload"]))
    except (OSError, ValueError, KeyError, InvalidSignature):
        print("INVALID"); return 1
    print("VALID"); return 0
if __name__ == "__main__": raise SystemExit(main())
