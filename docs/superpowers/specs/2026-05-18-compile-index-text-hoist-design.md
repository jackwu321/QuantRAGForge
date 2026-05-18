# `_build_index_text` Hoist — 设计与验证计划

## Context

v0.4.3 (`ad1ebf7`) 修了 `compile_wiki` 的 recompile 反向索引；v0.4.4 (`2343485`) 量化了它：large scale 下 `recompile_ms ≈ 374ms`，但 `assign_ms ≈ 22029ms`——也就是说 assign 阶段比 recompile 阶段贵 60×。继续做 compile 的下一步优化，最大候选是把 `_build_index_text(wiki_dir)` 从 assign 循环里 hoist 出来。

`docs/superpowers/specs/2026-05-17-brainstorm-compile-perf-design.md` 的 Out-of-Scope 把这条挂起来，理由是"会改变同一次 compile run 中后续文章是否能看见前面新 propose 的 concept；需先决定语义"。

Codex 二次评审指出这条语义风险**按当前代码不成立**：

- `compile.py:156–157` `_build_index_text` 显式 `if c.status != "stable": continue`
- `compile.py:186` `_create_proposed_concept` 写 `status="proposed"`
- recompile 循环（唯一写 `status="stable"` 的路径，L386）在 assign 循环结束后才跑（L336 计时切分）

因此 assign 循环内的"已观测 stable 集合"在循环内是 invariant，hoist 后语义等价。

本计划不直接假设"接受 frozen index 语义"，而是先用一个测试把这个等价性锁住，再测 `_build_index_text` 在 `assign_ms` 里的真实占比，决定要不要做 hoist。

## 验证后的代码现状

| Claim | 文件 | 位置 | 现状 |
|---|---|---|---|
| `_build_index_text` 只读 stable concepts | `quant_llm_wiki/wiki/compile.py` | L145–159 | status filter 在 L156–157，确凿 |
| `_create_proposed_concept` 总是写 proposed | `quant_llm_wiki/wiki/compile.py` | L177–202 | hard-coded `status="proposed"` L186 |
| Assign 循环内无 stable 写路径 | `quant_llm_wiki/wiki/compile.py` | L273–331 | 唯一概念写是 L313 `_create_proposed_concept`；`update_source_entry` / `write_source_summary` 不动 concepts/ |
| Recompile 是唯一 stable 写路径 | `quant_llm_wiki/wiki/compile.py` | L341–405 | `status="stable"` 在 L386；在 assign 循环退出后 |
| Assign 循环每轮调用 `_build_index_text` | `quant_llm_wiki/wiki/compile.py` | L294 | 循环体内，每篇 article 一次 |

## 阶段化交付（带 gate）

整个工作分四个 phase。**Phase 0、Phase 1 是 gate**：如果 gate 输出不符合阈值，立刻停手、把判断写回 `2026-05-17-perf-validation-report.md` 的 followup 段，转去做 `lint_wiki` staleness 设计；不强推 hoist。

### Phase 0 — 锁定语义等价（gate-1，必须做）

**目的**：用一个测试把"assign 循环结束前后 `_build_index_text(wiki_dir)` 输出相同"这个不变量焊死。**这个测试要在改任何 production code 之前先写、先过**——它在当前 HEAD 上就应该 pass，因为现状已经满足不变量；它的价值是回归保护：未来如果谁加了一条 assign 期间写 stable 的代码路径，这个测试会立刻 fail。

**新增测试** `tests/test_wiki_compile.py`：

**关键设计要点（v2，2026-05-18 修订）**：我们要锁的不变量是**"从 assign 循环第一次迭代开始 → assign 循环结束"**这个窗口内 `_build_index_text(wiki_dir)` 不变，而不是从"compile_wiki 调用前"到"compile_wiki 调用后"。原因：`compile_wiki` 在进入 assign 循环**之前**会调用 `bootstrap_wiki` (L234) 和（rebuild 模式下）删除 + 重写所有 concept 文件 (L237–250)；这些操作虽然可能改变 stable 集合，但都不在 hoist 影响的窗口里。Hoist 把 `_build_index_text` 从循环内移到循环外、但仍在 `_t_assign_start` **之后**——所以我们要测的就是这个 window-internal invariant。

