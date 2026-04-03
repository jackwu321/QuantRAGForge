# Metadata Schema

以下是公众号文章的初版字段规范。建议使用统一的 YAML frontmatter，再按 `content_type` 选择模板。这样方法论、配置框架和可执行策略都能落在同一知识体系内，并能为后续头脑风暴提供可重组的启发块。

## 核心分类枚举

```text
content_type:
- methodology
- strategy
- allocation
- risk_control
- market_review

market:
- a_share
- hk_equity
- us_equity
- commodity_futures
- index_futures
- bond
- fx
- crypto
- multi_asset
- general

asset_type:
- stock
- etf
- future
- option
- bond
- currency
- crypto_asset
- index
- sector_basket
- multi_asset
- general_time_series

reusability:
- idea_only
- adaptable
- directly_implementable

source_claim_strength:
- weak
- moderate
- strong

brainstorm_value:
- low
- medium
- high
```

建议分类原则：

- `methodology`: 解释研究框架、模型思想、因子逻辑
- `strategy`: 可以提炼出明确交易逻辑、持有逻辑或回测执行框架
- `allocation`: 行业轮动、主题轮动、ETF 配置、组合构建、权重分配
- `risk_control`: 风控框架、仓位控制、回撤管理、波动率目标、风险预算、对冲覆盖
- `market_review`: 市场观察、阶段复盘、专题点评，可复用性通常较弱

## 通用字段

所有文章统一使用以下基础字段：

```yaml
title:
source_url:
source_type: wechat_mp
account:
author:
publish_date:
ingested_at:
status:
content_type:

research_question:
core_hypothesis:
signal_framework:
application_scope:
constraints: []
evidence_type: []
reusability:
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

strategy_type: []
market: []
asset_type: []
holding_period:
tags: []
summary:
quality_score:
confidence:

code_quality:
image_insight_level:
```

说明：

- `status`: `raw` / `reviewed` / `high_value`
- `research_question`: 这篇文章试图回答什么问题
- `core_hypothesis`: 核心逻辑、理论假设或驱动机制
- `signal_framework`: 信号、排序、筛选、打分、轮动或决策框架
- `application_scope`: 适用市场、标的、频率和场景
- `constraints`: 容量、交易成本、数据依赖、风格暴露、行业约束等
- `evidence_type`: `theory`, `backtest`, `case_study`, `chart_evidence`, `code_demo`
- `reusability`: `idea_only` / `adaptable` / `directly_implementable`，表示是否适合迁移和组合
- `idea_blocks`: 从文章中抽出的 1-5 个关键想法单元，每个单元应足够短，可单独重组
- `transfer_targets`: 该逻辑可迁移到哪些市场、资产、周期、行业或策略族
- `combination_hooks`: 最适合与什么类型的文章或逻辑组合
- `contrast_points`: 与哪些常见假设相反，或与哪些框架存在冲突
- `novelty_axes`: 新意来自哪里，如信号、周期、资产映射、约束放松、风险定义
- `failure_modes`: 这个思路可能失效的条件，强调研究失效边界而不是风控规则
- `followup_questions`: 后续值得追问的研究问题
- `related_notes`: 可人工维护的关联文档路径或标题
- `source_claim_strength`: 原文论证强度，`weak` / `moderate` / `strong`
- `brainstorm_value`: 作为创意原料的价值，`low` / `medium` / `high`
- `strategy_type`: 使用固定词表的策略范式标签，建议从下方标准词表中选择，避免随意造词
- `market`: 使用固定词表的市场标签，建议从下方标准词表中选择
- `asset_type`: 使用固定词表的标的类型标签，建议从下方标准词表中选择
- `holding_period`: 周期，如 `intraday`, `swing`, `weekly`, `monthly`
- `code_quality`: `none` / `partial` / `usable` / `ocr_only`
- `image_insight_level`: `none` / `saved_only` / `ocr_done` / `vision_summary_done`
- `quality_score`: 1-5，表示对研究工作的整体价值，不仅仅是文章质量
- `confidence`: AI 预填字段的整体置信度，建议 0-1


## Content Type 标准词表

