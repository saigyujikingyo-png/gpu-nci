# Offline CPU CLI

Run from any working directory, using Python 3.12 and a built native driver:

```sh
python /absolute/path/to/cli/nci_cli.py run --card /path/card.json --driver /path/nci_driver --output-dir /existing/parent/new-run
```

The complete required card and private protocol are in [cli-contract.md](cli-contract.md).
Input paths are relative to the card directory; driver/output paths are relative
to the invocation directory. The output parent must already exist, and the run
directory must be new. There is no overwrite or resume mode. Original inputs and
cards are left intact. All runtime dependencies are from the Python standard library.

The CLI freezes card bytes and streams a verified input snapshot, writes the
validated Fortran namelist, obtains native build declarations, fingerprints the
driver/library, and runs the worker with its declared timeout. Logs, partial
outputs and failure receipts remain in the new directory. A failure exits nonzero;
inspect `manifest.json`, `native.json` when present, and the logs. Ctrl+C stops
the CLI's own direct child. No other application is stopped.

Only exit zero with `SUCCESS` means numerical completion. `SUCCESS` contains the
SHA-256 of the final `manifest.json` and a newline. The manifest records source
declarations separately from verified byte fingerprints, the original native
receipt, and per-file hashes, sizes, units, shapes, point/component ordering and
binary types. It does not authenticate producer claims or certify scientific
accuracy. Memory reservations cover tracked arrays and allowances, not total RSS.
Real-density acceptance, scientific uncertainty, GPU fields and performance
remain governed by the central [status](status.md) and later manual-run gates.

Protocol regressions can run independently of a native build:

```sh
NCI_CLI=/absolute/path/to/cli/nci_cli.py python -m unittest discover -s /absolute/path/to/tests/cli -p 'test_*.py' -v
```

These tests use an explicitly synthetic POSIX stub executable and opaque input
bytes. They validate schema, snapshots, receipts, output metadata and failure
handling; they provide no native numerical or scientific evidence. Root-owned
end-to-end tests separately inspect real native field values.