具体做法：用 `side_effect` 在**第一次 `assign_concepts` 调用**（assign 循环 iteration 1 进入时）和**第一次 `recompile_concept` 调用**（assign 循环结束、recompile 循环开始第一刻，对应 compile.py:L336 计时切分点之后立刻）两个点 snapshot。这两个点恰好是 assign loop 的进入/退出边界，且都在 `compile_wiki` 内部，对 bootstrap 的行为无感。

```python
class BuildIndexTextInvariantTests(unittest.TestCase):
    def test_build_index_text_unchanged_across_assign_loop(self):
        """
        Assign loop must not change the stable-concept set that
        _build_index_text reads. Locks in the precondition for the
        _build_index_text hoist optimization.

        Snapshots are taken INSIDE compile_wiki via side_effect:
          - first assign_concepts call  = state at iteration 1 entry
          - first recompile_concept call = state at end of assign loop
        Anything bootstrap/rebuild does BEFORE the assign loop is
        irrelevant — the hoist only affects the loop-internal window.

        Trigger: mocked assign_concepts MUST return at least one
        existing_concept so recompile fires (proposed-only assignments
        do not enter affected_concept_slugs).
        """
        from quant_llm_wiki.wiki import compile as wiki_compile
        from quant_llm_wiki.wiki.compile import _build_index_text, compile_wiki
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            wiki_dir = kb_root / "wiki"
            _seed_kb_with_articles(kb_root)  # 不需要 pre-seed concept；bootstrap 会做

            snapshot = {}
            real_assign = wiki_compile.assign_concepts  # not used; just for clarity

            def _assign_side_effect(*args, **kwargs):
                snapshot.setdefault(
                    "index_text_at_loop_entry",
                    _build_index_text(wiki_dir),
                )
                return _mock_assign_with_existing_and_proposed(
                    existing=["momentum-strategies"],
                )()

            def _recompile_side_effect(*args, **kwargs):
                snapshot.setdefault(
                    "index_text_at_loop_exit",
                    _build_index_text(wiki_dir),
                )
                return _mock_recompile_result()

            with unittest.mock.patch(
                "quant_llm_wiki.wiki.compile.assign_concepts",
                side_effect=_assign_side_effect,
            ), unittest.mock.patch(
                "quant_llm_wiki.wiki.compile.recompile_concept",
                side_effect=_recompile_side_effect,
            ):
                compile_wiki(kb_root=kb_root, mode="incremental")

            self.assertIn("index_text_at_loop_entry", snapshot)
            self.assertIn("index_text_at_loop_exit", snapshot)
            # Sanity: the stable set is non-empty (bootstrap seeded
            # momentum-strategies as stable), so the test isn't
            # trivially satisfied by empty == empty.
            self.assertNotEqual(snapshot["index_text_at_loop_entry"], "")
            self.assertEqual(
                snapshot["index_text_at_loop_entry"],
                snapshot["index_text_at_loop_exit"],
            )
```

`_seed_kb_with_articles`、`_mock_assign_with_existing_and_proposed`、`_mock_recompile_result` 在测试文件顶部以小 helper 形式存在。`_seed_kb_with_articles` 创建两个 article dir（仿 `_setup_corpus` 行 119–132 的 frontmatter shape），让 assign 循环至少跑两轮（一轮证明不了"循环内不变"）。**不**手动 pre-seed concept——bootstrap 会自己写入 `momentum-strategies`（status: stable），它会自然进入 `_build_index_text` 输出。`_mock_assign_with_existing_and_proposed(existing=[...])` 每次返回一个不同 slug 的 `ProposedConcept`（用闭包计数器避免两个 article 抢同名 file），让 assign 循环真的写出 proposed concepts。

**Gate-1**：测试在当前 HEAD pass。

- ✅ pass → 进入 Phase 1。
- ❌ fail → 说明现有代码已经违反不变量（probably bootstrap 或别处也在写 stable）。**停手**，把发现写进 followup 段，不要 hoist。

### Phase 1 — 测 `_build_index_text` 在 `assign_ms` 里的真实占比（gate-2）

**改动**：`quant_llm_wiki/wiki/compile.py` 在 `_t_assign_start`/`_assign_ms` 测量内部增加一个细粒度累加器，与现有 `QLW_PERF_DEBUG` 门控一致。

