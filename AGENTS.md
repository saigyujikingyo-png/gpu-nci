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
- The latest user-supplied execution instructions restore manual launch:
  agents prepare and review finite packages and perform only necessary light
  syntax, input, hash and empty-control checks; do not launch scientific or
  performance calculations. The user closes resource-consuming applications
  and starts the independent launcher. A GPT-6.1 Sol agent prepares the bounded
  controller and later checks actual receipts. Preserve input provenance,
  limits, stop controls, logs, exit status, failed evidence and acceptance gates.
  Do not kill unrelated processes, expand a frozen run or replay a used package.
- Never commit credentials, private prompts/replies, personal host metadata,
  environment files, or real input data without explicit public-use provenance.
- Update ignored `.agents/handoff.md` before handing off modified files.
- Claims must distinguish implementation, test pass, real-data acceptance,
  GPU offload, and measured performance.
