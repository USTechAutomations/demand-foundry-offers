#!/usr/bin/env python3
"""Controls for the USTA sync rail: refusals, drift reporting, byte copies."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_to_usta as sync  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ITEMS = ("catalog", "certificates/cand-467-question-seal", "charter", "sitemap.xml", "index.html")


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sync.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sync-to-usta-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.usta = self.tmp / "usta"
        (self.usta / sync.PUBLIC).mkdir(parents=True)

    def make_source(self) -> Path:
        source = self.tmp / "source"
        for item in SOURCE_ITEMS:
            src, dst = ROOT / item, source / item
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        return source

    def test_wrong_checkout_is_refused(self):
        wrong = self.tmp / "not-usta"
        wrong.mkdir()
        code, _, err = run("--usta", str(wrong), "--write")
        self.assertEqual(code, 2)
        self.assertIn("not a USTA checkout", err)
        self.assertEqual(files_under(wrong), set())

    def test_check_reports_drift_without_writing(self):
        code, out, _ = run("--usta", str(self.usta))
        self.assertEqual(code, 1)
        self.assertEqual(out.count("DRIFT "), len(sync.TARGETS) + 1)
        self.assertIn(sync.OFFERS_TS, out)
        self.assertEqual(files_under(self.usta), set())

    def test_write_copies_bytes_and_second_check_is_clean(self):
        code, out, _ = run("--usta", str(self.usta), "--write")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("wrote "), len(sync.TARGETS) + 1)
        expected = {dest for _, dest in sync.TARGETS} | {sync.OFFERS_TS}
        self.assertEqual(files_under(self.usta), expected)
        for src, dest in sync.TARGETS:
            self.assertEqual((self.usta / dest).read_bytes(), (ROOT / src).read_bytes(), dest)
        self.assertEqual(
            (self.usta / sync.OFFERS_TS).read_bytes(),
            (Path(__file__).with_name("fixtures") / "offers.ts").read_bytes(),
        )
        code, out, _ = run("--usta", str(self.usta), "--check")
        self.assertEqual(code, 0)
        self.assertNotIn("DRIFT", out)
        self.assertIn("clean", out)
        # A tampered served copy is drift again.
        (self.usta / sync.PUBLIC / "sitemap.xml").write_bytes(b"<urlset/>")
        code, out, _ = run("--usta", str(self.usta))
        self.assertEqual(code, 1)
        self.assertEqual(out.count("DRIFT "), 1)

    def test_usta_repo_env_stands_in_for_flag(self):
        with unittest.mock.patch.dict("os.environ", {"USTA_REPO": str(self.usta)}):
            code, out, _ = run()
        self.assertEqual(code, 1)
        self.assertIn("DRIFT", out)

    def test_bad_signature_is_refused_in_both_modes(self):
        source = self.make_source()
        catalog = source / "catalog/catalog.json"
        tampered = json.loads(catalog.read_text(encoding="utf-8"))
        tampered["clock_summary"]["total"] += 1
        catalog.write_text(json.dumps(tampered), encoding="utf-8")
        for mode in ("--check", "--write"):
            code, _, err = run("--usta", str(self.usta), "--source", str(source), mode)
            self.assertEqual(code, 2, mode)
            self.assertIn("does not verify", err)
        self.assertEqual(files_under(self.usta), set())

    def test_untampered_copy_of_source_syncs(self):
        source = self.make_source()
        code, _, _ = run("--usta", str(self.usta), "--source", str(source), "--write")
        self.assertEqual(code, 0)
        self.assertEqual(len(files_under(self.usta)), len(sync.TARGETS) + 1)


if __name__ == "__main__":
    unittest.main()