```python
# 在 L272 附近，紧挨 _t_assign_start
_t_assign_start = time.perf_counter()
_build_index_text_ms = 0.0
for article_index, article_dir in enumerate(articles, start=1):
    ...
    # L294 替换为：
    _t_idx = time.perf_counter()
    index_text = _build_index_text(wiki_dir)
    _build_index_text_ms += (time.perf_counter() - _t_idx) * 1000.0
    ...
```

并在 `_emit_perf("compile_wiki", ...)` 的 kwargs 里加 `build_index_text_ms=round(_build_index_text_ms, 3)`。

**测**：

```bash
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale large --trials 3 --label idxtext-share
```

**Gate-2**：从 large scale 输出读 `build_index_text_ms / assign_ms`。

- 占比 ≥ 5% 且绝对值 ≥ 200ms → hoist 值得做，进入 Phase 2。
- 占比 < 5% 或绝对值 < 200ms → hoist 不值得（assign_ms 主要消耗在 LLM mock 或文件读上）。**停手**，本文件改名加 `-shelved` 后缀；把决策（包含实测数字）写进 `2026-05-17-perf-validation-report.md` 的 followup 段，转去推 `lint_wiki` staleness 设计。

**Gate-2 fail 时 instrumentation 怎么办**：保留 `build_index_text_ms` 累加器和 `_emit_perf` 字段不 revert。理由：(a) 已经在 `QLW_PERF_DEBUG` 门控里，未设环境变量时零成本（一个 dict lookup + 一次 perf_counter 减法）；(b) 它本身就是有用的诊断字段，未来生产侧再评估时可以直接读；(c) 留它就避免下一次重新加 instrumentation 时再走一次 review。Ship 一个 v0.4.5（只含 instrumentation）或挂进任意下一个 PR 都可以，由 Phase 1 执行者决定。

> 实测注脚：v0.4.4 benchmark 用 deterministic mock，`assign_concepts` 本身近乎 O(1)，所以 `_build_index_text` 占比可能比生产环境更高（被放大）。这意味着如果 mock 下都低于阈值，生产更低；mock 下高于阈值则需要在生产侧追加一次确认（不放进本 plan，作为 follow-up）。

### Phase 2 — Hoist 实现（仅在 gate-2 通过时进入）

**改动**：`quant_llm_wiki/wiki/compile.py` L294 移出循环。**关键**：hoisted 调用要放在 `_t_assign_start` **之后**，让 `assign_ms` 仍然包含这一次 index build 成本——这样 v0.4.4（每篇一次累加）和 v0.4.5（仅一次）的 `assign_ms` 字段定义一致、严格可比，差值就是 hoist 省下的 (N-1) 次成本。

```python
# 原本 L272 附近的写法（v0.4.4 仍是这样）：
#   _t_assign_start = time.perf_counter()
#   _build_index_text_ms = 0.0
#   for ...:
#       _t_idx_start = time.perf_counter()
#       index_text = _build_index_text(wiki_dir)
#       _build_index_text_ms += (time.perf_counter() - _t_idx_start) * 1000.0
#       ...

# v0.4.5 hoist 后：
_t_assign_start = time.perf_counter()
# Hoist: assign loop never writes stable concepts (only proposed),
# and _build_index_text filters by status == "stable", so the index
# text is invariant for the duration of this loop. Locked by
# tests/test_wiki_compile.py::BuildIndexTextInvariantTests.
_t_idx_start = time.perf_counter()
index_text = _build_index_text(wiki_dir)
_build_index_text_ms = (time.perf_counter() - _t_idx_start) * 1000.0
for article_index, article_dir in enumerate(articles, start=1):
    ...
    # 删掉循环内原本的 index_text = _build_index_text(wiki_dir)
    # 复用闭包里的 index_text
```

`_build_index_text_ms` 仍然出现在 `_emit_perf` 里，从"累加 N 次"变成"单次"——前后含义不一样，benchmark harness 不需要改（它只读字段），但 Phase 3 报告段要显式标注这个语义切换。

**新增测试**：不加新行为测试。`BuildIndexTextInvariantTests` 已经覆盖了"hoist 不改变可观测行为"这一断言。`tests/test_wiki_compile.py` 已有 end-to-end snapshot 类型测试覆盖 compile 输出。

