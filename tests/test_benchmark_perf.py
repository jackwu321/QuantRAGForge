import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class BenchmarkPerfSmokeTest(unittest.TestCase):
    def test_small_scale_one_trial_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            proc = subprocess.run(
                [sys.executable, "scripts/benchmark_perf.py",
                 "--scale", "small", "--trials", "1",
                 "--out", str(out_dir), "--label", "smoke"],
                cwd=REPO_ROOT,
                capture_output=True, text=True,
                env={**os.environ, "QLW_PERF_DEBUG": "1"},
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stderr:\n{proc.stderr}")
            json_files = list(out_dir.glob("*.json"))
            self.assertEqual(len(json_files), 1, f"got {json_files}")
            rec = json.loads(json_files[0].read_text())
            self.assertEqual(rec["label"], "smoke")
            self.assertEqual(rec["scale"], "small")
            self.assertEqual(len(rec["trials"]), 1)
            t0 = rec["trials"][0]
            self.assertIn("compile_wiki", t0)
            self.assertIn("retrieve_blocks", t0)
            self.assertGreaterEqual(t0["compile_wiki"]["assign_ms"], 0.0)
            self.assertGreaterEqual(t0["compile_wiki"]["recompile_ms"], 0.0)
            self.assertGreaterEqual(t0["retrieve_blocks"]["total_ms"], 0.0)
            # Harness-observed call count (the v0.4.3 dedup invariant)
            self.assertEqual(t0["retrieve_blocks"]["concept_retrievals_observed"], 1)


if __name__ == "__main__":
    unittest.main()
