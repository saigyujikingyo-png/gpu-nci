#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic M3A source adapter (docs/openacc-probe-contract.md).

Reads src/backend_cpu/nci_kinds.f90 and nci_numerics.f90 of a production
checkout and writes, into a build directory only:

  host/nci_numerics.f90    production + test-only `public :: c_cbrt`
  device/nci_kinds.f90     production + `!$acc routine seq` in every module
                           procedure and in the pure scalbn binding interface
  device/nci_numerics.f90  the same for its procedures and the pure cbrt
                           binding, plus the test-only visibility

with one exact unified diff per generated file, SHA256SUMS and manifest.json.
The host reference compiles the production nci_kinds.f90 in place.

Generated files differ from production only by added lines: no production
line is changed or removed. Every insertion point is an exact anchor. If an
anchor is missing or repeated, the procedure list differs from the frozen one,
or a result is anything but its original plus the allowed lines, nothing is
written and the exit status is 1.
"""
import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

KINDS = "src/backend_cpu/nci_kinds.f90"
NUMERICS = "src/backend_cpu/nci_numerics.f90"

ROUTINE = "!$acc routine seq"

KINDS_BINDING = (
    "  interface",
    "    pure function c_scalbn(x,n) bind(C,name='scalbn') result(y)",
    "      import :: c_double,c_int",
    "      real(c_double),value :: x",
    "      integer(c_int),value :: n",
    "      real(c_double) :: y",
    "    end function c_scalbn",
    "  end interface",
)
KINDS_PROCEDURES = (
    "pow2_scale", "binary_exponent", "binary_fraction", "qnan", "is_finite", "all_finite",
)

NUMERICS_BINDING = (
    "  interface",
    "    pure function c_cbrt(x) bind(C, name='cbrt') result(y)",
    "      import :: c_double",
    "      real(c_double), value :: x",
    "      real(c_double) :: y",
    "    end function c_cbrt",
    "  end interface",
)
NUMERICS_PUBLIC = "  public :: rdg_from_gradient"
NUMERICS_VISIBILITY = "  public :: c_cbrt  ! M3A test-only visibility"
NUMERICS_PROCEDURES = (
    "stencil61", "fro_norm", "hypot2", "jinv_matrix", "underflow_floor", "fd1", "afd1",
    "axial", "mixed", "index_derivatives", "cartesian_transform", "bound_matrix",
    "jacobi_rotate", "sort3", "eig3_jacobi", "rdg_from_gradient", "point_eval",
)

HEADER = re.compile(
    r"^( *)(?:(?:pure|elemental|impure|recursive)\s+)*(?:function|subroutine)\s+(\w+)\s*\(",
    re.IGNORECASE)


class Drift(Exception):
    """An anchor or postcondition does not hold; nothing may be written."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_lines(root, rel):
    data = (root / rel).read_bytes()
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise Drift(f"{rel}: not ASCII")
    if "\r" in text or not text.endswith("\n"):
        raise Drift(f"{rel}: expected LF line endings and a final newline")
    return data, text[:-1].split("\n")


def find_line(lines, text, rel):
    hits = [i for i, line in enumerate(lines) if line == text]
    if len(hits) != 1:
        raise Drift(f"{rel}: anchor {text!r} found {len(hits)} times, expected once")
    return hits[0]


def find_block(lines, block, rel):
    n = len(block)
    hits = [i for i in range(len(lines) - n + 1) if tuple(lines[i:i + n]) == block]
    if len(hits) != 1:
        raise Drift(f"{rel}: binding {block[1].strip()!r} found {len(hits)} times, expected once")
    return hits[0]


def procedure_headers(lines, expected, rel):
    """(line index, indentation) of every module procedure header after `contains`."""
    start = find_line(lines, "contains", rel) + 1
    found = []
    for i in range(start, len(lines)):
        match = HEADER.match(lines[i])
        if match:
            if lines[i].rstrip().endswith("&"):
                raise Drift(f"{rel}:{i + 1}: continued procedure header")
            found.append((i, match.group(1), match.group(2).lower()))
    names = tuple(name for _, _, name in found)
    if names != expected:
        raise Drift(f"{rel}: procedure list drifted: found {names}, expected {expected}")
    return [(i, indent) for i, indent, _ in found]


