import io
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr
from pathlib import Path

from quant_llm_wiki.query import brainstorm as brainstorm_mod


PERF_LINE_RE = re.compile(r"^\[qlw-perf\] ([a-z_]+): (.+)$")


def parse_perf_lines(stderr: str) -> list[dict]:
    """Return a list of {event, fields} dicts, one per [qlw-perf] line."""
    out = []
    for line in stderr.splitlines():
        m = PERF_LINE_RE.match(line)
        if not m:
            continue
        event = m.group(1)
        fields = {}
        for kv in m.group(2).split():
            if "=" in kv:
                k, v = kv.split("=", 1)
                fields[k] = v
        out.append({"event": event, "fields": fields})
    return out


class RetrieveConceptArticlesTimingTests(unittest.TestCase):
    def test_emits_timing_line_with_mode_and_ms(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}):
                with redirect_stderr(buf):
                    brainstorm_mod._retrieve_concept_articles(
                        "anything", top_k=3, wiki_dir=wiki_dir,
                    )
            events = parse_perf_lines(buf.getvalue())
            timing = [e for e in events if e["event"] == "_retrieve_concept_articles"]
            self.assertEqual(len(timing), 1, f"expected exactly 1 timing line, got {buf.getvalue()!r}")
            f = timing[0]["fields"]
            self.assertIn("ms", f)
            self.assertIn("mode", f)
            self.assertIn("results", f)
            self.assertIn(f["mode"], {"chroma", "lexical", "empty"})
            self.assertGreaterEqual(float(f["ms"]), 0.0)
            self.assertEqual(f["results"], "0")  # empty wiki → no concepts


if __name__ == "__main__":
    unittest.main()
