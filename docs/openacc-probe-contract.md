# M3A isolated OpenACC numerical portability probe

Frozen before device execution. Base production tree:
`a1ebe23c5f56b2df143ee99aca8ac88497861fa0`. This is a small developer test of
binary64 numerical portability. It changes no production formula, threshold,
mask, input contract, C ABI or CLI backend. No real density, solver, timing
benchmark, or scientific acceptance is included. The public GPU backend stays
`NOT_IMPLEMENTED` even if this probe passes.

## Same evaluator, isolated build

Build the actual `nci_kinds.f90` and `nci_numerics.f90` from the declared CPU
source tree in a separate standalone experiment. Generate device sources into
the build directory with a deterministic adapter; retain original/generated
hashes and an exact unified diff. Allowed changes are device routine declarations,
replacement of the two host `scalbn`/`cbrt` bindings by a device-capable shim,
and test-only exposure of the cube-root binding. Do not maintain another copy
of the formulas or change operation order, purity, constants, Jacobi controls,
or bounds. A required change outside this allowlist is a failed portability
gate requiring architectural review, not permission for an automatic workaround.

The NVHPC `LIBM` device module is a candidate for `real(8)` `scalbn` and `cbrt`.
Pure compatibility, OpenACC routine calls and cross-file device linking must be
demonstrated. Do not substitute `rho**(1/3)` or the host `SCALE`, `EXPONENT` and
`FRACTION` intrinsics that previously failed endpoint probes. The host reference
executable uses the unchanged CPU source and bindings.

