# 头脑风暴导向的知识库文档与模板优化方案

## Summary

将当前方案从“研究归档为主”进一步调整为“归档 + 可重组启发”为主。  
基于你确认的目标，系统应优先支持：

- 跨文档联想与逻辑拼接
- 混合粒度存储：保留整篇卡片，同时抽取少量关键想法块
- 生成时在“新颖性”和“合理性”之间取平衡，不追求可交易或已验证盈利

核心方向是：保留现有 `content_type` 和双模板体系，但在 schema、模板和流程里显式增加“启发点、可组合模块、可迁移关系、冲突点、组合建议”等字段，让知识库更像“投研灵感图谱”而不只是文档仓库。

## Key Changes

### 1. 调整 README 的系统定位

把知识库定位从“量化策略研究知识库”明确改成“量化投研启发型知识库”。

需要在总说明中强调：

- 目标是积累研究逻辑并支持头脑风暴，不是自动产生可实盘策略
- 生成结果的价值在于启发、迁移、组合、反向思考，而不是回测通过
- RAG 的默认用途是“召回互补逻辑”，不是“寻找唯一正确答案”

同时把成功标准从“能筛出可执行策略”改为：

- 能基于多篇材料组合出新思路
- 能清晰追溯一个新想法来源于哪些旧材料
- 能把一篇文章中的关键逻辑迁移到别的市场、频率或资产类别

### 2. 扩展 metadata schema，加入“启发型字段”

保留现有字段，并新增一组专门服务于 brainstorm 的通用字段：

```yaml
idea_blocks: []
transfer_targets: []
combination_hooks: []
contrast_points: []
novelty_axes: []
failure_modes: []
followup_questions: []
related_notes: []
source_claim_strength:
brainstorm_value:
```

字段定义固定如下：

- `idea_blocks`: 从文章中抽出的 1-5 个关键想法单元，每个单元应足够短，可单独重组
- `transfer_targets`: 该逻辑可迁移到哪些市场、资产、周期、行业或策略族
- `combination_hooks`: 该文章最适合与什么类型的文章组合，例如“可与行业轮动排序逻辑组合”
- `contrast_points`: 与哪些常见假设相反，或与哪些框架存在冲突
- `novelty_axes`: 新意来自哪里，例如信号、持有周期、资产映射、约束放松、风险定义
- `failure_modes`: 这个思路可能失效的条件，不是风控规则，而是研究上的失效边界
- `followup_questions`: 后续值得追问的研究问题
- `related_notes`: 可人工维护的关联文档路径或标题
- `source_claim_strength`: `weak`, `moderate`, `strong`，表示原文论证强度
- `brainstorm_value`: `low`, `medium`, `high`，表示是否适合作为创意原料

现有字段中建议弱化两个：

- `quality_score`：不再只表示“文章质量”，改为“对你的研究价值”
- `reusability`：保留，但语义改成“是否适合迁移和组合”，不再偏执行落地

### 3. 模板从“卡片”升级为“卡片 + 想法块”

继续保留两套模板，但都要增加一个新章节：`Idea Blocks`。  
这是本轮优化的核心，不需要把每篇文章拆碎存多份文档，只需要在单篇卡片里抽取少量可重用块。

#### `research-note-template.md` 新增章节

建议加入：

- `Idea Blocks`
- `Combination Hooks`
- `Transfer Targets`
- `Contrast Points`
- `Failure Modes`
- `Follow-up Questions`
- `Brainstorm Value`

每篇研究型文章至少抽取 2-4 个 `idea_blocks`，格式统一为短条目，例如：

- 核心排序因子是什么
- 约束条件是什么
- 能迁移到哪些别的资产或市场
- 与什么别的逻辑组合后最可能产生新思路

#### `strategy-note-template.md` 新增章节

除保留策略字段外，也加入与 brainstorm 相关的相同章节，但表达偏向：

- 哪一部分逻辑可脱离原策略独立使用
- 哪个信号块可迁移
- 哪个持有/换仓机制可以与别的因子组合
- 哪些假设是最脆弱的

默认规则：

- 模板里“Main Content”负责忠实保存原文
- `Idea Blocks` 和相关章节负责为大模型提供“重组接口”
- 后续 RAG 对生成任务优先使用这些短结构化块，再补正文上下文

### 4. 入库流程从“整篇归档”改为“整篇归档 + 关键想法抽取”

现有流程需要加入一个新的固定阶段：