### Phase 3 — 量化与文档

```bash
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale small  --trials 3 --label v0.4.5-hoist
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale medium --trials 3 --label v0.4.5-hoist
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale large  --trials 3 --label v0.4.5-hoist
```

把 v0.4.4 vs v0.4.5 三个 scale 加进 `2026-05-17-perf-validation-report.md` 一个新的"v0.4.5 increment"段，沿用现有表格风格。**只放 compile-side 字段**：`compile.assign_ms`、`compile.build_index_text_ms`、`compile.recompile_ms`、`compile.wall_ms`。不放 `query.total_ms`——本 PR 不动 query path，把它列进来只会引入噪音。`build_index_text_ms` 应该从 N×单次降到 1×单次，差值 ≈ (N-1) 倍单次成本，并应能在 `assign_ms` 上看到相同量级的下降（因为 hoisted 调用仍计入 `assign_ms`，N-1 次省下来的成本会反映出来）。报告段要显式标注 `build_index_text_ms` 语义从"循环累加"切换为"单次"。

**Ship 路径**：版本号 v0.4.5，按 `reference_pypi_release_via_tag` 走（tag push 触发 Trusted Publishing），changelog 一句话。

## 关键文件

- `quant_llm_wiki/wiki/compile.py`（L271–294 重构为 hoist；`_emit_perf` 增字段）
- `tests/test_wiki_compile.py`（追加 `BuildIndexTextInvariantTests`）
- `docs/superpowers/specs/2026-05-17-perf-validation-report.md`（追加 v0.4.5 段）

## 验证（整套流程）

```bash
cd /home/ubuntu/.project/knowledge

# Phase 0
python3 -m unittest tests.test_wiki_compile.BuildIndexTextInvariantTests -v
# 期望: PASS（当前 HEAD 已满足不变量）

# Phase 1：先加 instrumentation，再 measure
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale large --trials 3 --label idxtext-share
# 在 benchmarks/ 输出 JSON 里读 build_index_text_ms / assign_ms

# 仅 gate-2 通过时执行 Phase 2 + Phase 3
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v
QLW_PERF_DEBUG=1 python3 scripts/benchmark_perf.py --scale large --trials 3 --label v0.4.5-hoist
```

## 风险与对策

| 风险 | 级别 | 对策 |
|---|---|---|
| 未来有人加了 assign 期间写 stable 的路径（破坏不变量） | 中（未来向） | Phase 0 的 `BuildIndexTextInvariantTests` 永久锁住 |
| bootstrap 或加载流程绕开了上面的 invariant 假设 | 低 | Phase 0 gate 一旦 fail 就停手，不靠"我以为是" |
| Mock 放大占比，生产实际占比 < 阈值 | 中 | Phase 1 注脚提示生产侧再确认；如不放心可在 Phase 1 跑一次真实 LLM 小 scale |
| Hoist 后 `build_index_text_ms` 字段语义变化（累加 → 单次）让历史 benchmark 不可直接比 | 低 | 报告段里显式标注语义切换；`assign_ms` 因为口径不变（hoist 调用仍在 `_t_assign_start` 之后）仍可直接比 |

## 显式 Out-of-Scope

- **Query-time `lint_wiki` 改读 stale report**（仍在 followup 列表）：本计划不涉及。如果 gate-2 fail，下一站直接是它。
- **跨 process LLM rate-limit 协调**：`docs/plan/2026-05-17-zhipu-429-rate-limit-hardening.md` 自有 track。
- **生产侧（真 LLM）实测**：本计划用 deterministic mock；生产侧测量是 follow-up，不阻塞 v0.4.5 ship 决策。

## 决策与 Ship

- Phase 0 + Phase 1 + Phase 2 + Phase 3 全过 → v0.4.5 ship（含 instrumentation + hoist）。
- Phase 0 fail → 不动代码，写 followup，转 `lint_wiki`。
- Phase 1 gate-2 fail（占比不够）→ 保留 Phase 1 加的 `build_index_text_ms` instrumentation（已在 `QLW_PERF_DEBUG` 门控下零成本），不做 Phase 2/3；ship instrumentation-only patch（v0.4.5 或挂下一个 PR），写 followup，转 `lint_wiki`。
