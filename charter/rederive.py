#!/usr/bin/env python3
"""Recount every number published by the USTA forward-provenance charter."""
import hashlib, json, re, sys
from collections import Counter
from pathlib import Path
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
def fail(message):
    print("FAIL: " + message, file=sys.stderr); return 1
def main():
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parent
    try:
        snapshot = json.loads((root / "rail-snapshot.json").read_text())
        policy_bytes = (root / "recorder-policy.json").read_bytes()
        policy = json.loads(policy_bytes)
        page = (root / "index.html").read_text()
    except (OSError, ValueError) as exc:
        print("UNKNOWN: public charter input unreadable: " + type(exc).__name__, file=sys.stderr); return 2
    if snapshot.get("schema") != "usta.forward-provenance-charter.v1": return fail("snapshot schema")
    if hashlib.sha256(policy_bytes).hexdigest() != snapshot.get("measurement", {}).get("recorder_policy_sha256"): return fail("policy digest")
    rows=snapshot.get("rows"); cutoff=snapshot.get("cutoff")
    if not isinstance(rows, list) or not isinstance(cutoff, str): return fail("snapshot shape")
    legacy=[r for r in rows if r.get("timestamp", "") < cutoff]
    post=[r for r in rows if r.get("timestamp", "") >= cutoff]
    legacy_un=[r for r in legacy if not r.get("provenance_present")]
    post_with=[r for r in post if r.get("provenance_present")]
    post_missing=[r for r in post if not r.get("provenance_present")]
    enforced=set(policy.get("provenance_required_for", []))
    if sorted(enforced) != sorted(snapshot.get("proof_bearing_verdicts", [])): return fail("policy verdict set")
    proof=[r for r in post if r.get("verdict") in enforced]
    proof_with=[r for r in proof if r.get("provenance_present")]
    ruled=[r for r in legacy if r.get("legacy_ruling") == "GRANDFATHERED-UNPROVEN"]
    calculated={
      "legacy_total":len(legacy), "legacy_unproven":len(legacy_un), "legacy_ruled":len(ruled),
      "post_cutoff_total":len(post), "post_cutoff_with_provenance":len(post_with),
      "post_cutoff_without_provenance":len(post_missing), "proof_bearing_total":len(proof),
      "proof_bearing_with_provenance":len(proof_with),
      "proof_bearing_without_provenance":len(proof)-len(proof_with),
      "post_missing_by_verdict":dict(sorted(Counter(r.get("verdict") for r in post_missing).items())),
    }
    if calculated != snapshot.get("summary"): return fail("snapshot summary does not recount")
    if len(legacy_un) != len(ruled): return fail("legacy ruling coverage")
    published={key:int(value) for key,value in re.findall(r'data-count="([a-z_]+)">(\d+)<', page)}
    page_expected={key:value for key,value in calculated.items() if isinstance(value,int)}
    if published != page_expected: return fail("HTML counts do not match snapshot")
    if calculated["proof_bearing_without_provenance"] != 0: return fail("proof-bearing row lacks provenance")
    print("VALID: " + str(len(rows)) + " rows; " + str(len(proof_with)) + "/" + str(len(proof)) + " proof-bearing rows carry provenance; " + str(len(ruled)) + " legacy gaps ruled")
    return 0
if __name__ == "__main__": raise SystemExit(main())
