# Independent M3B0 resource verifier

This directory contains independent static fixtures and a compare-only verifier
for the frozen [resource contract](../../docs/openacc-resource-contract.md).
It does not import the candidate resource implementation or start any program.
The public ABI, CPU formulas, M3A fixtures and numerical tolerances are unchanged.

`frozen/manifest.json` freezes 79 input/output binary64 bit pairs and the exact
240 resource events. Values follow the contract's dyadic rational expressions,
so addition of one is exact; `test_verify.py` independently checks them with
Python `Fraction` and binary64 packing. The fixture SHA-256 is
`fc63b07d695ba4540eda8261dc2a4e6d3ac2c94fea18ff49697f8e76d6c1ce48`.
The verifier checks this digest and the frozen contract digest, not candidate
output used as a reference. No floating-point tolerance is involved.

## Pure preparation checks

```text
python -m pytest -q tests/openacc_resources
```

These tests use invented output, runtime notifications, source captures and
placeholder files named `not-an-executable` and `not-a-runner.txt`. They never
launch a native candidate, compiler, GPU, solver or subprocess. A selftest PASS
validates fixture/parser behavior only and is not device acceptance.
The author preparation run completed 96 pure tests; native candidate execution
remained NOT_STARTED.

## Compare-only command

```text
python tests/openacc_resources/verify.py --verify --manifest tests/openacc_resources/frozen/manifest.json --stdout /absolute/run.stdout --stderr /absolute/run.stderr --evidence /absolute/evidence.json --report /absolute/NEW-report.json
```

The report is created exclusively; an existing file is never overwritten.
Exit/status pairs are `0/PASS`, `1/FAILED`, and `2/NOT_TESTED`. A no-device result
requires explicit inventory absence **before any candidate invocation** and
omits both stdout/stderr command arguments. Any attempted nonzero exit,
including candidate exit3, or timeout is FAILED. A `no_candidate` state cannot
PASS. Reports state the limited synthetic scope and retain artifact hashes.

Stdout must be exactly 96 nonempty ASCII lines. Stderr is strict UTF-8 because
NVIDIA metadata may include Chinese source paths. All raw bytes are retained
and hashed. Resource lines are parsed directly from original stderr; no
separate unbound ledger file is accepted. Acquisition/unwind order, presence
queries, per-object host/device/map lifetimes, peak counts/bytes and final zero
are checked against all 240 frozen events.

The NVIDIA `launch CUDA kernel`, `upload CUDA data`, and `download CUDA data`
notifications permit legitimate file/function/line/thread and other metadata,
but each requires exactly one `device=0`; every transfer requires exactly one
`bytes=...`. Malformed relevant notification lines fail. Additional allocation,
free, wait and diagnostic lines are preserved. Require exactly 3 kernels,
8 uploads/1332 bytes and 6 downloads/948 bytes. Input A/B uploads may occur after
their own preparation; no recovery transfer/kernel is permitted. Each kernel
requires its two poison uploads and two downloads in the correct phase. Output
and marker transfers within a pair may be ordered either way. The first two
kernels precede A release; the third follows A release and precedes B release.

## Evidence schema version1

Every receipt has **exactly** `path`, `sha256`, `bytes`: canonical absolute path,
lowercase SHA-256, and nonnegative integer byte count (bool is rejected). All
referenced files are rehashed after comparison. JSON duplicate keys, nonfinite
constants, missing/extra schema fields and integer/bool substitutions fail.

Executed evidence has exactly these top-level fields:

```json
{
  "schema_version": 1,
  "state": "executed",
  "manifest": {"path": "/absolute/manifest.json", "sha256": "...", "bytes": 1},
  "contract": {"path": "/absolute/openacc-resource-contract.md", "sha256": "...", "bytes": 1},
  "runner": {"path": "/absolute/runner.py", "sha256": "...", "bytes": 1},
  "source_manifest": {"path": "/absolute/source.json", "sha256": "...", "bytes": 1},
  "compiler_report": {"path": "/absolute/build.log", "sha256": "...", "bytes": 1},
  "source_snapshots": [],
  "device_count": 1,
  "selected_device": 0,
  "device_identity": "recorded actual NVIDIA identity",
  "runtime_evidence": {"path": "/absolute/run.stderr", "sha256": "...", "bytes": 1},
  "run": {
    "binary": {"path": "/absolute/m3b_resources", "sha256": "...", "bytes": 1},
    "stdout": {"path": "/absolute/run.stdout", "sha256": "...", "bytes": 1},
    "stderr": {"path": "/absolute/run.stderr", "sha256": "...", "bytes": 1},
    "command": ["/absolute/m3b_resources"],
    "input_mode": "none",
    "stdin_mode": "devnull",
    "returncode": 0,
    "timed_out": false,
    "timeout_seconds": 30,
    "environment": {
      "ACC_DEVICE_TYPE": "nvidia",
      "ACC_DEVICE_NUM": "0",
      "NVCOMPILER_ACC_NOTIFY": "31",
      "NVCOMPILER_ACC_SYNCHRONOUS": null,
      "PGI_ACC_SYNCHRONOUS": null,
      "CUDA_LAUNCH_BLOCKING": null
    }
  }
}
```

The examples use abbreviated digest strings only for explanation; actual
receipts require 64 lowercase hex digits. `source_snapshots` must contain one
object with exactly `role="integrated"`, `path`, `commit`, `tree`,
`clean_before=true`, `clean_after=true`, `before`, `after`. Each capture object
has exactly `head`, `tree`, `status` receipts. HEAD/tree file contents are the
matching 40 lowercase hex digits followed by LF; raw porcelain status is empty.
The captures bind actual pre/post-candidate checks, rather than two freeze-time
copies. The controller rechecks after verification as well.

The sealed source manifest has exactly `schema_version=1`, `root`, `commit`,
`tree`, `files`; `files` is a nonempty list of receipts for all tracked public
files under the canonical integrated root. The verifier rehashes every listed
file, rejects duplicates/private paths/escapes, requires the contract, fixture
and actual verifier itself, and cross-checks both source captures. **Completeness
of the tracked-file index and truthful capture timing belong to the reviewed
controller and independent source review.** This compare-only verifier does
not invoke Git or prove those facts from a list of hashes. Compiler/source
review also checks real build flags, actual API calls and absence of host
replacement of GPU results; a valid-looking log is not an implementation proof.

`runtime_evidence` must equal `run.stderr` exactly, and all CLI paths bind the
corresponding receipts exactly. Identical bytes at another path cannot replace
an output or runtime log. `run.environment` contains only the six listed keys;
the controller keeps its wider safe environment whitelist in its own receipt.

Missing-device evidence has exactly `schema_version=1`, `state="no_device"`,
`manifest`, `contract`, `device_count=0`, and nonempty `reason`. It forbids any
`run` object and yields NOT_TESTED. Failed/partial executions are never a
missing-device substitute. All PASS claims remain restricted to this finite
synthetic configuration, without public backend or scientific acceptance.