Use NVHPC 26.9, explicit `-acc=gpu -Kieee -Mnofma` and
`-gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc` (confirmed by the installed
compiler's help). Record the exact
accepted compiler/link commands and reports. A compiler rejecting a required
flag is a failure, not a reason to omit it silently. The experiment is absent
from the default root build. GNU CPU compilation requires neither OpenACC nor
LIBM. Every compiler/variant has its own module and output directories.

## Runtime input/output protocol version 1

ASCII input, exclusively synthetic, begins with `M3A1`, then three decimal
counts `NS NR NP` (each 0--128). Each binary64 token is exactly 16 hexadecimal
digits representing its IEEE bits, avoiding decimal parsing/constant folding.
All input is read on the host before transfer; no file I/O occurs on the device.

1. NS scalar records: `X_BITS SCALE_EXPONENT`. Exponents are signed integers
   bounded to [-4096,4096]. Evaluate finite classification, binary exponent and
   fraction on finite input only, power-of-two scaling, and cube root. For
   nonfinite X, return exponent 0 and canonical NaN fraction; scaling and cube
   root are checked by classification. Signed zero is a finite input.
2. NR RDG records: four hex tokens `GX GY GZ RHO`. Call the existing
   `rdg_from_gradient` directly with finite gradient and finite positive rho.
3. NP point records: one line `FLOOR_BITS MAX_ROT` (30 normally, 1 only for the
   existing forced-nonconvergence test), then 9 inverse-matrix tokens, then
   125 block tokens. Arrays use Fortran element order (first index fastest),
   matrix shape (3,3), block bounds (-2:2,-2:2,-2:2). Compute `absm=abs(m)`.
   Call the actual `point_eval`; one independent point per device iteration.

Output begins `M3A1`, followed in the same order by:

- `S i DEVICE FINITE EXPONENT FRACTION_BITS SCALED_BITS CBRT_BITS`.
- `R i DEVICE RDG_BITS`.
- `P i DEVICE STATUS UNCERTAIN`, then a line of 16 hex tokens: grad(3),
  hess(6), lambda(3), rdg, signed_rho, bound, tau, in that order.
- Final line `END NS NR NP`. Indices are 1-based; logical outputs are 0/1.

Each DEVICE is 1 only when `acc_on_device(acc_device_nvidia)` was evaluated
in the same compute region that performed the corresponding actual calculation.
The host reference writes DEVICE=0. No host recomputation may replace returned
GPU fields, bounds, tau, uncertainty or status. The driver rejects malformed,
excess or truncated records. The independent verifier checks exact record count,
identity and the final marker, process exit and file hashes.

## Independent frozen gates

The separate verifier must commit its finite fixture manifest before the first
candidate GPU execution. Include both signed zeros; smallest, representative
and largest subnormals; smallest normal; largest finite; Inf/NaN classification;
and runtime-fed scaling endpoints `.75*2^1024`, `.75*2^-1073`, `.75*2^-1074`,
half-ULP ties to signed zero and genuine overflow. Binary exponent/fraction are
checked only on their finite contract. Scaled finite values, signed zero and
bit helpers must equal an independent correctly rounded binary64 reference
bitwise. Cube root must be within 1 ULP of an independently correctly rounded
value, with signed zero/Inf/NaN classified separately.

Point fixtures reuse the independent constant, mixed quadratic, skew-matrix,
known-root and forced-failure principles already used by the CPU oracle.
Standalone RDG fixtures include extreme finite and subnormal outputs. Point
grad/Hessian/eigenvalue tolerances remain atol=1e-12, rtol=1e-10; RDG remains
atol=1e-11, rtol=1e-9. Extreme RDG fixtures additionally enforce output class and
their existing endpoint-relative/ULP gates so absolute tolerance cannot accept
zero for a nonzero subnormal result. Record exact individual gates in the
fixture manifest. Do not derive expected numerical values from production code.

For this finite probe corpus require host/device status and uncertainty to
agree. On success, compare device bound and tau separately with the unchanged
host evaluator using rtol=1e-10 and atol=8*2^-1074, and require both finite and
nonnegative. This comparison is a portability check, not an independent proof
of the bound theorem. Also check tau against its frozen relation to lambda/bound
and `UNCERTAIN == not(abs(lambda(2)) > tau)` on each device result. Signed density must agree with the raw
computed middle-eigenvalue sign, including exact zero. Reference sign gates use
the existing fixed 1e-9 fixture band; record raw host/device sign differences
separately, not as a replacement for the field comparisons. General bit5
boundary-band qualification, public masks/statistics, and scientific bit6
certification are outside this pointwise experiment. It cannot certify tile
classification, slabs, budgets or direct C ABI behavior.

## Execution and evidence limits

At most 128 records of each kind; input/output arrays <=8 MiB each, synthetic
host sample data <=64 MiB. These caps exclude compiler processes and CUDA
context/driver overhead and are not claimed as total RSS/VRAM limits. Configure
and build have 600-second timeouts, at most two build jobs; each executable has
a 30-second timeout. A verifier invocation runs one host executable and one
device executable once each. No parameter sweep, repeated timing, automatic
retry or tolerance relaxation. Preserve failed attempts under new directories.

Select NVIDIA explicitly, require a nonzero device count, save device identity,
compiler device-generation reports and runtime kernel-launch/transfer evidence.
A missing device is `NOT_TESTED`, never fallback PASS. Device markers alone
or a successful compile alone are insufficient evidence. Save source/input/
generated-source/binary/output SHA-256 hashes, all commands, stdout/stderr,
exit status and the final independent comparison. A pass proves only this
finite evaluator path and compiler/device configuration.

## Gate before the public GPU backend

OpenACC's error callback is not recovery: NVIDIA documents undefined behavior
if it returns after a fatal runtime error. The existing ABI forbids NCI from
using STOP, exceptions or external I/O; it does not promise recovery from every
OS, driver or hardware failure. Keep NCI-detectable input/configuration failures,
explicit work-buffer allocation failures and pointwise numeric failures on the
existing status/errbuf paths. Unrecoverable platform or third-party runtime
failure may terminate a process; the existing CLI worker boundary must classify
that as failure, never SUCCESS or CPU fallback. This distinction is not an
excuse for invalid mapping, out-of-bounds code or reproducible crashes on valid
supported input.

The documented `acc_malloc` null-device-pointer result is a candidate for
checked explicit allocation with paired `acc_free`; its actual failure/cleanup
path still needs a bounded development test. Before public dispatch, separately
freeze and validate host/device budgets, per-context state, synchronous output
commit behavior and device-origin failure diagnostics. M3A does not implement
these, and no public backend is advertised. This keeps the planned OpenACC
route without claiming that an error callback can recover fatal errors.

Primary references:

- [NVHPC LIBM device module](https://docs.nvidia.com/hpc-sdk/compilers/cuda-fortran-prog-guide/index.html#libm-device-module)
- [NVIDIA mathematical function accuracy](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-c-programming-guide/index.html#mathematical-functions)
- [NVHPC 26.9 OpenACC error handling](https://docs.nvidia.com/hpc-sdk/archive/26.9/compilers/openacc-gs/index.html#openacc-error-handling)
- [NVHPC 26.9 explicit allocation](https://docs.nvidia.com/hpc-sdk/archive/26.9/compilers/openacc-gs/index.html#acc-malloc)
- [NVHPC 26.9 compiler guide](https://docs.nvidia.com/hpc-sdk/archive/26.9/compilers/hpc-compilers-user-guide/index.html)

AI assistance is recorded with implementation evidence: Astra architecture and
independent review; Claude Opus 5.5 max device adaptation; GPT-6.1 Sol independent
fixtures and verifier. No model, credentials or network is a runtime dependency.
