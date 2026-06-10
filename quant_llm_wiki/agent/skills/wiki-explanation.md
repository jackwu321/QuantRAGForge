---
name: wiki-explanation
description: 用户要"解释/梳理/总结某概念"时的路由
version: 1
triggers:
  - 解释
  - 梳理
  - 总结
  - 知识库怎么说
  - explain
requires_user_decision: false
tools_used:
  - list_concepts
  - read_wiki
  - query_knowledge_base
---

## When to use
用户问"解释 X" / "梳理 Y" / "知识库对 Z 怎么说"。优先 wiki 层（凝练 + 有 source 引用），向量库兜底。

## Steps
1. list_concepts(status='all') — 看所有概念
2. 主题能映射到 stable slug → read_wiki(target=slug)
3. 只映射到 proposed slug → read_wiki(target=slug)，回复中**提醒"该概念尚未稳定"**
4. 无法映射 → read_wiki(target='index') 查目录
5. 仍找不到 → query_knowledge_base(query=..., mode='ask') 兜底

## Notes
- 不要先冲向量库再补 wiki — wiki 概念已凝练
- 返回 read_wiki 内容时做**解释性总结**，不要机械全文转贴；保留 source 引用信息
- 找不到时如实说"知识库未覆盖"，别编
