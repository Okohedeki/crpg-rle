---
name: workflow-small-commits-cheap-subagents
description: User wants small frequent commits and cheaper-model subagents to save tokens
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2b437fc3-c203-4213-999e-d39ae2f233e0
---

Two workflow rules the user set for the crpg-rle project (2026-07-09):

1. **Small, frequent commits** — one logical change per commit, committed as completed, not batched.
2. **Token economy** — delegate self-contained implementation/research chunks to subagents on cheaper models (Agent tool `model: "opus"` or `"sonnet"`); reserve main-model reasoning for architecture and debugging.

**Why:** User asked for this explicitly when approving the implementation plan.

**How to apply:** Commit after each coherent unit of work. When spawning agents for boilerplate, parsing, test scaffolding, or docs, pass a cheaper `model` param. See [[authorship-user-only]] and [[crpg-rle-project]].
