---
name: kb-health-check
description: 检查 wiki 健康状态、给出修复建议
version: 1
triggers:
  - 健康检查
  - 库状态
  - audit
  - wiki 状态
  - lint
requires_user_decision: false
tools_used:
  - audit_wiki
  - compile_wiki
---

## When to use
- 用户主动问"知识库健康吗"
- 上手新 KB 前体检
- brainstorm 前担心 wiki 陈旧 / 有 lint 问题
- compile_wiki / embed_knowledge 报错后定位

## Steps
1. audit_wiki() — 拿 lint 报告
2. 若报告含阻塞或高严重度问题，按类别总结给用户
3. 建议下一步（**不自动执行**）：
   - 干净 → 报"健康"，结束
   - 文章变了 wiki 没跟上 → 建议 compile_wiki(mode='incremental')
   - alias 冲突 / oversized concepts → 报告人工修缮

## Notes
- This skill is read-only by default. Any suggested write action (compile_wiki) requires explicit user approval before execution.
- compile_wiki 在 tools_used 里只是"建议的后续工具"，不是默认执行的一部分
- audit_wiki 输出 summary 的措辞可能变化，按"高严重度/阻塞"宽分类即可，别死板