1. 抓取与清洗原文
2. 分类 `content_type`
3. 生成整篇卡片
4. AI 抽取 2-5 个 `idea_blocks`
5. AI 补 `combination_hooks`、`transfer_targets`、`failure_modes`
6. 人工只确认这些“启发字段”是否胡编或过度推断
7. 再决定是否进入 `reviewed` / `high-value`

字段生成原则要改成：

- 不强迫每篇文章都像策略
- 不强迫每篇文章都有回测
- 但强迫每篇高价值文章都给出“它能被拿来做什么联想”

人工审核重点也要改：

- 这篇文章最值得保留的启发点是什么
- 哪些想法块值得后续组合
- 哪些跨市场迁移是合理的
- 哪些 AI 联想明显超出了原文边界

### 5. RAG 检索策略要从“相似召回”改成“互补召回”

现有 RAG 规则仍偏筛选，未来应明确两种检索模式：

#### 归档问答模式
用于“这篇文章讲了什么”
优先召回：
- 原文摘要
- 正文 chunk
- `research_question`
- `core_hypothesis`

#### 头脑风暴模式
用于“基于这些报告产生新想法”
优先召回：
- `idea_blocks`
- `combination_hooks`
- `transfer_targets`
- `contrast_points`
- `novelty_axes`
- `failure_modes`

头脑风暴模式的默认召回策略：

- 先按 `brainstorm_value` 和 `reusability` 过滤
- 再优先召回“内容互补而非相似”的材料
- 至少混合两类 `content_type`
- 同时限制过多 `market_review` 进入上下文
- 输出时要求显式说明“这个新想法由哪些来源逻辑拼接而成”

### 6. 新增一个“生成输出约束”文档或固定提示规范

现有文档还缺一个对大模型输出的约束说明。为了让生成结果更贴合你的用途，需要增加固定输出框架，建议单独维护一个轻量规范文档。

生成新想法时，输出至少包含：

- `Idea Title`
- `Inspired By`
- `Core Combination Logic`
- `What Is New`
- `Why It Might Make Sense`
- `What Could Break`
- `Possible Variants`

这一步很重要，因为你的目标不是验证盈利，而是拓展研究思路。没有输出约束，大模型容易退化成泛泛总结或假装给出“严谨策略”。

## Public Interfaces / Types

需要稳定的新接口只有两类。

### Metadata frontmatter 增补字段

在当前通用 schema 上增加：

```yaml
idea_blocks: []
transfer_targets: []
combination_hooks: []
contrast_points: []
novelty_axes: []
failure_modes: []
followup_questions: []
related_notes: []
source_claim_strength:
brainstorm_value:
```

建议固定枚举：

```text
source_claim_strength:
- weak
- moderate
- strong

brainstorm_value:
- low
- medium
- high
```

### 模板新增固定章节

两套模板都应包含：

- `Idea Blocks`
- `Combination Hooks`
- `Transfer Targets`
- `Failure Modes`
- `Follow-up Questions`

其中 `strategy-note-template` 额外保留：

- `Entry Rule`
- `Exit Rule`
- `Rebalance / Holding Logic`
- `Risk Control`
- `Backtest Metrics`

## Test Plan

需要用 8-12 篇样本文章验证“启发型结构”是否真的比当前版本更适合脑暴，样本应覆盖：

1. 方法论文章
2. 因子研究文章
3. 行业/主题 ETF 配置文章
4. 明确策略文章
5. 市场观察文章
6. 有很多图表但逻辑分散的文章

每篇文章至少验证：

- 能否抽出 2-5 个高质量 `idea_blocks`
- `combination_hooks` 是否能明确指出可与哪类材料拼接
- `transfer_targets` 是否能给出合理迁移方向
- `failure_modes` 是否不是泛泛风险提示，而是研究失效边界
- 生成新想法时，是否比只用正文摘要更具体、更可解释

验收标准：

- 80% 以上的高价值文章能稳定抽出至少 2 个可重组想法块
- 基于同一批材料，brainstorm 输出明显优于“泛总结”
- 每个新想法都能追溯到至少 2 个来源逻辑
- 生成结果能说明“新意来自哪里”，而不是仅复述原报告

## Assumptions

- 你的目标是“拓展研究思路”，不是“自动发现可交易 alpha”
- 知识库应服务于启发式组合与迁移，而不是只做忠实归档
- 每篇文章保留整篇卡片，同时额外抽取少量关键想法块；不在初版把单篇文章拆成多份独立文档
- `market_review` 仍然保留，但默认 `brainstorm_value` 较低，除非其中有很强的框架性洞见
- 当前双模板和 `content_type` 体系保留，不再继续扩大模板数量
