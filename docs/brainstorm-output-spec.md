# Brainstorm Output Spec

这份文档定义了基于知识库生成新策略想法时的最小输出约束。目标不是验证盈利，而是确保输出具备启发性、可追溯性和可解释性。

## 适用场景

- 基于多篇文章做策略脑暴
- 基于互补逻辑组合出新研究方向
- 基于已有框架迁移到新市场、资产或周期

## 输出结构

每个新想法至少包含以下字段：

```text
Idea Title
Inspired By
Core Combination Logic
What Is New
Why It Might Make Sense
What Could Break
Possible Variants
```

## 字段要求

- `Idea Title`: 一个短标题，表达新想法的核心
- `Inspired By`: 明确列出来源文章、想法块或逻辑片段
- `Core Combination Logic`: 说明是如何把多个来源逻辑拼接起来的
- `What Is New`: 明确指出新意来自哪里，如新市场映射、持有周期变化、约束变化、因子组合变化
- `Why It Might Make Sense`: 给出高层逻辑依据，不假装已经验证
- `What Could Break`: 说明失效边界或最脆弱的假设
- `Possible Variants`: 给出 2-3 个可继续扩展的变体方向

## 输出约束

- 不把“启发”写成“已验证有效”
- 不编造不存在于来源中的回测结果
- 至少引用 2 个来源逻辑，除非任务明确要求单篇延展
- 优先组合互补逻辑，而不是改写同一篇文章
- 如果想法主要来自单篇文章，应明确标注是“延展”，不是“组合”

## 推荐提示使用方式

- 先检索 `idea_blocks`、`combination_hooks`、`transfer_targets`
- 再补充 `summary`、`core_hypothesis` 和正文 chunk 作为上下文
- 要求模型先列出“来源逻辑”，再生成“新想法”
