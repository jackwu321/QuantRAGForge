# Ingestion Workflow

这是公众号文章入库的最小可用流程。目标不是一次做满，而是先形成稳定流水线，并确保不同类型文章用合适的模板表达，同时支持后续头脑风暴和逻辑重组。

## 阶段 1: 原始采集

输入：公众号文章链接

输出：

- `raw.html`
- `source.json`
- 图片文件
- 初步分类结果

步骤：

1. 记录原始链接到 `sources/inbox/links.txt`
2. 抓取页面 HTML
3. 解析标题、公众号名、发布时间、正文区块
4. 下载正文图片到文章目录或统一 `assets/images/`
5. 保留原始 HTML，避免后续解析规则变化时无法重跑

## 阶段 2: 内容分类

目标：先判断“这是一篇什么类型的知识对象”，再决定模板。

分类枚举：

- `methodology`
- `strategy`
- `allocation`
- `market_review`

默认规则：

- 解释研究框架、模型思想、因子逻辑，用 `methodology`
- 有明确交易逻辑、持有逻辑、换仓规则或回测执行框架，用 `strategy`
- 讨论 ETF 配置、行业轮动、组合构建、权重分配，用 `allocation`
- 偏时点评述、复盘、专题观察，用 `market_review`

模板选择规则：

- `methodology` / `allocation` / `market_review` 使用 `research-note-template.md`
- `strategy` 使用 `strategy-note-template.md`

## 阶段 3: 内容清洗

目标：把“网页文本”变成“研究材料”

处理规则：

- 删除推荐阅读、点赞区、公众号名片、广告文本
- 保留段落、小标题、列表
- 把图片写成 Markdown 引用
- HTML 原生代码块转为 fenced code block
- 对明显是代码截图的图片标记为 `ocr_candidate`

## 阶段 4: 知识增强

目标：补齐适合 RAG 和头脑风暴生成的字段

处理内容：

- 生成 `content_type`
- 生成 `summary`
- 抽取 `research_question`
- 抽取 `core_hypothesis`
- 抽取 `signal_framework`
- 抽取 `application_scope`
- 抽取 `constraints`、`evidence_type`、`reusability`
- 抽取 2-5 个 `idea_blocks`
- 补充 `transfer_targets`、`combination_hooks`、`contrast_points`
- 补充 `novelty_axes`、`failure_modes`、`followup_questions`
- 评估 `source_claim_strength` 和 `brainstorm_value`
- 抽取 `strategy_type`、`market`、`asset_type`、`holding_period`
- 若为 `strategy`，再提炼 `entry_rule`、`exit_rule`、`rebalance_logic`
- 若为 `strategy`，抽取 `risk_control`
- 若为 `strategy`，提取回测指标到 `backtest_metrics`
- 对图表和代码截图进行 OCR 或视觉摘要

## 阶段 5: 人工审核

人工只做高价值动作，不从零录入：

- 校验 `content_type` 是否正确
- 校验核心假设和适用场景是否正确
- 校验市场和周期是否正确
- 校验 `idea_blocks` 是否足够短、准、可重组
- 校验 `combination_hooks`、`transfer_targets`、`failure_modes` 是否没有过度联想
- 若为策略类，校验关键规则和风控有没有被模型误读
- 判断文章是否可复用，并确认 `reusability`
- 判断是否具有足够的 `brainstorm_value`
- 判断是否进入 `reviewed/` 或 `high-value/`
- 给出 `quality_score`

## 初版处理优先级

建议按这个顺序做，不要一开始全自动：

1. 文本抓取稳定
2. 图片下载稳定
3. 分类规则稳定
4. Markdown 模板固定
5. AI 预填字段
6. AI 抽取想法块和组合钩子
7. OCR 代码截图
8. 图表视觉摘要
9. 批量入库

## 建议的单篇目录结构

```text
articles/raw/2025-11-08_stat_arb_case/
  article.md
  raw.html
  source.json
  images/
    001.png
    002.png
```

## RAG 入库建议

初版不要把所有原始材料都入向量库，优先使用：

- `articles/reviewed/`
- `articles/high-value/`

推荐把以下内容一起送入 RAG：

- 标题
- 摘要
- `content_type`、`reusability` 等结构化字段
- `idea_blocks`、`combination_hooks`、`transfer_targets`
- 正文分块
- 核心假设与信号框架
- 图表摘要
- 可用代码块

## 文章分块建议

- 按标题分段优先
- 每块保留 500-1200 中文字符
- 每块携带元数据：标题、文章路径、`content_type`、策略类型、市场、周期、`reusability`
- `idea_blocks` 额外单独成 chunk，优先用于 brainstorm 检索
- 代码块单独成 chunk
- 图表 OCR/摘要单独成 chunk

## 两种检索模式

### 归档问答模式

- 用于“这篇文章讲了什么”
- 优先召回原文摘要、正文 chunk、`research_question`、`core_hypothesis`

### 头脑风暴模式

- 用于“基于这些报告产生新想法”
- 优先召回 `idea_blocks`、`combination_hooks`、`transfer_targets`、`contrast_points`、`novelty_axes`、`failure_modes`

## 生成新策略想法时的默认检索规则

- 先按 `brainstorm_value` 和 `reusability` 过滤
- 再优先召回内容互补而非内容相似的材料
- 至少混合两类 `content_type`
- 优先召回 `methodology + allocation + strategy`
- 弱化 `market_review`
- 优先使用 `reusability != idea_only`
- 优先组合不同 `holding_period` 或不同 `strategy_type` 的知识对象
- 输出时明确说明新想法来自哪些来源逻辑的拼接

## 初版成功标准

- 能稳定把 20-50 篇公众号文章落地为本地 Markdown
- 每篇都有最小字段和明确的 `content_type`
- 能按 `content_type`、策略类型和市场筛选
- 能让模型基于这些材料输出“新策略想法”而不是泛泛总结
- 能追溯一个新想法对应的来源逻辑和启发块
