---
name: concept-review
description: 审核 compile_wiki 提案的低置信度概念
version: 1
triggers:
  - 审核概念
  - proposed 概念
  - concept review
  - 批准概念
  - 概念决议
requires_user_decision: true
tools_used:
  - list_concepts
  - set_concept_status
  - compile_wiki
---

## When to use
compile_wiki 报告"N 个低置信度概念被放入 exception queue"，或用户主动要求审核概念。

## Steps
1. list_concepts(status='proposed') — 展示待审核概念
2. [PAUSE] 把列表交给用户，等用户逐一决定。**必须停**
3. set_concept_status(slug=..., status=..., reason=...) — 每个 slug 调一次
   - stable — 批准 proposed 概念，进入 wiki 主体
   - deprecated — 标记弃用，文件保留以可追溯
   - deleted — 删除文件；**只在用户明确说"删除"时使用**
4. 若有 stable 化 → 询问用户是否现在 compile_wiki(mode='incremental')。**只在用户预授权或当场同意时才跑**（compile_wiki 会写盘）

## Notes
- proposed 概念在批准前不进 brainstorm 检索
- set_concept_status 一次只接受一个 slug，不是批量
