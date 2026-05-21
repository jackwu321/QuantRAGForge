# tiny_kb — a worked example for Quant_LLM_Wiki

This is a tiny pre-seeded knowledge base so you can try the `enrich → embed → compile → ask → brainstorm` flow **without bringing your own research articles**.

It ships with two synthetic, textbook-style primer articles (no real research material, no copyright concerns):

- `raw/2026-01-15_demo_momentum-factor-primer/` — a primer on the cross-sectional momentum factor
- `raw/2026-01-16_demo_sector-etf-rotation-primer/` — a primer on sector ETF rotation

Both are written in English so any LLM can ingest them cleanly.

## What's in the box

```
examples/tiny_kb/
├── README.md                  ← you are here
├── .gitignore                 ← keeps your generated wiki/vector_store/outputs out of git
└── raw/
    ├── 2026-01-15_demo_momentum-factor-primer/
    │   ├── article.md         ← markdown body + frontmatter
    │   └── source.json        ← ingest metadata
    └── 2026-01-16_demo_sector-etf-rotation-primer/
        ├── article.md
        └── source.json
```

## Run it

You need an LLM API key configured (see the top-level [README §3](../../README.md#3-configure-the-llm)).

```bash
# From the repo root
cd examples/tiny_kb
export QLW_KB_ROOT="$PWD"

# (Optional) put your LLM .env right here so it auto-loads
cp ../../llm_config.example.env .env
# edit .env to set LLM_API_KEY etc.

qlw enrich              # ~2 LLM calls, fills out idea_blocks / transfer_targets / etc.
qlw embed               # builds vector_store/
qlw compile             # compiles wiki/concepts/, wiki/sources/, wiki/INDEX.md
qlw lint                # schema + health audit (should be clean on these two)

qlw ask --query "What signals do these articles describe?"
qlw brainstorm --query "Combine momentum and sector ETF rotation into a single allocation rule"
```

After the run you'll see new directories appear:

```
examples/tiny_kb/
├── wiki/                  ← LLM-built concept memory (gitignored)
│   ├── INDEX.md
│   ├── state.json
│   ├── concepts/<slug>.md
│   ├── sources/<basename>.md
│   └── queries/<date>_<slug>_<mode>.md   ← each ask/brainstorm files a log here
├── vector_store/          ← ChromaDB (gitignored)
└── outputs/brainstorms/   ← full brainstorm + Rethink Layer scoring (gitignored)
```

Open `outputs/brainstorms/<date>_*_brainstorm.md` to read the generated ideas plus the Rethink Layer's novelty and quality scores.

## Reset between runs

```bash
rm -rf wiki/ vector_store/ outputs/
# raw/ stays — those are the seed articles
```

`qlw enrich` is also incremental: re-running it after `rm` will re-process the two articles; otherwise it skips already-enriched ones.

## Why these two articles?

They're chosen to:

1. **Sit in different `content_type` buckets** (`methodology` vs `allocation`) so the wiki compiler builds at least two concept clusters.
2. **Share enough overlap** (both reference rebalancing cadence and risk control) that `brainstorm` has something to combine — exercising the wiki-first retrieval path and the Rethink Layer's novelty check.
3. **Be entirely synthetic** — no copying of real broker or vendor research, no reproduction of paywalled material.

They are **not** investment advice and **not** representative of what real ingested WeChat / PDF research looks like. They exist purely so the pipeline has something to chew on out-of-the-box.
