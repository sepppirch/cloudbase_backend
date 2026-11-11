@AGENTS.md

## Claude Code specifics

- Coding: use the Opus model.
- Reviews, exploration and other non-coding subagent/workflow work: use
  Sonnet or Haiku (`model: "sonnet"` / `"haiku"` on Agent and workflow `agent()` calls).
