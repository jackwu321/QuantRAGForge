# TODOS

## Agent / Skills

### strategy-brainstorm under --no-memory references unregistered tools
**Priority:** P2
The strategy-brainstorm SOP instructs calling memory tools (record_note,
record_decision, set_note_status, add_task) at nearly every stage, but
`qlw agent --no-memory` (and the corrupt-sqlite degraded mode) runs the graph
without them — the agent hits tool-not-found errors mid-conversation.
Noticed on branch feat/strategy-brainstorm (v0.7.0 adversarial review,
Claude + Codex agreed). Candidate fixes: filter the skill registry by the
runtime tool set at list_skills time, or add a degraded-mode branch to the
SOP. Deferred from v0.7.0 — SOP wording iterates post-release by design.

## Completed
