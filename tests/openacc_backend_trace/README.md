# M3B1 original NVHPC stderr comparison

**PREPARED; real policy, source sites and compiler metadata are not frozen.**
This directory supplies a small standard-library-only, compare-only checker.
It never invokes a process, Git, a compiler, an evaluator or a shared library,
and never reads environment variables. No native/GPU/scientific calculation
was run while authoring it. Invented pure-test PASS is parser preparation only.

Run only the pure preparation tests during authoring:

```text
python -m pytest -q -p no:cacheprovider tests/openacc_backend_trace/test_pure.py
```

The checker rejects unknown lines, blank lines, unknown or duplicate keys,
unknown/ambiguous sites, wrong device/function/file/source line/variable,
missing or extra kernels/transfers, wrong bytes, malformed UTF-8, NUL/control
characters, duplicate/nonfinite JSON, changed artifacts and exceeded caps.
It parses at most 16 MiB per JSON/stderr and hashes at most 256 MiB of unique
artifacts in total. These are artifact caps, not host/device memory limits.

## Prepare once before a manual launch

An independent reviewer must freeze the integrated source, source/compiler
reports, strict build flags, binaries, test source, upstream verifiers and
controller. Never infer a policy from candidate stderr after execution.
The final source/compile report must prove every permitted notification,
including any fixed compiler-generated metadata. An empty metadata list is a
reviewed conclusion, not a default assumption. There is no ignore-unknown rule.

The independently authored `tests/openacc_backend/expectations.py` is the
source of physical input plans. After source review, generate a new JSON before
launch, from that module alone (no receipt or candidate import):

```python
import json
from tests.openacc_backend.expectations import expected_calls
fields = ('mode', 'backend', 'shape', 'input_shape', 'status', 'entry')
# Reviewed independently against test_private.py configure calls, not receipts.
failures = {**{f'fail-{n}': n for n in range(1, 19)},
            'control/pending-failure-consumed': 1, 'isolation/A-failure': 9}
plan = {'schema_version': 1}
for group, role in [('public', 'production-shared-library'),
                    ('private', 'same-production-objects-test-only-bridge')]:
    plan[group] = [dict(case_id=name,
                       failure_at=failures.get(name, 0) if group == 'private' else 0,
                       **{k: spec[k] for k in fields})
                   for name, spec in expected_calls(role).items()]
with open('/absolute/new/input-plan.json', 'x', encoding='utf-8') as stream:
    json.dump(plan, stream, indent=2, allow_nan=False)
```

Bind that JSON, its exact reviewed `expectations.py`, and the independent
`test_private.py` configure-plan source SHA256 in policy.
Plan list order is immaterial: cases map by ID to independently verified
receipt ordinals. The frozen inventory is 295 public/55 bridge evaluations,
238/34 GPU field regions; six pthread regions give 278 regions total. Allocation
failure and preflight rejection have no region; marker/status corruption still
requires the complete region and transfers. This preserves the 148 pytest
cases, 356 total evaluations, at most two contexts and 17^3 actual grids.
Each row's explicit `failure_at` must match the independent fixed configure
plan; actual verified configure receipts are cross-checked, including pending
controls surviving preflight and being consumed only on backend entry. The
checker never infers failure_at from a candidate status or runtime notices.

The fixed manual pytest command must have `--capture=no`, no xdist or order
plugins, and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Its explicit file order is
`test_cpu_only.py test_public.py test_rejections.py test_private.py`.
Public and rejections use only the public GPU library; private uses only the
bridge. Thus `group_order=["public","private"]` and each group's raw evaluation
ordinal determine serial notice order. `case_ids.json` is a sorted identity
set, not collection order. If file/fixture ordering changes, review this policy
and checker before launch. Original stderr must be captured directly by the
controller, with passed-case stderr retained. Do not extract notices with grep.

## Policy schema

All JSON objects have exact keys unless explicitly described otherwise.
Every artifact receipt is `{"path": canonical_absolute_path,
"sha256": lowercase_sha256, "bytes": nonnegative_integer}`. Booleans do not
stand in for integers. All paths are read-only inputs.

The policy has these keys:

