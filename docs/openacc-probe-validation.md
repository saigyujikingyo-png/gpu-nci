# M3A independent fixture freeze

State: INPUTS_PREPARED_NOT_EXECUTED. The finite corpus and its numerical gates
are frozen before candidate GPU execution. This work changes no production code,
public backend, compiler policy or scientific threshold. The public GPU backend
remains NOT_IMPLEMENTED.

The committed `tests/openacc_probe/frozen/manifest.json` and `input.m3a1` contain
36 scalar, 9 RDG and 9 point records. All binary64 runtime input is hexadecimal.
Manifest source hashes cover the independent generator, exact oracle and existing
`reference/extreme.py`. Each record has its own expected values and named gates.

Scalar scaling uses exact Fraction arithmetic and nearest-even rational midpoint
comparisons, including the overflow midpoint. Cube roots use a binary search
over positive finite binary64 bit patterns and exact Fraction cube comparisons
at rounding midpoints. No production algorithm or output supplies truth.
RDG uses the defining formula with independently computed pi at 160 and 210
decimal digits, requiring stable binary64 rounding at both precisions.
Exact rational FD4 derivatives and transforms plus independent LAPACK or known
analytic eigenvalues supply point references. Failure paths have explicit field
classes: derivative overflow status1/all16NaN; forced nonconvergence status4 with
finite grad/Hessian and seven NaNs; RDG overflow status6 retains finite
derivatives/eigenvalues/bound/tau, positive infinity RDG and NaN signed density.

The manifest records the original derivative/eigenvalue and RDG tolerances.
Extreme finite RDG also requires relative error <=16 binary64 epsilons.
Nonzero subnormal RDG requires positive subnormal classification and <=1 ULP;
zero cannot pass through an absolute tolerance. Scalar cbrt allows <=1 ULP
against the correctly rounded reference, with signed zero/Inf/NaN separate.

Bound/tau are host portability checks, not independent bound theorem proofs:
exact rational comparison requires abs(device-host)<=8*2^-1074+1e-10*abs(host).
Both must be finite and nonnegative. On each applicable result tau must match
the exact bits of `(1e-12 + 1e-10*max(abs(lambda1),abs(lambda3))) + bound`, and
uncertainty must equal `not(abs(lambda2)>tau)`. Host/device status and uncertainty
must agree. Raw signed density follows the returned middle root, and reference
sign checks use the unchanged fixed 1e-9 fixture band.

Generate a new exclusive directory without executing any native binary:

```text
python tests/openacc_probe/fixtures.py --generate NEW_DIRECTORY
```

The compare-only verifier interface, implemented separately, is:

```text
python tests/openacc_probe/verify.py --verify --manifest manifest.json --input input.m3a1 --host-output host.stdout --device-output device.stdout --evidence evidence.json --report NEW_report.json
```

The private runner alone executes one frozen host and one frozen device binary.
The verifier never invokes them. It returns exit0/PASS, exit1/FAILED, or
exit2/NOT_TESTED for an explicitly recorded missing device. All results are
limited to this finite corpus; runtime launch/transfer evidence and immutable
binary/input/output/log receipts are required for an executed comparison.

The executed evidence JSON schema is:

```json
{
  "schema_version": 1,
  "state": "executed",
  "input": {"path": "/absolute/input.m3a1", "sha256": "64 lowercase hex digits", "bytes": 22024},
  "manifest": {"path": "/absolute/manifest.json", "sha256": "64 lowercase hex digits", "bytes": 57629},
  "host": {
    "binary": {"path": "/absolute/host", "sha256": "64 lowercase hex digits", "bytes": 123},
    "stdout": {"path": "/absolute/host.stdout", "sha256": "64 lowercase hex digits", "bytes": 123},
    "stderr": {"path": "/absolute/host.stderr", "sha256": "64 lowercase hex digits", "bytes": 0},
    "returncode": 0,
    "command": ["/absolute/host", "/absolute/input.m3a1"]
  },
  "device": {
    "binary": {"path": "/absolute/device", "sha256": "64 lowercase hex digits", "bytes": 123},
    "stdout": {"path": "/absolute/device.stdout", "sha256": "64 lowercase hex digits", "bytes": 123},
    "stderr": {"path": "/absolute/device.stderr", "sha256": "64 lowercase hex digits", "bytes": 123},
    "returncode": 0,
    "command": ["/absolute/device", "/absolute/input.m3a1"]
  },
  "device_count": 1,
  "device_identity": "actual NVIDIA identity recorded by the private runner",
  "compiler_report": {"path": "/absolute/build.log", "sha256": "64 lowercase hex digits", "bytes": 123},
  "runtime_evidence": {"path": "/absolute/device.stderr", "sha256": "64 lowercase hex digits", "bytes": 123}
}
```

All receipts have exactly path/sha256/bytes; paths are absolute, SHA-256 values
must be lowercase and sizes/returncodes/device_count must be integers, not bool.
The command's first argument must resolve to its binary. Output arguments must
bind to the matching stdout receipt. Runtime evidence must bind to device stderr
and contain a kernel-launch line plus upload and download messages, for example
the actual NVHPC `NVCOMPILER_ACC_NOTIFY=3` log. A DEVICE=1 marker alone cannot pass.
The compiler report is retained and hashed; exact compiler flag, source adapter
and device identity provenance still require the separate architecture/build
review. The verifier does not infer those facts from numerical output.

For a missing device, use schema_version1, state `no_device`, device_count0,
nonempty reason, input and manifest receipts. Omit host/device run objects;
the runner must not execute either binary. Host/device output arguments may be
omitted in this case. An attempted nonzero-exit execution is FAILED, not a
missing-device substitute. Reports are exclusively created. PASS records counts,
all artifact digests, verifier/evidence digests, scope and raw middle-root sign
differences; FAILED records its reason and available input/output/log-index
digests; NOT_TESTED records the missing-device reason. Original files are only
read and are hashed again after comparison.

Pure development validation:

```text
python -m pytest -q tests/openacc_probe
97 passed
```

These checks use invented protocol output, placeholder files explicitly named
`not-an-executable` and a synthetic runtime log. Their invented bound is only
verifier test data. They do not supply native or device acceptance evidence.
The tests reject malformed records, wrong counts/END/indices/device markers,
incorrect bit helpers and >1-ULP cbrt, flushed subnormal RDG, hidden NaN/Inf,
incomplete failure fields, wrong raw sign/status/uncertainty, a device bound/tau
pair that is self-consistent but differs from host by 1e-5 relative, one-bit tau
relation drift, missing kernel or transfers, changed binary/input/gates, absent
device identity/count, unbound runtime evidence and nonzero exits. Separate
checks retain permitted raw sign differences inside the fixed band and verify
NOT_TESTED/FAILED exit codes and refusal to overwrite an existing report.

The frozen corpus commit is `ee5489078fa8bcaf8107d7d93b6de09d99ad6cf7`.
No candidate host/device binary, scientific solver or benchmark was executed by
this writer. Actual finite probe execution and review remain pending.