```yaml
content_type:
  - methodology
  - strategy
  - allocation
  - risk_control
  - market_review
```

说明：

- `methodology`: 方法论、研究框架、模型介绍、因子逻辑
- `strategy`: 存在明确交易逻辑、持有逻辑或回测执行框架
- `allocation`: 配置框架、行业轮动、组合构建、ETF 配置
- `risk_control`: 风控框架、仓位控制、回撤控制、波动率目标、风险预算、对冲覆盖
- `market_review`: 市场观察、复盘、专题分析

填写规则：

- 每篇文章只填写 `1` 个 `content_type`
- 按主要用途归类，不按是否提到交易案例归类
- 框架解释为主的文章优先标 `methodology`
- 权重分配、轮动、ETF 配置优先标 `allocation`
- 风控方法、风险指标、组合风险管理优先标 `risk_control`
- 纯观察和结论复盘优先标 `market_review`

## Market 标准词表

```yaml
market:
  - a_share
  - hk_equity
  - us_equity
  - commodity_futures
  - index_futures
  - bond
  - fx
  - crypto
  - multi_asset
  - general
```

说明：

- `a_share`: A 股
- `hk_equity`: 港股
- `us_equity`: 美股
- `commodity_futures`: 商品期货
- `index_futures`: 股指期货
- `bond`: 债券
- `fx`: 外汇
- `crypto`: 加密资产市场
- `multi_asset`: 明确跨多个市场或资产大类
- `general`: 通用方法，不明显绑定某一市场

填写规则：

- 每篇文章建议填写 `1-3` 个标签
- 优先填写主要适用市场，不要把文中顺带提到的市场都写上
- 通用建模文章可填 `general`
- 跨市场配置或迁移研究可填 `multi_asset`

## Asset Type 标准词表

```yaml
asset_type:
  - stock
  - etf
  - future
  - option
  - bond
  - currency
  - crypto_asset
  - index
  - sector_basket
  - multi_asset
  - general_time_series
```

说明：

- `stock`: 个股
- `etf`: ETF
- `future`: 期货合约
- `option`: 期权
- `bond`: 债券
- `currency`: 货币或汇率序列
- `crypto_asset`: 加密资产标的
- `index`: 指数
- `sector_basket`: 行业篮子、主题篮子或板块组合
- `multi_asset`: 多资产组合
- `general_time_series`: 通用时序对象，不绑定具体资产类型

填写规则：

- 每篇文章建议填写 `1-3` 个标签
- 优先填写研究直接作用的标的类型
- 通用预测模型可填 `general_time_series`
- 真正覆盖多类资产时再填 `multi_asset`

## Strategy Type 标准词表

建议初版统一使用以下标签：

```yaml
strategy_type:
  - trend_following
  - mean_reversion
  - cross_sectional
  - time_series_forecast
  - factor_model
  - allocation_rotation
  - event_driven
  - stat_arb
  - pair_trading
  - options_volatility
  - macro_regime
  - ml_prediction
  - risk_model
  - risk_control
  - volatility_targeting
  - drawdown_control
  - position_sizing
  - regime_filter
  - execution_microstructure
  - seasonal_calendar
  - momentum
  - carry
  - breakout
  - engineering_system
```

说明：

- `trend_following`: 趋势跟随
- `mean_reversion`: 均值回归
- `cross_sectional`: 横截面排序、相对强弱、选股或选行业
- `time_series_forecast`: 单序列或单资产时序预测
- `factor_model`: 因子构建、因子打分、因子组合
- `allocation_rotation`: 资产配置、行业轮动、ETF 轮动
- `event_driven`: 事件驱动
- `stat_arb`: 统计套利
- `pair_trading`: 配对交易
- `options_volatility`: 期权与波动率相关策略
- `macro_regime`: 宏观状态或 regime 切换
- `ml_prediction`: 机器学习预测模型
- `risk_model`: 风险建模、风险预算、协方差或波动率控制
- `risk_control`: 泛化风控方法、风险管理模块
- `volatility_targeting`: 波动率目标控制
- `drawdown_control`: 回撤控制
- `position_sizing`: 仓位管理
- `regime_filter`: 风险开关、市场状态过滤
- `execution_microstructure`: 交易执行、订单流、盘口微观结构
- `seasonal_calendar`: 季节效应、日历效应
- `momentum`: 动量
- `carry`: Carry、期限结构、展期收益
- `breakout`: 突破逻辑