- `schema_version`: 1; `state`: `PREPARED` or `FROZEN`.
- `evidence`: artifact receipts named `source`, `compiler_report`,
  `build_manifest`, `input_plan_source`, `control_plan_source`,
  `receipt_verifier`, `thread_verifier`,
  `trace_verifier`, `controller`, `library`, `bridge`, `thread_binary`, `corpus`,
  `case_ids`. `trace_verifier` must hash this actual `verify.py`. Source/build
  manifests and compiler report must retain complete integrated provenance;
  root review checks their meaning, including same-object bridge linkage.
- `plan`: the input-plan JSON receipt; `group_order`: `["public","private"]`.
- `review`: nonempty independent source/compiler review reference.
- `sites`: object mapping a short site name to `{kind, fields, proof}`.
  `kind` is `upload`, `download`, `launch`, `alloc`, `delete`, `free`, `wait`,
  or `enter_`/`leave_` followed by `update`, `enter_data`, `compute`, `exit_data`.
  `proof` cites reviewed source and
  compiler-report locations. `fields` contains exact string values for `file`,
  `function`, `line` and every additional runtime field, such as `variable`.
  `line` is a positive canonical decimal string. `device`, `threadid`, `bytes`, `devaddr`
  are reserved. Only launch dimensions `num_gangs`, `num_workers`,
  `vector_length`, `grid`, `block` may use JSON null instead of an exact string;
  null permits one to three canonical positive integers, each <= INT32_MAX.
  No arbitrary regex or wildcard is supported. Reuse the same site name for
  multiple arrays if the compiler emits the same helper source site. Exactly
  one `delete` site must describe `file=(OpenACC API) function=acc_free line=1`;
  any `alloc` site must describe `file=(OpenACC API) function=acc_malloc line=1`.
  Physical `free` has the last runtime source site, not the logical acc_free
  API location. List only independently justified possible free sites, each
  with exact fields/queue and proof; never generalise this from a new run.
- `explicit`: `{upload: [nine site names], launch: one site name,
  download: [five site names]}`. Upload order is rho, X/Y/Z tables, fields,
  flags, status, nrot, marker. Download order is fields, flags, status, nrot,
  marker. Every site must have the corresponding kind. These orders must
  match the final reviewed source. Array bytes are calculated independently:
  `8*Nin,40*B,40*Ny,40*Nz,(24+72*mode)*Nout,Nout,4*Nout,4*Nout,4*Nout`.
- `metadata`: a list of `{gap, site, bytes, proof}` describing each extra fixed
  transfer or construct/wait notice per full field region. There are 15 explicit events and 16 insertion
  gaps: 0 before the first upload, 9 before the kernel, 10 after the kernel,
  15 after the final download and before logical delete cleanup. Preserve list
  order within a gap. Transfer bytes must be positive and <= INT32_MAX;
  construct/wait bytes must be zero. Proof must cite independent source/report
  evidence for the exact notice. No extra kernels or allocation API notices
  are permitted in metadata. Enter and Leave line numbers may differ and
  need separate source-proved sites.
- `process_notices`: `{python:{prefix:[],suffix:[]},
  pthread:{prefix:[],suffix:[]}}`. Each optional process-level transfer is
  `{site,bytes,proof}`, with the same restrictions. This is for independently
  proved fixed initialization/finalization notices, not unreviewed output.

Logical `acc_free` delete notices are required in each Python call's cleanup
phase, after its transfer/kernel/construct sequence: nine after a completed
workspace (including corruption), zero for preflight or host acquisition
failure 1..9, and `failure_at-10` for device acquisition failure 10..18.
Expected counts are **2484 Python + 54 pthread = 2538 planned logical deletes**;
these are pre-run expectations, not actual-run results. Pthread checks only
aggregate counts because interleaving prevents call attribution.

Every alloc/delete/free notification must have source-proved exact fields,
device 0, a nonzero 64-bit hex address and positive bytes. `alloc` and `free`
are then reported in `runtime_api_observations` with complete observed counts,
byte totals and unique addresses; their occurrence counts are not pre-fitted
to a candidate. Delete comparison binds its logical count/site/phase, while
its raw bytes and addresses are also reported as observations. No alloc/free
pairing, net balance, rounding, suballocation, reuse model, physical VRAM bound
or mapping from an API address to a private array is inferred. Physical pool
bytes do not use the array INT32 cap. Independent private ledgers and source
review remain responsible for actual array acquisition, ownership and cleanup;
all reviewed-source and controller gates remain necessary for acceptance.

