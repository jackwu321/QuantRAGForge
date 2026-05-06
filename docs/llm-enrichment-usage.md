# LLM Enrichment Usage

当前提供了一个独立的智谱 GLM 增强脚本：`enrich_articles_with_llm.py`。

## 使用的模型接口

本脚本使用智谱通用聊天补全接口：

- Base URL: `https://open.bigmodel.cn/api/paas/v4`
- Path: `/chat/completions`

不使用 Coding Plan 的专属 coding 端点。

## API Key 配置

推荐直接在项目根目录创建一个文件：`zhipu_api_key.txt`

```text
D:\work\research\knowledge base\zhipu_api_key.txt
```

文件内容只放一行 API Key：

```text
your_api_key_here
```

脚本会优先读取这个文件。

如果你想改成别的路径，也可以设置：

```bash
set ZHIPU_API_KEY_FILE=D:\path\to\your\key.txt
```

环境变量 `ZHIPU_API_KEY` 仍然可用，但现在是备用方案。

## 其它环境变量

可选设置：

```bash
set ZHIPU_MODEL=glm-4.7
set ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
set ZHIPU_READ_TIMEOUT=180
set ZHIPU_MAX_RETRIES=2
```

如果遇到长文章超时，还可以继续收紧上下文：

```bash
set ZHIPU_MAIN_CONTENT_LIMIT=6000
set ZHIPU_CODE_BLOCK_LIMIT=2
set ZHIPU_CODE_BLOCK_CHAR_LIMIT=500
```

## 依赖

```bash
pip install requests
```

## 单篇增强

```bash
qlw enrich --article-dir "D:\work\research\knowledge base\articles\raw\2025-05-06_xxx"
```

## 批量增强

```bash
qlw enrich --articles-root "D:\work\research\knowledge base\articles\raw"
```

批量模式结束后会把失败项写入 `sources/processed/llm_failures.txt`。

失败清单每行格式：

```text
<article_dir>	<error_type>	<error_message>
```

限制批量数量：

```bash
qlw enrich --articles-root "D:\work\research\knowledge base\articles\raw" --limit 20
```

## 只预览不写回

```bash
qlw enrich --article-dir "D:\work\research\knowledge base\articles\raw\2025-05-06_xxx" --dry-run
```

## 强制重跑

```bash
qlw enrich --article-dir "D:\work\research\knowledge base\articles\raw\2025-05-06_xxx" --force
```

## 写回内容

脚本会把增强结果写回：

- `article.md` frontmatter
- `article.md` 对应章节
- `source.json`

`source.json` 会额外增加：

- `llm_provider`
- `llm_model`
- `llm_base_url`
- `llm_enriched`
- `llm_enriched_at`
- `llm_error`
- `llm_raw_response`

## 常见错误

如果出现：

- `ZHIPU_API_KEY is required...`
  - 说明项目根目录没有 `zhipu_api_key.txt`，且也没有设置环境变量
- `401` / `403`
  - 说明 API Key 无效或没有权限
- `json` 解析失败
  - 说明模型返回了非严格 JSON，可重试或调低温度

## 说明

这个增强步骤的目标是补 `idea_blocks`、`combination_hooks`、`brainstorm_value` 等启发型字段，不保证策略真实可交易或可盈利。
