# Brainstorm/Compile 复杂度优化 — 实现计划

## Context

Codex 对本仓库做了一份 complexity report，定位出 5 处热点；codex reviewer 的二次评审建议**只先做前两项**，并把另外几项作为后续工作。已通过 Explore agent 对每条 claim 在当前 main 分支做了行号级别的源码验证，全部属实。

本 PR 目的：在不改变行为的前提下，把 brainstorm 查询路径上的**重复 concept 检索**和 wiki recompile 阶段的 **O(S·A·K) 反向查找**两个结构性热点修掉，并加一对最小化 instrumentation，便于下一轮 PR 用数据验证。两个更大的项（`_build_index_text` 出循环、query-time `lint_wiki` 改读 stale report）有语义/设计风险，本 PR 不动。

## 验证后的代码现状

| Claim | 文件 | 位置 | 现状 |
|---|---|---|---|
| 双重 concept 检索 | `quant_llm_wiki/query/brainstorm.py` | `_concepts_to_blocks` L691–720 调一次；`retrieve_blocks` L756–776 又调一次 | 两处 `top_k` 都是 `DEFAULT_CONCEPT_TOP_K`，确属冗余 |
| `concept_to_articles` 反向索引缺失 | `quant_llm_wiki/wiki/compile.py` | L322–335 对每个 affected slug 全扫一遍 `article_to_concepts` | `article_to_concepts` 在 L275/L313/L315 三处写入，之后无变更，可同步维护反向索引 |

`_concepts_to_blocks` 的所有调用方（grep 结果）：brainstorm.py:759 + tests/test_query_wiki_first_ask.py:28 (mock) + tests/test_brainstorm_with_wiki.py:46,121。Wrapper 保留签名即可全部兼容。

## 修改清单

### 1) `quant_llm_wiki/query/brainstorm.py` — 去重 concept 检索

**新增内部 helper（L691 附近）**

```
def _retrieve_concepts_and_blocks(
    query, *, top_k, vector_store_dir, wiki_dir,
) -> tuple[list[KnowledgeBlock], list[dict]]:
    concepts = _retrieve_concept_articles(
        query, top_k=top_k,
        vector_store_dir=vector_store_dir,
        wiki_dir=wiki_dir,
    )
    blocks = [...]  # 原 _concepts_to_blocks 内的转换逻辑搬到这里
    return blocks, concepts
```

**`_concepts_to_blocks` 改为 thin wrapper**（保留原签名与返回类型，测试零修改）

```
def _concepts_to_blocks(...) -> list[KnowledgeBlock]:
    blocks, _ = _retrieve_concepts_and_blocks(...)
    return blocks
```

**改写 `retrieve_blocks` 中 wiki 分支（L756–776）**

```
wiki_blocks, wiki_concepts = _retrieve_concepts_and_blocks(
    query, top_k=DEFAULT_CONCEPT_TOP_K,
    vector_store_dir=store_dir, wiki_dir=resolved_wiki_dir,
)
if wiki_blocks:
    for c in wiki_concepts:
        for src_path in c["sources"]:
            src = Path(src_path)
            if not src.is_absolute():
                src = resolved_kb_root / src
            excluded_articles.add(str(src.parent))
```

删掉 L766–771 第二次 `_retrieve_concept_articles` 调用。

### 2) `quant_llm_wiki/wiki/compile.py` — 反向索引

**L255 附近声明同步结构**

```
article_to_concepts: dict[Path, list[str]] = {}
concept_to_articles: dict[str, list[Path]] = {}  # 同步维护
```

**在三处写入 `article_to_concepts` 后同步反向索引**（L275, L313；L315 空列表跳过）

```
seen = set()
for slug in feeds:        # 或 prior_entry.feeds_concepts
    if slug in seen:
        continue
    seen.add(slug)
    concept_to_articles.setdefault(slug, []).append(article_dir)
```

`seen` 去重是低成本保险，避免 feeds 中潜在重复 slug 让同一 article 被列两次。

**L327–329 替换为直接查找**

```
sources_for_concept = concept_to_articles.get(slug, [])
```

下游 L330–335 的 `existing_paths`/`affected_paths` 都是 `set`，`_source_sort_key` 排序结果不依赖 `sources_for_concept` 的迭代顺序，输出 byte-identical。

