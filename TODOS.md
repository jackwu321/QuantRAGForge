# TODOS

## Agent / Skills

(none)

## Completed

### strategy-brainstorm under --no-memory references unregistered tools (2026-06-12, v0.7.1)
Was P2, deferred from v0.7.0. Fixed with both candidate approaches:
`create_agent` publishes the session's tool set to the skill registry
(`set_runtime_tool_names`); `list_skills`/`read_skill` annotate each skill
with `unavailable_tools` and a `degraded_note` telling the agent to skip
steps that call unregistered tools. The strategy-brainstorm SOP (v2) also
carries an explicit degraded-mode note. Skills are annotated, not hidden —
the SOP still works under --no-memory minus the memory writes.
