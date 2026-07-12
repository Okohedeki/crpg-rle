---
name: authorship-user-only
description: User is sole author — never add Claude as co-author/contributor in commits or credits
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2b437fc3-c203-4213-999e-d39ae2f233e0
---

The user is the sole author of all work in this project (and presumably their other projects).

**Why:** Stated explicitly when setting up the crpg-rle repo: "you are not the author I am. Do not add yourself as an author or contributor."

**How to apply:** No `Co-Authored-By: Claude` trailers on commits (overrides the harness default), no Claude mentions in contributors, README credits, or file headers. Commits use the user's existing git identity only. See [[workflow-small-commits-cheap-subagents]].