### 3) Instrumentation（QLW_PERF_DEBUG 门控）

- `retrieve_blocks` 在 wiki 分支结束后：

  ```
  if os.environ.get("QLW_PERF_DEBUG"):
      print(f"[qlw-perf] retrieve_blocks: concept_retrievals=1 wiki_blocks={len(wiki_blocks)}", file=sys.stderr)
  ```

  字面量 `concept_retrievals=1` 就是本 PR 想锁定的不变量；改回前是 `=2`。

- `compile_wiki` recompile 循环结束后：

  ```
  if os.environ.get("QLW_PERF_DEBUG"):
      print(f"[qlw-perf] compile_wiki: articles={len(articles)} affected_concepts={len(sorted_slugs)} reverse_index_size={len(concept_to_articles)}", file=sys.stderr)
  ```

未设置环境变量时零开销（一次 dict 查找）。不引入 logging 配置面。

## 新增测试

`tests/test_brainstorm_with_wiki.py` 末尾追加：

```
class RetrieveBlocksCallCountTests(unittest.TestCase):
    def test_retrieve_blocks_calls_retrieve_concept_articles_once(self):
        # 引导一个最小 wiki（bootstrap_wiki + 写一个 stable concept）
        # 让 _wiki_is_healthy_for_query 与 _should_use_wiki_memory 都返回 True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ...
            with unittest.mock.patch.object(
                brainstorm_from_kb,
                "_retrieve_concept_articles",
                wraps=brainstorm_from_kb._retrieve_concept_articles,
            ) as spy:
                brainstorm_from_kb.retrieve_blocks(
                    [note], "momentum", top_k=3,
                    command="brainstorm", retrieval_mode="keyword",
                    kb_root=root,
                )
            self.assertEqual(spy.call_count, 1)
```

实现前先把这个测试写出来，本应该 fail（call_count == 2），然后修代码让它过 — 一次行为锁定，一次回归保护。

Compile 反向索引不加新测试，靠 `tests/test_wiki_compile.py` 的端到端覆盖（sources 列表与排序作为 snapshot 自然 cover）。

## 关键文件

- `quant_llm_wiki/query/brainstorm.py`（L691–720, L756–776）
- `quant_llm_wiki/wiki/compile.py`（L255, L275, L313, L327–329）
- `tests/test_brainstorm_with_wiki.py`（追加 1 个测试类）

## 验证

```
cd /home/ubuntu/.project/knowledge

# 1. 先把 spy 测试加进去并确认在改代码前 fail（count=2）
python3 -m unittest tests.test_brainstorm_with_wiki.RetrieveBlocksCallCountTests -v

# 2. 改代码，再跑相关三个 test 模块
python3 -m unittest tests.test_brainstorm_with_wiki tests.test_query_wiki_first_ask tests.test_wiki_compile -v

# 3. 全量回归
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s tests/robustness -p 'test_*.py' -v

# 4. 打开 instrumentation，肉眼确认 concept_retrievals=1
QLW_PERF_DEBUG=1 python3 -m unittest tests.test_query_wiki_first_ask -v 2>&1 | grep '\[qlw-perf\]'
```

## 风险与对策

| 风险 | 级别 | 对策 |
|---|---|---|
| `_concepts_to_blocks` 签名变化影响外部 | 低 | 保留 wrapper；grep 已确认无外部调用 |
| 反向索引与 `article_to_concepts` drift | 低（未来向） | 三个写入点紧邻，同函数内同步；在 L255 加一行注释说明 lockstep 不变量 |
| `feeds` 含重复 slug 灌入反向索引 | 低 | 写入时 `seen` 集合去重 |
| `_retrieve_concept_articles` 非确定性 | 极低 | state.json scoring 决定顺序，确定性；测试改 mock `_retrieve_concept_articles` 即可控制 |
| Instrumentation 泄到生产 | 无 | 环境变量门控 |

## 显式 Out-of-Scope（后续 PR）

- **`_build_index_text` 出循环（compile.py:278）**：会改变同一次 compile run 中后续文章是否能看见前面新 propose 的 concept；需先决定语义。
- **Query-time `lint_wiki` 改读 stale report**（brainstorm.py:723 + compile.py:405）：是设计变更，要引入 staleness 模型与降级策略，单开 PR。

两点都会在本 PR 描述里写成 follow-up。
