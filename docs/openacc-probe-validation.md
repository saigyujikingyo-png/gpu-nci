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

Verifier negative/selfchecks and the exact evidence schema follow in the next
test-only commit. This fixture freeze alone is not integration acceptance.