填写规则：

- 每篇文章建议填写 `1-3` 个标签
- 优先选择核心范式，不要因为相关文章提到就全部打上
- 方法论文章也可以填写 `strategy_type`，例如 `content_type: methodology` 与 `strategy_type: ml_prediction` 并不冲突
- 工程型文章可填写 `strategy_type: engineering_system`，用于标记量化框架、回测系统和研究基础设施
- 若后续高频出现新流派，再扩词表，不建议在单篇文章里临时发明新标签

示例：

- 行业轮动 / ETF 配置：`allocation_rotation`, `cross_sectional`
- 因子选股报告：`factor_model`, `cross_sectional`
- CTA 趋势策略：`trend_following`, `breakout`
- 单变量时序预测模型：`ml_prediction`, `time_series_forecast`
- 风控框架 / 回撤控制：`risk_control`, `drawdown_control`
- 风险预算 / 波动率目标：`risk_control`, `volatility_targeting`

## 策略类附加字段

以下字段主要在 `content_type = strategy` 时推荐填写，其他类型允许留空：

```yaml
entry_rule:
exit_rule:
rebalance_logic:
risk_control: []
backtest_metrics: {}
```

说明：

- `entry_rule`: 开仓或建仓逻辑
- `exit_rule`: 平仓或退出逻辑
- `rebalance_logic`: 调仓频率、换仓条件、持有/更新逻辑
- `risk_control`: 止损、仓位约束、波动率过滤等风控逻辑
- `backtest_metrics`: 回测指标对象

对于 `allocation` 类文章：

- 可以填写 `rebalance_logic`
- 不要求出现传统 `entry_rule / exit_rule`

对于 `methodology`、`risk_control` 和 `market_review`：

- 默认不要求填写交易字段

## 回测指标建议格式

```yaml
backtest_metrics:
  annual_return:
  sharpe:
  max_drawdown:
  win_rate:
  turnover:
  sample_period:
```

## 字段填充方式

### 自动提取

- `title`
- `source_url`
- `account`
- `author`（若页面可取）
- `publish_date`
- `ingested_at`
- 图片列表
- HTML 中可识别的代码块

### AI 预填

- `content_type`
- `research_question`
- `core_hypothesis`
- `signal_framework`
- `application_scope`
- `constraints`
- `evidence_type`
- `reusability`
- `idea_blocks`
- `transfer_targets`
- `combination_hooks`
- `contrast_points`
- `novelty_axes`
- `failure_modes`
- `followup_questions`
- `source_claim_strength`
- `brainstorm_value`
- `strategy_type`
- `market`
- `asset_type`
- `holding_period`
- `summary`
- `confidence`

仅当 `content_type = strategy` 时，额外预填：

- `entry_rule`
- `exit_rule`
- `rebalance_logic`
- `risk_control`
- `backtest_metrics`

### 人工确认

- `content_type` 是否正确
- `reusability` 是否合理
- `idea_blocks` 是否足够具体、可重组、没有脱离原文
- `combination_hooks` 和 `transfer_targets` 是否合理
- `failure_modes` 是否反映研究失效边界而非泛泛风险
- `quality_score`
- `status`
- AI 预填内容中的错误项
- OCR 提取代码是否可用
- 图表信息是否值得补充摘要

## 命名建议

- 文章目录名: `YYYY-MM-DD_标题简写`
- Markdown 文件名: `article.md`
- 原图目录: `images/`
- 原始数据: `source.json`, `raw.html`

## 为什么要这些字段

这些字段让后续系统不仅能“找到相关文章”，还能区分知识对象并做启发式组合，例如：

- 找出所有 `allocation + etf + monthly`
- 排除 `reusability = idea_only` 的纯观点文章
- 组合 `methodology + strategy` 形成新研究方向
- 单独筛出“研究框架”和“可执行策略”
- 让模型优先读取 `idea_blocks` 和 `combination_hooks`，而不是只复述摘要
