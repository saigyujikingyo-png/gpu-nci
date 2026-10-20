# Development rules

- Read git status/log and local `.agents/handoff.md` before changes.
- One writer per checkout. Parallel code uses separate worktrees and branches.
  Do not merge branches without the user's confirmation.
- Preserve originals, existing changes, failed runs, and frozen evidence.
- Root architect owns the public C ABI and common build scaffold.
- Core implementation: Claude Opus 5.5, max effort for difficult numerics.
- Independent fixtures, input handling, and routine tooling: GPT-6.1 Sol.
  Difficult independent reviews may use GPT-6 Astra max.
- A cross-review is read-only: report findings, do not edit the other author's
  checkout and do not invoke the other model recursively.
- Small synthetic unit tests, compilation, and empty device smoke are allowed.
  Actual scientific computations and benchmarks are prepared as finite manual
  packages. Do not launch them, kill unrelated processes, or expand a run.
- Never commit credentials, private prompts/replies, personal host metadata,
  environment files, or real input data without explicit public-use provenance.
- Update ignored `.agents/handoff.md` before handing off modified files.
- Claims must distinguish implementation, test pass, real-data acceptance,
  GPU offload, and measured performance.
