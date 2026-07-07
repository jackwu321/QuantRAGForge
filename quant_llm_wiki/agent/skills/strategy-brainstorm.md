---
name: strategy-brainstorm
description: 模糊策略方向的多轮沟通 SOP：入口路由 → 澄清 → 知识库定向 → 提案 → 细化 → 收敛落盘简报
version: 3
triggers:
  - 策略方向
  - 脑暴
  - 聊聊策略
  - 有个想法
  - 模糊方向
  - 结合点
  - brainstorm
requires_user_decision: true
tools_used:
  - list_concepts
  - read_wiki
  - query_knowledge_base
  - deep_brainstorm
  - record_note
  - record_decision
  - set_note_status
  - save_strategy_brief
  - add_task
---

## When to use
用户提出模糊或方向性的策略想法（"想看看 X 和 Y 有没有结合点"）、要求继续/细化某个已有方向、或要求把讨论收敛成简报。

## 第 0 步 — 入口路由（先做这一步）
阶段是状态库，不是流水线。判断用户处于哪个阶段，**从最晚可行的阶段进入**；
工作记忆 preamble 里已有的状态（decisions / open notes / 既往简报）视为已完成的前序阶段，不重走。

| 用户消息形态 | 进入 |
|---|---|
| 全新且模糊的方向（"想看看宏观周期和商品期限结构有没有结合点"） | 阶段 1 |
| 方向具体、约束自带（"A股ETF周频动量，给几个组合思路"） | 阶段 3（可零澄清） |
| 续接已有方向要细化（"上次那个期限结构方向，直接细化成回测思路"） | 阶段 4 |
| 要求收口（"出个简报吧"） | 阶段 5 |

- 路由判断不询问用户（禁止"你想从哪个阶段开始？"）。
- 跨会话续接时，先用一句话复述续接点（方向 + 已确认约束）再继续，例：
  "续接：商品期限结构方向，约束周频/国内品种——直接进入回测思路细化"。

## Steps
1. **澄清**（跳过条件：约束已在 Recent Decisions 里，或用户消息已给全）
   - 全程至多一轮澄清、单轮至多 2 问；能合理默认的维度直接默认并显式声明
     （"默认 A股 ETF / 周频，不对请纠正"）；答复后仍有缺口 → 带显式假设前进，不二次追问
   - 用户确认的约束 → record_decision
   - 本阶段不写 direction note（见 Notes 的延迟写规则）
   - [PAUSE]
2. **知识库定向**（仅当方向首次出现，或用户主动问"知识库有什么"；续接方向跳过）
   - 进入本阶段说明方向已获用户推进：若该方向尚无 direction note → record_note(kind='direction')
   - 交叉方向分腿映射：每条腿单独 list_concepts(status='stable') + read_wiki(target=slug)
   - 只下"概念层覆盖"结论；"知识库整体覆盖太薄 / 建议补 ingest"必须等阶段 3 检索结果
     之后再说（文章块层只有 query_knowledge_base 探得到）；建议 ingest 时不自动执行
   - [PAUSE] 等用户选切入点
3. **提案**（跳过条件：用户已锁定具体想法、只要细化）
   - 若该方向尚无 direction note → record_note(kind='direction')
   - 把方向 + 已确认约束组合成精炼 query → deep_brainstorm(query=...)
     （内部自动多轮"生成→批判→精炼"，产出已带证据引用与演化日志；
     结果里的 ⚠️ 降级标注原样告知用户）
   - 呈现幸存的候选想法，逐个带来源引用、所受批判与 failure modes；
     全灭时如实呈现各死因，回到阶段 2 换切入点或建议放宽方向
   - 用户明确要求快/省（"快速来一版"）时可退回单发：
     query_knowledge_base(mode='brainstorm')，并说明未经批判循环
   - [PAUSE] 等反馈
4. **细化**（可循环）
   - 按用户反馈换角度重组 query 再检索，或 read_wiki 深挖具体概念
   - 用户确认有价值的中间结论 → record_note(kind='hypothesis')
   - 用户否定某方向 → record_decision（含否定理由）+ 该方向 note → set_note_status(status='rejected')
   - 用户选定深入方向 → record_decision
   - [PAUSE]，本阶段可重复多轮
5. **收敛落盘**（仅当用户明确示意收敛；你认为已收敛时至多**询问**"要不要出简报"，
   禁止自行调用 save_strategy_brief）
   - 综合全程 + memory 既往状态（不只本次会话）生成简报，结构：
     方向与约束 / 候选想法（来源 + failure modes）/ 已否定方向及理由 /
     选定深入的方向 / 依据的 wiki 概念清单 / 下一步建议
   - save_strategy_brief(topic=方向短标题, content=简报全文)
   - 已吸收进简报的 notes → set_note_status(status='folded')
   - 后续待办：先向用户提出具体 task 文本，用户对**该文本**确认后才 add_task
     （"好的 / 继续"这类泛确认不算）
   - 若 KB 配置了 handoff schema（.qlw/handoff_schema.json），save_strategy_brief
     会自动同时产出经校验的 .yaml（handoff 双产物）；yaml 产出失败只影响 yaml，
     md 简报为兜底真相，把返回串里的 warning 如实告知用户

## Notes
- **降级模式（无 memory 工具）**：read_skill 返回的 degraded_note 列出本会话未注册的工具
  （`--no-memory` 或 memory 损坏降级）时，跳过所有调用它们的步骤——record_note /
  record_decision / set_note_status / add_task 一律不调用、不替代；其余步骤照常，
  约束与中间结论靠对话上下文维持，save_strategy_brief 收敛简报仍可用。
- **direction note 延迟写**：开场不写。方向"成形"才记——用户在澄清后继续推进（进入
  阶段 2/3）、或带具体方向直接进入阶段 3/4、或明确要求记下。闲聊式开场不留 memory 残留。
- 不编造回测结果；每个想法标注来源；wiki 未覆盖如实说，不要硬凑。
- 过程状态进 notes，绝不进 wiki；检索痕迹不进 memory（逐轮输出文件和 query log 已是痕迹）。
- memory 是用来读的：不重新提议已否定（Recent Decisions）的方向，不重问已确认的约束。
- set_note_status 只对本会话可见的 note id 调用（preamble 的 `#id` 行，或本会话
  record_note 返回的 id）；id 不可见时不要猜，请用户用 `qlw memory notes` / `note-status` 处理。
