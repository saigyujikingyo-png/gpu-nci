# M3B0 finite OpenACC resource result

**PASS for the frozen synthetic resource case, 2026-10-21 UTC.** Explicit
allocation, mapping, partial-failure unwind and synchronous staging passed on
an actual NVIDIA device. This is the standalone resource prerequisite for
M3B1. Public GPU dispatch is still `NOT_IMPLEMENTED`; real-density validation
and performance remain `NOT_RUN`.

## Exact execution scope

The complete clean integrated source was
`07aa8ffb2d7000713b76f92d0d013ab40912d811`, tree
`45e14761e94efcc96d81640ebee32b6d08c428db`, with all 124 tracked files hashed.
Opening, pre-candidate, post-candidate and closing source checks agreed.
The [contract](openacc-resource-contract.md) SHA-256 remained
`d0cb92529e83837dcc604e1b34508af9bbc69976fd53ccac1143b55b914e7413`;
the independently frozen fixture SHA-256 remained
`fc63b07d695ba4540eda8261dc2a4e6d3ac2c94fea18ff49697f8e76d6c1ce48`.
Expected values and resource events were committed before native execution.

Environment: Linux/WSL2 x86_64, NVHPC 26.9, CUDA 13.3, compute capability 12.0,
**NVIDIA GeForce RTX 5070 Laptop GPU**, 8151 MiB reported memory, driver 610.71.
The strict separate-memory flags are recorded in the
[implementation/build instructions](openacc-resource-implementation.md).
Default CPU builds do not require this toolchain.

The corrected candidate ran once with no arguments or input, under a
30-second limit. Candidate, compare-only verifier and controller all exited 0;
all 27 recorded commands completed without timeout or an unreaped child.
The seven silent host checks for device-property string formatting ran before
device initialization. No environment variable forced synchronization.

## Observed resource and transport checks

| Check | Actual result |
|---|---|
| Injected allocation failures and recoveries | All six failure positions unwound; six following recoveries succeeded |
| Two live instances | A has 17 points, B has 31; B remains usable after A is released |
| Output | 96 protocol lines; all 79 binary64 outputs exactly match the frozen bit patterns |
| Resource events | All 240 events match the frozen order, ownership and presence queries |
| Peak tracked objects | 6 host arrays, 6 device allocations, 6 mappings |
| Peak tracked array bytes | 960 host and 960 device; final tracked ownership is zero |
| Actual device execution | 3 NVIDIA kernel launches; every returned marker is 1 |
| Transfers | 8 uploads / 1332 bytes; 6 downloads / 948 bytes, in the required phases |

The exact arithmetic is synthetic addition of one to dyadic inputs; this is
not a measurement of NCI field error. Poisoning host staging before downloads
and checking device markers prevents stale host copies from counting as GPU
results. The test covers interleaved instance lifetimes, not concurrent calls.
Injected failures exercise shared cleanup branches, not actual device OOM.
Tracked bytes exclude driver/runtime pools, allocation rounding and process
RSS; the result does not establish a physical VRAM ceiling or general leak proof.

The same complete source passed all **20 GNU Debug CTests**, with no CTest
skip. Included pytest suites passed 46 CLI, 21 native-driver, 84 end-to-end,
285 independent-oracle, 145 M3A verifier and 96 resource-verifier tests. The
oracle retains one documented pytest skip for the unavailable public
Jacobi-injection hook;
GNU binary128 reference tests actually ran. These CPU regressions are not
GitHub-hosted GPU CI or performance measurements.

## Preserved failure and evidence

The first source `ae89ee99717b7d5eac0218f5ba19354946f63f03` remains
**FAILED / NOT_ACCEPTED**. Its candidate exited 0, but strict verification
correctly rejected 723 NUL bytes in the device identity diagnostic. NVHPC
returned C-padded property strings and Fortran TRIM retained the NUL padding.
A bounded producer-side prefix helper fixed formatting and added seven host
checks. The verifier, fixtures, resource sequence and scientific code did not
change. The successful result comes from a new reviewed package and attempt;
the failed logs were never filtered or reused as an accepted result.

Raw source snapshots, commands, compiler output, binaries, original logs,
exit codes and artifact hashes are retained locally. Relevant receipts:

| Artifact | SHA-256 |
|---|---|
| Candidate binary | `67d8426db791ef3baf7480b007645b91cd7049326ff63f07a7fe8740c56b9e8f` |
| Original stdout | `ad45458654114245edb97ef433942f6484b20bec77da967bdb192c7e432c8dd6` |
| Original stderr | `b7fc201f98cfd12fc300da3fe7076c2a9f1bf7feb5cb96761a4a5fc14d814ffc` |
| Verification report | `16978e397ea92301140696d7fc810ee1432ddf922ffe8eb05de0fc5ffcaabee2` |

The [independent verifier](../tests/openacc_resources/README.md) compares raw
outputs and bound receipts without running the candidate. Its pure selftests
use invented logs and are preparation evidence only. Reproducing native
acceptance requires a fresh finite package bound to its actual build and
outputs; replaying a consumed attempt is not supported.

## Next implementation boundary

M3B1 must connect checked resources to the existing C ABI and production point
evaluator, retain common preflight and private staging, and commit outputs only
after synchronized device-result checks. M3B2 must connect the existing CLI
and X-slab scheduler and test full/slab correctness. Public context budgets,
thread safety, real-density cases and measured performance remain unestablished.
See the [backend plan](openacc-backend-plan.md); scientific specifications,
ABI layouts and tolerances remain frozen.

AI-assisted development: Claude Opus 5.5 max wrote the resource implementation;
GPT-6.1 Sol wrote independent fixtures/verifier, the diagnostic repair and
managed bounded execution; GPT-6 Astra defined architecture and reviewed code
and integration. Only synthetic data was used. No AI model or network is a
runtime dependency. `RESEARCH_HANDOFF.md` remains deferred until the first
accepted end-to-end scientific case.
