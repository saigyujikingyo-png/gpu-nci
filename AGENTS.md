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
- Standing GPU-NCI execution authorization (user, 2026-10-21): automatically
  arrange and run scientific calculations, native validation and performance
  tests through an explicitly GPT-6.1 Sol execution-manager subagent. Manual
  user launch and repeated routine execution approval are not required. This
  project-specific instruction supersedes earlier manual-only ChemCUDA rules
  for GPU-NCI, and remains effective until the user changes or revokes it.
- Before each run, prepare, independently review and freeze a finite package
  with provenance, resource/time/output limits, fail-stop/STOP controls, logs,
  exit status and acceptance criteria. The Sol execution manager checks current
  capacity and unused attempt identity, launches and monitors it; the root or
  an independent reviewer accepts actual receipts before progression. Keep the
  controller independent of an agent session. An old frozen manual-launch label
  does not require editing the frozen package: record the newer authorization
  separately and use the reviewed entrypoint without changing its bounds.
- Further packages within the agreed roadmap may be prepared and automatically
  run under the same authorization after their own review/readiness gates.
  Do not expand a live frozen run, extend limits, retry a consumed attempt or
  weaken a gate. Preserve failures; any corrected attempt needs a new identity
  and reviewed frozen inputs. Never close unrelated apps or kill their processes.
- This execution authorization does not change the scientific specification,
  correctness thresholds, data permissions, merge/CI gates or evidence rules.
- Never commit credentials, private prompts/replies, personal host metadata,
  environment files, or real input data without explicit public-use provenance.
- Update ignored `.agents/handoff.md` before handing off modified files.
- Claims must distinguish implementation, test pass, real-data acceptance,
  GPU offload, and measured performance.