def adapt(lines, rel, *, binding=None, procedures=None, visibility=None):
    """Insert only the allowlisted lines; returns (new lines, edit counts)."""
    inserts, counts = {}, {}

    def add(index, line, kind):
        inserts.setdefault(index, []).append(line)
        counts[kind] = counts.get(kind, 0) + 1

    if binding is not None:
        header = find_block(lines, binding, rel) + 1
        indent = re.match(r" *", lines[header]).group(0)
        add(header, indent + "  " + ROUTINE, "acc_routine_seq_in_binding")
    if procedures is not None:
        for i, indent in procedure_headers(lines, procedures, rel):
            add(i, indent + "  " + ROUTINE, "acc_routine_seq_in_procedures")
    if visibility is not None:
        add(find_line(lines, NUMERICS_PUBLIC, rel), visibility, "visibility_lines")
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        out.extend(inserts.get(i, ()))
    check_allowlist(lines, out, rel, [line for new in inserts.values() for line in new])
    return out, counts


def check_allowlist(original, generated, rel, added):
    """Independent postcondition: deleting the added lines from the result must
    give back the original exactly, line for line."""
    allowed = set(added)
    for line in original:
        if line in allowed or line.lstrip().lower().startswith("!$acc"):
            raise Drift(f"{rel}: original already contains {line.strip()!r}")
    kept = [line for line in generated if line not in allowed]
    if kept != original or len(generated) - len(kept) != len(added):
        raise Drift(f"{rel}: generated text differs outside the allowlist")


def unified(original, generated, src, dst):
    return "".join(difflib.unified_diff(
        [line + "\n" for line in original], [line + "\n" for line in generated],
        fromfile="a/" + src, tofile="b/" + dst, n=3))


def generate(root):
    kinds_data, kinds = read_lines(root, KINDS)
    numerics_data, numerics = read_lines(root, NUMERICS)
    plan = (
        ("host/nci_numerics.f90", NUMERICS, numerics, dict(visibility=NUMERICS_VISIBILITY)),
        ("device/nci_kinds.f90", KINDS, kinds,
         dict(binding=KINDS_BINDING, procedures=KINDS_PROCEDURES)),
        ("device/nci_numerics.f90", NUMERICS, numerics,
         dict(binding=NUMERICS_BINDING, procedures=NUMERICS_PROCEDURES,
              visibility=NUMERICS_VISIBILITY)),
    )
    files, outputs = {}, {}
    for dst, src, lines, edits in plan:
        new, counts = adapt(lines, src, **edits)
        text = ("\n".join(new) + "\n").encode("ascii")
        diff = unified(lines, new, src, dst).encode("ascii")
        files[dst], files[dst + ".diff"] = text, diff
        outputs[dst] = {"from": src, "sha256": sha256(text), "bytes": len(text),
                        "diff": dst + ".diff", "diff_sha256": sha256(diff), "added_lines": counts}
    manifest = {
        "contract": "docs/openacc-probe-contract.md (M3A1)",
        "generator_sha256": sha256(Path(__file__).read_bytes()),
        "production_root": str(root),
        "inputs": {KINDS: {"sha256": sha256(kinds_data), "bytes": len(kinds_data)},
                   NUMERICS: {"sha256": sha256(numerics_data), "bytes": len(numerics_data)}},
        "host_compiles_unchanged": [KINDS],
        "outputs": outputs,
    }
    sums = "".join(f"{sha256(files[name])}  {name}\n" for name in sorted(files))
    files["SHA256SUMS"] = sums.encode("ascii")
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--production-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        files = generate(args.production_root.resolve())
    except (Drift, OSError) as error:
        print(f"M3A generator: ANCHOR DRIFT OR INPUT ERROR, nothing written: {error}", file=sys.stderr)
        return 1
    for name, data in files.items():
        path = args.output_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"M3A generator: wrote {len(files)} files to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
