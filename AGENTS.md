# Development rules

- Read git status/log and local `.agents/handoff.md` before changes.
- One writer per checkout. Parallel code uses separate worktrees and branches.
  The user gave standing approval on 2026-10-21 for routine project merges after
  independent review, complete integrated-source checks and CI pass. Do not ask
  again for the same class of merge; preserve those gates and failed evidence.
- Preserve originals, existing changes, failed runs, and frozen evidence.
- Root architect owns the public C ABI and common build scaffold.
- Core implementation: Claude Opus 5.5, max effort for difficult numerics.
- Independent fixtures, input handling, and routine tooling: GPT-6.1 Sol.
  Difficult independent reviews may use GPT-6 Astra max.
- A cross-review is read-only: report findings, do not edit the other author's
  checkout and do not invoke the other model recursively.
- Small synthetic unit tests, compilation, and empty device smoke are allowed.
  On 2026-10-21 the user also authorized automatic scientific and performance
  execution for this project, superseding its earlier manual-launch rule.
  Freeze a finite package with input provenance, resource/time limits, logs,
  exit status and stop conditions first; a GPT-6.1 Sol subagent must manage
  execution. Preserve scientific acceptance gates. Do not kill unrelated
  processes or expand the frozen run. This approval does not cover other projects.
- Never commit credentials, private prompts/replies, personal host metadata,
  environment files, or real input data without explicit public-use provenance.
- Update ignored `.agents/handoff.md` before handing off modified files.
- Claims must distinguish implementation, test pass, real-data acceptance,
  GPU offload, and measured performance.
