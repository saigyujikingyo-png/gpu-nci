# Isolated OpenACC probe implementation

This experiment tests the existing binary64 point evaluator on an NVIDIA
device. It is not the public GPU backend. The frozen
[M3A contract](openacc-probe-contract.md) defines its input, fields, tolerances
and execution limits. No production source, ABI, formula or threshold changes.

## Source and device path

`experiments/openacc_probe/generate_sources.py` reads the two actual production
modules from `NCI_PROBE_PRODUCTION_ROOT`. Exact anchors and the complete module
procedure lists must match before it writes any generated file. Its only edits
are insertion of `!$acc routine seq` in procedures and the existing **pure
bind(C)** interfaces, and test-only visibility of the cube-root binding. Removing
these inserted lines must reproduce the original text exactly. Each generated
module has a unified diff; SHA256SUMS and a manifest retain input/output hashes.

The host executable compiles production `nci_kinds.f90` unchanged and
`nci_numerics.f90` with only the visibility insertion. Separate module directories
prevent host/device module reuse. Preprocessing is disabled: the compiler reads
the hashed Fortran sources directly. Device cross-file calls use relocatable
device code. There is no copied numerical implementation or host replacement
of returned device fields.

`m3a_io.f90` reads the complete bounded hexadecimal M3A1 input from stdin.
The device driver explicitly selects NVIDIA device 0. Its three compute loops
evaluate scalar helpers, RDG, and `point_eval`, respectively; each obtains its
DEVICE flag in that same region. Inputs use explicit copyin and results copyout.
All protocol output and diagnostics occur on the host after synchronous return.
No NVIDIA device gives exit 3 / NOT_TESTED; a false DEVICE marker gives exit 4.
Other fatal runtime failures remain failed processes, with no CPU fallback.

## Build interface

The standalone project defaults OFF and is absent from the ordinary CPU build.
It requires NVHPC 26.9 when enabled. Use a fresh single-configuration build
directory, leave CMAKE_BUILD_TYPE and global Fortran/link flags empty, and
configure with the explicitly installed compiler and Python paths:

```sh
cmake -S experiments/openacc_probe -B /path/to/new-build -G Ninja \
  -DNCI_ENABLE_OPENACC_PROBE=ON \
  -DCMAKE_Fortran_COMPILER=/path/to/nvfortran \
  -DPython3_EXECUTABLE=/path/to/python \
  -DNCI_PROBE_PRODUCTION_ROOT=/path/to/frozen-production-checkout \
  -DCMAKE_BUILD_TYPE= -DCMAKE_Fortran_FLAGS= -DCMAKE_EXE_LINKER_FLAGS=
cmake --build /path/to/new-build --parallel 2 --verbose \
  --target m3a_host m3a_device
```

Configure and build each require a caller-enforced 600-second timeout.
Outputs are `host/m3a_host` and `device/m3a_device`; each accepts stdin only,
without arguments. The independent verifier and a bounded execution controller
must freeze and hash the synthetic input before either executable is run.
Each executable is limited to one 30-second invocation. No benchmark loop is
provided. The source-generator, generated files/diffs, binaries, stdin payload,
stdout/stderr and actual runtime evidence all belong to the execution record.

The fixed device options are:

```text
-acc=gpu -Kieee -Mnofma
-gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc
-Minfo=accel
```

Host options are `-Kieee -Mnofma -Mrecursive -Mreentrant`, with IEEE/no-FMA
link options. The no-contraction options do not assert that vendor mathematical
library implementations contain no internal FMA instructions.

## Compilation evidence and rejected candidate

Three distinct compile-only attempts were preserved on 2026-10-20 UTC:

1. Directly importing the NVHPC LIBM interfaces linked, but produced three
   NVFORTRAN-W-0473 purity warnings. This did **not** pass the purity gate.
2. Retaining the production pure bind(C) interfaces and adding routine seq
   compiled and linked without those warnings.
3. The same insertion-only variant with Fortran preprocessing disabled compiled
   and linked without warnings. Compiler reports contain NVIDIA device code for
   the evaluator and the three compute loops. Existing disassembly and dynamic
   dependency records were retained for independent review.

The unused `src/nci_probe_device_math.f90` and `gate_checks/` files preserve the
compile-only comparison; they are not CMake targets and were never executed.
Four deliberate generator anchor/procedure/directive drift cases were rejected
before output. Configure-only checks accepted the default-off GNU project and
rejected enabled GNU, NVHPC Release, and extra global flags. These checks establish
build behavior, not numerical correctness or actual GPU execution.

At this source freeze, native numerical execution is **NOT_EXECUTED**. The
independent corpus and gates were committed separately before execution. A later
execution report must identify exact source revisions and actual device evidence;
compilation alone cannot change this acceptance status.

AI assistance: Claude Opus 5.5 max authored the experiment, adapter and drivers;
GPT-6 Astra defined the contract, reviewed and completed its documentation;
GPT-6.1 Sol authored the independent fixtures and verifier. Development uses only
synthetic data. No AI service or network is required by the compiled programs.
