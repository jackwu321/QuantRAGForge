---
name: full-ingest
description: 入库一批新文章的完整流水线
version: 1
triggers:
  - 入库
  - ingest
  - 处理这批 URL
  - 这些文章加入知识库
  - 批量入库
requires_user_decision: true
tools_used:
  - ingest_article
  - enrich_articles
  - review_articles
  - set_article_status
  - compile_wiki
  - embed_knowledge
---

## When to use
用户给出一批 URL / HTML / PDF，要走完整入库流程。

## Steps
1. ingest_article(urls=... 或对应入参)
2. enrich_articles(status_filter='raw', limit=...) — 优先只处理本次新增。若用户未指定 limit 且 raw/ 中明显含历史未处理文章，**简短说明范围**（如"将 enrich 当前 raw/ 下所有 N 篇"）后继续；用户已明确说"完整入库"且未表达异议时**不要**在此停顿等确认
3. [PAUSE] review_articles(source_dir='raw') — 把列表交给用户决定 reviewed / high_value / rejected。**必须停**，不替用户判
4. set_article_status(article_paths=..., status=..., reason=...) — 只对用户已决定的文章调用；未决定的保持 raw
5. compile_wiki(mode='incremental')
6. embed_knowledge(force=false)

## Notes
- 每步完成后报告再进下一步，不一口气跑完
- compile_wiki 报 N 个 proposed 概念 → 切到 concept-review skill
- ingest_article 全失败时不继续后续步骤
- 状态名严格使用 reviewed / high_value / rejected（下划线，不是连字符）
- ingest_article（agent tool）只写 raw/，**不会**像 CLI `qlw ingest` 那样自动 compile+embed；step 5/6 必须按本 SOP 执行，不存在重复
