# M3B1 public OpenACC library: finite synthetic results

**Accepted on 2026-10-21 for the reviewed finite synthetic scope.** The optional
library executes the existing FP64 NCI field evaluator on the GPU through the
unchanged three-function C ABI. This establishes neither real-density scientific
validation nor a measured speedup. Offline CLI integration is outside this
M3B1 result; its later acceptance is recorded in [M3B2 results](openacc-cli-results.md).

The tested source is `e751417074d655f299bdf47911b88b9a7424fc94` (160 tracked
files). Later documentation commits do not change this tested revision. The
complete GNU and NVHPC builds used an exact Git archive; mathematical source,
public header, units, masks, flags and acceptance tolerances were unchanged.

## Actual environment and checks

The execution used WSL2 Ubuntu 24.04, GNU Fortran 13.3, NVHPC 26.9, CUDA 13.3,
cc120 and an NVIDIA GeForce RTX 5070 **Laptop GPU** (driver 610.71).
The independent Python checks used Python 3.12.3, NumPy 2.3.4, SciPy 1.16.2
and pytest 8.4.2. IEEE/no-contraction controls and separate device memory follow
the [public contract](openacc-public-contract.md).

| Check | Observed result |
|---|---|
| GNU CPU CTest | 22/22 passed, including the available binary128 checks |
| CPU pytest identities inside those checks | 1006 passed; one existing documented skip; zero failures/errors |
| Public/private OpenACC native pytest | 148/148 passed; zero skips/failures/errors |
| Python evaluation receipts | 295 public-library calls + 55 private test-bridge calls verified |
| Separate pthread executable | Six evaluations verified, including context migration and concurrent distinct contexts |
| Original runtime notices | 20,218 Python + 482 pthread notices matched the frozen strict policy |
| Actual GPU field kernels | 272 Python + six pthread = 278 |
| Logical device cleanup | 2484 Python + 54 pthread = 2538 deletes matched the frozen call plan |
| Finite controller | All ten stages exited zero and passed owned-process cleanup |

The sole CPU pytest skip is `test_optional_jacobi_nonconvergence_hook`: the
public ABI has no standardized test-only Jacobi injection hook. Native core
CTest exercises its separate injection hook. The CPU pytest counts are included
in CTest and must not be added to CTest as independent runs.

Independent analytic/LAPACK and CPU comparisons cover finite, periodic and mixed
boundaries, full grids and canonical slabs, both output modes, mathematical edge
cases, flags and diagnostics. Rejection tests check unchanged caller buffers;
private fault injection checks staged failures, recovery and isolation. Original
pthread outputs, digests, causal events and thread identities were checked.
The private bridge links the same production objects; its hooks are not public
ABI functionality. See the [independent suite](../tests/openacc_backend/README.md).

The trace policy was frozen from reviewed source, compiler and installed-runtime
evidence before this run. It checks the exact static initialization prefixes,
transfers, kernel regions, synchronization and logical cleanup. Unknown notices
are rejected. Python notice ordering is serial; pthread attribution is aggregate.
Physical allocation/free notifications are observations, not a proof of driver
pool balance or a measurement of peak VRAM.

## Finite resource and rejection evidence

The package limited execution to ten stages, 1800 seconds plus its fixed cleanup
allowance, two CPU equivalents, 2 GiB cgroup memory, no swap and 64 processes.
Output controls were a 32 MiB hard per-file limit and sampled fail-stop limits
of 256 MiB, 16,384 files and 32,768 entries. Actual controller elapsed time was
321.057 seconds; this includes validation overhead and is **not a benchmark**.

The cgroup recorded a 271,781,888-byte memory peak, no OOM or limit events, and
zero remaining processes before removal. All recorded owned process identities
were absent after cleanup. The final output sample was 40,944,156 bytes across
8951 files and 9623 entries, below the limits. These observations do not measure
physical GPU memory.

Actual field fixtures had at most two contexts, grids no larger than 17 cubed,
and at most 576,861 tracked array bytes on each host/device side per context.
The mapped-object rejection fixture separately reserved a 2,348,826,624-byte
virtual arena with 45,056 writable prefix bytes; another 856 guarded statistics
and error-buffer bytes are outside that arena. The remaining arena is inaccessible.
The virtual extent is not measured RSS. Its 1777-byte original-argument
proof established disjoint declared intervals; only packed object 5 exceeded
INT32_MAX. The call returned the specified UNSUPPORTED status and exact error,
preserving all retained density, output and statistics bytes. It did not evaluate
a large density grid or weaken the memory limit.

## Provenance, failures and review

The accepted attempt is `m3b1-full-e7514170-20261021-07`. These SHA-256 identifiers
bind the private original evidence; raw host paths, process identities and logs
are kept outside the public repository:

| Artifact | SHA-256 |
|---|---|
| Frozen package | `65149d3a8c7b23d168fb0d0105b964908966baef480ebc65df0b307393e82eee` |
| Original completion record | `c78b69438dab34f38b56df2f8cbaaa170ea1bff40339ae947ecc566c43e0341a` |
| Terminal evidence seal | `fd8fc8517dd68b632adfaca71acda5d704bb87914503827d9787f112470540b3` |

An independent reviewer rehashed the original logs and bound source/output
artifacts, checked exact test identities, original pointer/byte proofs, raw
runtime notices, resource events and cleanup. Acceptance is recorded separately;
the original completion and collection reports retain their pre-acceptance states.

Earlier attempts 01–06 are consumed and preserved as failures. They exposed
harness path setup, truncated CTest evidence, receipt-directory setup, an empty
oracle selection, a stale source fingerprint, and an invalid large-span rejection
fixture. Each correction received a new reviewed source/package identity; no
failed attempt was replayed or retroactively converted to success. The final
test repairs did not change production numerical formulas or rejection ordering.

Development was AI-assisted: Claude Opus 5.5 implemented the OpenACC core;
GPT-6.1 Sol authored independent fixtures/tooling and managed the frozen run;
GPT-6 Astra handled architecture, integration and independent review. Those
roles are development provenance, not a replacement for scientific validation.
The data in this package are generated synthetic fixtures; no research-group
internal data are used.

## Remaining work

M3B2 must connect explicit GPU selection to the existing offline CUBE worker,
account for host staging, and independently validate complete CLI/slab behavior.
M4 then needs authorized real-density inputs, a frozen CPU reference and actual
error/performance measurements. Test tolerances are acceptance criteria, not
measured worst-case scientific errors. Peak VRAM, speedup and real-density
scientific acceptance remain unmeasured/unaccepted. `RESEARCH_HANDOFF.md` follows
the first accepted end-to-end scientific case.