Notifications use full NVHPC lines, e.g. the following **invented** grammar:

```text
upload CUDA data file=/invented/source.f90 function=upload_real1 line=123 device=0 threadid=1 variable=x bytes=2520
launch CUDA kernel file=/invented/source.f90 function=launch_kernel line=456 device=0 threadid=1 num_gangs=2 num_workers=1 vector_length=128 grid=2 block=128
```

Fields can appear in any order; values are exact, except the documented launch
dimension fields. UTF-8 source paths with spaces are supported. `threadid` is a
canonical nonnegative runtime integer; it is never interpreted as Linux TID.
NVHPC pads kind/CUDA/data/kernel and key separators with horizontal whitespace;
single spaces, repeated spaces and tabs are accepted at those separators.
Whitespace inside fixed field values is preserved, including source paths.
The parser also recognises `alloc`, `delete`, `free`, `Implicit wait`, and
Enter/Leave notifications for `update`, `enter data`, `compute`, `exit data`.
Every occurrence still requires an exact reviewed site, function, line and
queue (where present). Positional Leave locations are normalised for comparison.
Allocation-class notices require a nonzero 64-bit hexadecimal `devaddr` and a
positive byte count. No address-to-private-buffer relationship follows merely
from parsing those fields.
If the final installed compiler uses a different grammar, preparation must
stop for a reviewed checker change before the policy is frozen.

The pure suite includes deidentified format examples read from the already
accepted M3B0 stderr archive (no replay of its executable). This is explicitly
old-format parser preparation, not M3B1 runtime acceptance. The old M3B0 verifier
bound its 240 producer resource records and selected kernel/transfer notices;
it did not establish a general runtime allocator/pool proof. That accepted
finite boundary is preserved. The M3B1 parser's logical-delete comparison and
physical observation boundaries were independently reviewed; no real policy
or M3B1 execution is frozen or accepted by these examples.

## Compare after the user's single manual run

First obtain PASS from the existing receipt and pthread verifiers. Their raw
receipt/artifact formats remain unchanged. This checker rehashes all bound
artifacts, checks binary identities against policy, maps cases to the pre-run
plan and derives mode/backend from validated 40-byte options. It compares the
Python stream's exact transfer/kernel/construct sequence and logical cleanup
counts. Physical alloc/free remain the explicitly limited observations above.
Concurrent pthread transfer/kernel/construct notices and logical delete counts
are checked only as aggregate site/count/byte multisets; `verify_threads.py` remains
responsible for the program's own Linux-thread causal and output checks.
No one-to-one mapping between runtime notices and Linux threads is claimed.

The trusted controller writes a capture JSON with exact keys:

```text
schema_version=1, state="COMPLETED",
policy=<policy receipt>, controller=<controller source receipt>,
receipt_check=<receipt-check report receipt>, thread_check=<thread-check report receipt>,
python_stderr=<original stderr receipt>, thread_stderr=<original stderr receipt>,
capture_no=true, plugin_autoload_disabled=true,
group_order=["public","private"], python_exit=0, thread_exit=0, timed_out=false
```

The post-run bundle has exact keys `schema_version=1`, `policy`,
`receipt_check`, `thread_check`, `python_stderr`, `thread_stderr` (the same
receipts), plus `controller_capture` (the capture JSON receipt).
Use a fresh report path:

```text
python tests/openacc_backend_trace/verify.py --policy /absolute/frozen/policy.json --policy-sha256 <independently-frozen-sha256> --bundle /absolute/attempt/bundle.json --report /absolute/new/trace-check.json
```

The trusted package/reviewer must establish that the digest was frozen before
launch and that upstream reports and capture receipts came from the bound
verifiers/controller and original process streams. Hashes alone cannot prove
execution or temporal provenance. The checker does not independently prove
loader provenance, exits, complete source semantics, or no CPU fallback.
Those remain controller/source-review acceptance gates, never implicit PASS.

Exit 0 is scoped notice-comparison PASS under a FROZEN policy. Exit 2 is
PREPARED under a PREPARED policy even if all comparisons match; exit 1 is FAILED.
Missing/non-PASS/NOT_TESTED upstream results, unknown notices and mismatches
always fail. Existing report files are never overwritten. No real-density,
scientific or performance acceptance follows from any result here.
