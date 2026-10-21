# M3B1 preparation status

The optional public OpenACC backend and its independent tests are implemented.
The complete integrated source at `a631ca78fd22d13b6f07b9e8baf7d6d49e457087`
was compiled with GNU 13.3 Debug and NVHPC 26.9 Debug. Both configure/build
sequences returned zero. **M3B1 native acceptance, scientific validation and
performance measurements remain NOT_RUN.** These builds do not establish
correct GPU execution.

## What was checked

- All 157 files extracted from the Git archive matched their Git blobs.
- The mathematical kinds, numerical routines, field kernel and public header
  are unchanged from the accepted M3B0 main revision.
- `nci_cpu` remains separate from the default-off `nci_openacc` library.
  Both export only the three existing ABI v1 functions. Neither GNU nor NVHPC
  CPU library imports the GPU runtime.
- The private test bridge links the same seven production objects as the
  OpenACC shared library. The pthread test links that shared library.
- Independent source review closed the staging-cleanup, failed-destroy and
  unmap-accounting findings, and checked the private observation/failure hooks
  against the [public-library contract](openacc-public-contract.md).
- The public-test receipt/fixture selfchecks passed 171 pure checks. The
  runtime-notice checker passed 54 pure checks. These tests use invented
  records and static input plans; they do not execute the candidate library.
- A standalone controller has bounded stages, owned-process cleanup, explicit
  stop handling and single-use attempts. Its focused fake-process/file-system
  checks were reviewed separately from scientific validation.

The compiled metadata distinguishes 172 bytes of explicit scalar values from
the full aligned 272-byte kernel parameter area. Fixed descriptors, runtime
storage and compiler/device scratch are not counted as tracked field arrays.
No actual peak GPU memory or speedup has been measured for M3B1.

## Why a diagnostic run comes first

The final host object has nine matching data-entry/data-exit descriptors for
the nine planned arrays. An initial manual count of ten exits was corrected
by exact relocation inspection. This does not by itself prove the complete
NVHPC construct/wait and memory-pool notification sequence.

The full runtime-trace policy therefore remains PREPARED. Unknown notifications
must not be silently ignored, represented as an empty expected list, or fitted
after execution and used to declare the same execution accepted.

The next finite package is a **user-launched diagnostic capture** of one
existing test:

```text
test_public.py::test_original_mathematical_edge_cases[constant-diagnostic]
```

It contains one public evaluation, one context and a 7 x 9 x 11 constant-density
grid (693 points), with the existing diagnostic-output mathematics and
tolerances. `NVCOMPILER_ACC_NOTIFY=31` and direct stderr capture preserve the
runtime evidence. The planned tracked arrays are 82,161 bytes on each of the
host and device sides; this is an input-derived array count, not measured
memory usage or a bound on the driver/runtime.

A successful diagnostic process only produces
`CAPTURE_COLLECTED_REVIEW_REQUIRED`. It does not pass the full M3B1 acceptance
gate. Unexpected/failed output remains preserved without an automatic retry.
After source/compiler/runtime evidence explains the observations, an independent
review must freeze a new policy before a separate complete acceptance run.

## Acceptance still required

The prepared complete suite remains 148 native pytest cases, 350 Python
evaluations plus six pthread evaluations, with 278 planned GPU field regions.
The final source also has 22 GNU CTest entries. These inventories are plans,
not passing results. The single diagnostic case does not replace them.

Complete CPU regression, public/private GPU checks, failure cleanup, thread
migration, original runtime notices, controller receipts and applicable CI
must pass on the integrated source before merging this backend to main.
CLI GPU integration is a later M3B2 step. Real-density validation and measured
performance are later work under the unchanged scientific specification.

## AI-assisted development

Claude Opus 5.5 implemented and repaired the Fortran backend. GPT-6.1 Sol
authored independent tests, receipt/trace checks and execution preparation.
The primary conversation coordinated the architecture and integration; a
separate Astra review checked source and evidence boundaries. AI-written
code and review are not independent scientific results. No internal research
group data were used in this preparation.

`RESEARCH_HANDOFF.md` remains deferred until the first real scientific
end-to-end example has run and been accepted.
