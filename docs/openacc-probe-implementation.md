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
Its host reader uses POSIX `read(0,...)` and a 4096-byte interoperable C-char
buffer. This isolated experiment is explicitly restricted to Linux x86_64,
where `ssize_t` maps to C long; CMake rejects another platform when enabled.
The binding uses value fd/count/c_ptr and `c_loc`, without a Fortran character
descriptor. Positive short reads continue the same token, zero alone is EOF,
and a negative return rejects input without retry. Actual bytes, including LF,
count toward 8 MiB; at the exact cap one additional byte is requested solely
to distinguish EOF from excess input. Space/tab/CR/LF are the only separators.
No formatted Fortran input or synthesized record boundaries share fd0.
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

At the initial e5d5a0f source freeze, native numerical execution was
**NOT_EXECUTED**. The
independent corpus and gates were committed separately before execution. A later
execution report must identify exact source revisions and actual device evidence;
compilation alone cannot change this acceptance status.

## Preserved first execution failure and stdin repair

The root-owned first finite attempt is preserved at
`/opt/gpu-nci-development-builds-20261020/m3a-20261020T235144433074Z`.
Host exit2 rejected input at token139 before numerical evaluation; GPU execution
was not started. The actual 22024-byte payload matched the independent frozen
input SHA-256 `ad9fd786113d8db5d7760475ab1be110eb7f042d576206efdcdd13535607c7f5`.
Token139 is valid `3FF0000000000000`, at column255 of the first 2124-byte point
block line: the first token crossing the old 256-byte buffer boundary.
Root's separate pure-I/O reproduction at
`/opt/gpu-nci-development-builds-20261020/m3a-reader-20261020T235317143336Z`
showed NVHPC's nonadvancing formatted READ consuming256 bytes, then reporting
zero bytes/EOR while losing the logical line suffix. Input reformatting and
tolerance changes were not used to hide this failure.

The correction changes only experimental stdin transport, leaving token rules,
record parsing, production numerical modules, generated adapter, frozen input
and independent numerical gates unchanged. The new explicit
`m3a_parse_only` target compiles the CPU modules for their types, but its entry
only calls read_input and emits actual parsed binary64 bits/integers in protocol
order. It never calls scalar_record, rdg_record or point_eval and is excluded
from the default standalone build. Its module/output directory is separate.

```sh
cmake --build /path/to/new-build --parallel 2 --verbose --target m3a_parse_only
python experiments/openacc_probe/tools/parser_regression.py \
  --parser /path/to/new-build/parse_only/m3a_parse_only \
  --input /path/to/frozen/input.m3a1 --output-dir /path/to/new-cases
```

Configure/build retain the 600-second timeout and at most two jobs. The finite
regression script runs ten fixed parser cases once each with a 10-second limit,
preserving stdin/stdout/stderr, exit status and hashes in an exclusive directory.
It checks every returned token, not just counts. New evidence at
`/opt/gpu-nci-development-builds-20261020/m3a-parser-canonical-20261020T235728737531Z`
records configure/build exit0 and **10/10 parser cases PASS**: original long
lines, legal space/tab/CR/LF, a token across4096, no final LF, truncated hex,
overlong token, excess input, NUL, exact8MiB, and cap+1. Every accepted case
returns all1336 original tokens; rejected cases return exit2 with no stdout.
The preliminary count-only9-case development run remains separately preserved
at `.../m3a-parser-fix-20261020T235634932320Z`; final acceptance uses the full
canonical-token run. No numerical or GPU executable was run by this repair.
After that repair was frozen at `5a5657f`, root ran the original fixed corpus
once on the host and once on the NVIDIA GPU. Both exited0 and the independent
verifier passed all36scalar/9RDG/9point records. Actual kernel and transfer
evidence was retained. Full scope and measured finite errors are recorded in
the integration branch's `docs/openacc-probe-results.md`; this does not enable
the public GPU backend or constitute scientific/performance acceptance.

AI assistance: Claude Opus 5.5 max authored the experiment, adapter and drivers;
GPT-6 Astra defined the contract, reviewed and completed its documentation;
GPT-6.1 Sol authored the independent fixtures/verifier and the host stdin repair.
Development uses only
synthetic data. No AI service or network is required by the compiled programs.
