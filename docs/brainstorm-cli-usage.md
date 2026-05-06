# Brainstorm CLI Usage

当前提供两个外部命令：`embed_knowledge_base.py` 和 `brainstorm_from_kb.py`。

## 设计定位

- `Obsidian` 负责阅读、筛选、人工修正 frontmatter
- `embed_knowledge_base.py` 负责为 `reviewed/high-value` 建立或更新本地向量索引
- `brainstorm_from_kb.py` 负责读取知识库并发起问答或脑暴
- 默认流程先做 frontmatter 过滤，再做 `keyword` / `vector` / `hybrid` 检索

## 依赖

```bash
pip install requests chromadb
```

并确保项目根目录有：

```text
zhipu_api_key.txt
```

## 建立向量索引

```bash
qlw embed
```

常用命令：

```bash
qlw embed --source-dir reviewed,high-value
qlw embed --dry-run
qlw embed --force
```

默认向量库存储在：

```text
vector_store/
```

## 问答模式

```bash
qlw ask --query "哪些文章讨论行业轮动和ETF配置？"
```

## 脑暴模式

```bash
qlw brainstorm --query "基于行业轮动和风险预算，给我5个新的ETF配置想法"
```

## 检索模式

支持三种检索模式：

- `keyword`: 只用当前关键词重叠排序
- `vector`: 只用向量检索
- `hybrid`: 关键词和向量检索做 RRF 融合，默认值

示例：

```bash
qlw brainstorm --query "行业轮动和风险预算" --retrieval hybrid
qlw brainstorm --query "行业轮动和风险预算" --retrieval vector
qlw brainstorm --query "行业轮动和风险预算" --retrieval keyword
```

如果 `chromadb` 未安装、向量库缺失、embedding API 超时或向量检索为空，脚本会自动回退到 `keyword`。

## 常用过滤参数

```bash
qlw brainstorm ^
  --query "基于行业轮动和风险预算，给我5个新的ETF配置想法" ^
  --content-type allocation ^
  --market a_share ^
  --asset-type etf ^
  --strategy-type allocation_rotation ^
  --brainstorm-value high ^
  --top-k 8 ^
  --retrieval hybrid
```

支持的常用参数：

- `--kb-root`
- `--source-dir reviewed,high-value`
- `--content-type`
- `--market`
- `--asset-type`
- `--strategy-type`
- `--brainstorm-value`
- `--top-k`
- `--retrieval`
- `--output-file`
- `--dry-run`

## 输出位置

默认输出到：

```text
outputs/brainstorms/
```

文件名类似：

```text
YYYY-MM-DD_<query_slug>_brainstorm.md
YYYY-MM-DD_<query_slug>_ask.md
```

## Dry Run

如果你想先看看检索到哪些上下文，而不调用模型：

```bash
qlw brainstorm --query "行业轮动和风险预算" --retrieval hybrid --dry-run
```

## 推荐工作流

1. 批量抓取到 `articles/raw/`
2. 批量跑 LLM 增强
3. 在 Obsidian 中人工修正 frontmatter
4. 用 `sync_articles_by_status.py` 同步到 `reviewed/` 和 `high-value/`
5. 运行 `embed_knowledge_base.py` 更新向量索引
6. 用 `brainstorm_from_kb.py --retrieval hybrid` 发起问答或脑暴
