# M4 stored-water validation

Accepted 2026-10-21: **SCIENTIFIC_ACCEPTED_CONDITIONAL** and
**CONTROL_TRACE_CLEANUP_ACCEPTED**. This is the first accepted real-density
end-to-end case. Performance (P1) is **NOT_RUN**; same-input NCIPLOT/CRITIC2
pointwise comparison (V4) is **NOT_PERFORMED**.

## Input and fixed scope

The input is IOData's public
[`water_sto3g_hf_g03.fchk`](https://github.com/theochem/iodata/blob/9f7e800fc414b086d677b5f2882dd0c1dfa919f3/iodata/test/data/water_sto3g_hf_g03.fchk)
at commit `9f7e800fc414b086d677b5f2882dd0c1dfa919f3` (5,369 bytes).
It describes a stored, all-electron, spin-summed RHF/STO-3G water model:
seven atomic orbitals, five doubly occupied molecular orbitals and ten electrons.
The density is exactly `rho = 2 sum(first five stored MO amplitudes squared)`.
No new SCF calculation, density clipping, contraction renormalization or private
research-group input was used. Historical SCF and physical model error
`E_model` remain **UNKNOWN**.

Three grids directly sample the same model in `[-3,3]^3` bohr:
`41^3`, `81^3`, `161^3`, with steps `h=0.15`, `h/2=0.075`, `h/4=0.0375` bohr.
There is no interpolation. The fixed spatial ROI is coarse indices 4..36 on
each axis: 35,937 nodes in `[-2.4,2.4]^3` bohr. The primary ROI intersects this
with continuous density in `[1e-4,0.05]` electron/bohr^3: **26,817 nodes**,
38.9098% of the 68,921 coarse output nodes. Membership was frozen independently
of numerical errors, RDG and Hessian signs.

Eight native CLI calls used source
`001cf5c5a68d625878176179e4179fcdbbd5d2da`: CPU and OpenACC full-grid/X-slab
at h, and CPU/OpenACC X-slabs at h/2 and h/4. The GPU was an **RTX 5070 Laptop
GPU**, using NVHPC 26.9 / CUDA 13.3 / cc120. Later documentation commits do not
change the tested native source identity. Production settings retained FP64,
no FMA, `rho_min=1e-8`, zero negative tolerance and one CPU/BLAS thread.

## Independent checks and actual results

The validation-only reader/sampler used pinned IOData and GBasis
(`7fa3524ece92b149a6838332ec67a43a8f404bdf`) with screening disabled.
A separate seven-orbital s/p Gaussian implementation supplied continuous
derivatives, overlap checks and prior sampling/coordinate roundoff budgets.
An independent rational-weight finite-difference oracle checked common coarse
nodes on each grid; LAPACK checked eigenvalues of the diagnostic Hessians.
These checks do not add production wavefunction input support.

All 4,773,643 density points were sampled directly. CUBE serialization changed
zero binary64 values. The independent analytic all-space electron count was
10.000000002868966; this checks the stored representation, not SCF accuracy.

| Check | Actual result |
|---|---|
| Stable primary nodes / fixed denominator | 26,722 / 26,817 = **99.6457471%**; gate >=95% |
| All three grids and both backends vs continuous sign on that fixed stable set | **100%** agreement; gate >=99.9% |
| Nodes retained outside stable set | One nonasymptotic + 94 target-budget-unstable nodes |
| Raw h vs continuous-reference sign flips | Six, all outside the stable set; zero CPU/GPU raw sign flips |
| CPU/GPU gradient, Hessian, lambda2, flags, signed density | Equal file hashes on every grid |
| Maximum CPU/GPU RDG absolute difference, all valid grid points | `1.1368683772161603e-13` |
| h full-grid vs slab | Byte-identical across all six fields within each backend |
| RDG P95 relative change, h to h/2 / h/2 to h/4 | `0.001245826019` / `0.000079679563`; both <=0.01 |
| RDG maximum absolute change, same pairs | `0.008135914605` / `0.000495576845`; both <=0.02 |

The RDG relative denominator is `max(abs(finer RDG),1e-6)`. Every strict V2
nominal CPU/GPU gate passed; no bit-5 differences, numerical failures or contract
violations occurred. Separately, at h/4 **two Hessian components per backend**
in the independent finite-difference-oracle comparison passed only with the
pre-frozen `B_comp` arithmetic allowance. This is not a strict V2 nominal
CPU/GPU failure, and the allowance was not fitted after execution.

Continuous-reference errors on the same 26,817 primary nodes were identical
for CPU and GPU. Here L2 means RMS of pointwise Euclidean gradient errors or
Frobenius Hessian errors; maximum means the largest such pointwise norm.

| Step (bohr) | Gradient L2 (electron/bohr^4) | Gradient maximum | Hessian L2 (electron/bohr^5) | Hessian maximum |
|---|---:|---:|---:|---:|
| 0.15 | `3.3957553e-5` | `3.3240365e-4` | `2.4069603e-4` | `2.8865123e-3` |
| 0.075 | `2.1689696e-6` | `2.1732081e-5` | `1.5659288e-5` | `1.9227306e-4` |
| 0.0375 | `1.3635485e-7` | `1.3722614e-6` | `9.8884583e-7` | `1.2208834e-5` |

Primary-ROI L2 convergence orders are gradient **3.96865 / 3.99157** and
Hessian **3.94212 / 3.98513**. The larger spatial ROI includes nuclear cores;
its Hessian orders are only **1.42908 / 2.83229**. These results do not establish
fourth-order convergence throughout the box or for arbitrary molecular inputs.

## Conditions, execution and evidence identity

The scientific assessment is conditional on the specified stored model, ROI,
prior arithmetic budgets and the frozen libm premise (used exp/power relative
error at most eight binary64 epsilons plus eight minimum subnormals).
The local prior-error-aware order interval must lie within `[3.5,4.5]`;
Richardson's `(16/15)*||H_h-H_h/2||F` is an asymptotic estimate, not a universal
rigorous truncation bound. Unresolved and nonasymptotic nodes remain in the
coverage denominator. Production scientific-uncertainty **bit 6 stays set** on
all valid points; acceptance is an external sidecar, not a rewritten flag.

Independent review accepted the original 16 stages (all exit zero), 72 actual
GPU field launches, complete trace attribution, resource limits and cleanup.
Peak controlled memory was 1,764,319,232 bytes (<2 GiB), with zero memory/OOM/PID
limit events. Sampled output was 1,397,347,075 bytes (<3 GiB). Validation wall
time **628.1694 seconds includes verification overhead and is not a benchmark**.
No speedup or physical peak-VRAM measurement follows from it.

The finite attempt was consumed once. Original logs, sealed arrays and review
records are retained outside the public repository; no raw FCHK, third-party
dependency source, host identity or private prompt is redistributed here.
These SHA-256 identities bind the reported case to that retained evidence;
they are not a claim that the full private execution package is published.

| Item | SHA-256 |
|---|---|
| Public input FCHK | `aa8dec77849d4f9e1e9dc9357c80f5b4d6ba1efc3bbc17da6c59754bdaed0816` |
| Frozen package | `586dbe78ca4e32d23c8538df67eaaafb810d796ca6e306d9e98925c6ebaa4d2c` |
| Frozen policy | `bdec0c937ed174913e9d5b6364aaec38efe9f6bedd0fb63fcff3a46741bf26e9` |
| Original run/completion JSON (identical) | `6c889551af413a66e58f617dcd354ee16e64fbe04a22f397a45bc2167106c543` |
| Sealed artifacts | `42ae0f11f1450bfbdf0f7b30bd303158fd7f7fa6dd0628f5e5b958b4fbd1961a` |
| Terminal seal | `ff0fe3ca9ab0809df9e768df9d80af64e866d7a3bf88b304417af5ad408d0bab` |
| Analysis report | `8007e7163fd9257bafdfa5a9ed36ba51ab6c80fd306333855047f6e324efa905` |
| Certification CSV | `550017729d26220d0d20e9ee97267526dc5e61372822056e07b937a349ff8511` |

P1 performance preparation needs a separate reviewed, frozen package and actual
timing before any speedup claim. V4 same-density NCIPLOT/CRITIC2 comparison,
chemical interpretation and broader input coverage remain undone. See the
[research handoff](../RESEARCH_HANDOFF.md) for the intended research discussion.
