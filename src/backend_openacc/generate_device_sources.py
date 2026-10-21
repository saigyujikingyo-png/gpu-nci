#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Insertion-only device adapter of the production sources for nci_openacc.

Contract: docs/openacc-public-contract.md (M3B1). Reads the production
nci_kinds.f90, nci_numerics.f90 and nci_kernel.f90 from --production-dir (the
CPU source directory) and writes into --output-dir only:

  nci_kinds.f90     `!$acc routine seq` in the pure scalbn binding interface
                    and in each of the 6 module procedures
  nci_numerics.f90  the same in the pure cbrt binding interface and in each of
                    the 17 module procedures
  nci_kernel.f90    the same in on_boundary and in classify_point (after its
                    complete, continued header), plus one visibility line
                    making axis_table and classify_point public

with one exact unified diff per file, SHA256SUMS and manifest.json.

No production line is changed, reordered or removed. Deleting exactly the
inserted lines from a generated file must give back the original bytes. Every
insertion point is an exact anchor: a missing or repeated anchor, a procedure
list that differs from the frozen one, an unsupported header form or any other
failed postcondition writes nothing and exits with status 1. This generator is
separate from the frozen M3A adapter in experiments/openacc_probe, which
rejects continued headers.
"""
import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

ROUTINE = "!$acc routine seq"

KINDS = "nci_kinds.f90"
NUMERICS = "nci_numerics.f90"
KERNEL = "nci_kernel.f90"

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
NUMERICS_PROCEDURES = (
    "stencil61", "fro_norm", "hypot2", "jinv_matrix", "underflow_floor", "fd1", "afd1",
    "axial", "mixed", "index_derivatives", "cartesian_transform", "bound_matrix",
    "jacobi_rotate", "sort3", "eig3_jacobi", "rdg_from_gradient", "point_eval",
)

KERNEL_PROCEDURES = (
    "preflight_density", "axis_table", "on_boundary", "classify_point", "evaluate_grid",
    "diagnose_point",
)
KERNEL_DEVICE = ("on_boundary", "classify_point")
KERNEL_PUBLIC = "  public :: preflight_density, evaluate_grid, diagnose_point"
KERNEL_VISIBILITY = "  public :: axis_table, classify_point  ! M3B1 OpenACC backend visibility"

HEADER = re.compile(
    r"^( *)(?:(?:pure|elemental|impure|recursive)\s+)*(?:function|subroutine)\s+(\w+)\s*\(",
    re.IGNORECASE)

# (output name, input name, binding block, procedures receiving the directive,
#  complete frozen procedure list, visibility anchor/line, inserted-line count)
PLAN = (
    (KINDS, KINDS_BINDING, KINDS_PROCEDURES, KINDS_PROCEDURES, None, 7),
    (NUMERICS, NUMERICS_BINDING, NUMERICS_PROCEDURES, NUMERICS_PROCEDURES, None, 18),
    (KERNEL, None, KERNEL_DEVICE, KERNEL_PROCEDURES, (KERNEL_PUBLIC, KERNEL_VISIBILITY), 3),
)


class Drift(Exception):
    """An anchor or postcondition does not hold; nothing may be written."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_lines(path, name):
    data = path.read_bytes()
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise Drift(f"{name}: not ASCII")
    if "\r" in text or not text.endswith("\n"):
        raise Drift(f"{name}: expected LF line endings and a final newline")
    lines = text[:-1].split("\n")
    for number, line in enumerate(lines, 1):
        if line.lstrip().lower().startswith("!$acc"):
            raise Drift(f"{name}:{number}: original already contains an OpenACC directive")
    return data, lines


def find_line(lines, text, name):
    hits = [i for i, line in enumerate(lines) if line == text]
    if len(hits) != 1:
        raise Drift(f"{name}: anchor {text!r} found {len(hits)} times, expected once")
    return hits[0]


def find_block(lines, block, name):
    n = len(block)
    hits = [i for i in range(len(lines) - n + 1) if tuple(lines[i:i + n]) == block]
    if len(hits) != 1:
        raise Drift(f"{name}: binding {block[1].strip()!r} found {len(hits)} times, expected once")
    return hits[0]


def header_end(lines, start, name):
    """Index of the last line of the procedure header beginning at start.

    A header line ending in '&' continues on the next line. Comments inside a
    header are not supported, so an '&' can never hide behind one.
    """
    i = start
    while True:
        if i >= len(lines):
            raise Drift(f"{name}:{start + 1}: unterminated procedure header")
        if "!" in lines[i]:
            raise Drift(f"{name}:{i + 1}: comment inside a procedure header")
        code = lines[i].rstrip()
        if i > start and not code.strip():
            raise Drift(f"{name}:{i + 1}: blank line inside a procedure header")
        if not code.endswith("&"):
            return i
        i += 1


def procedure_headers(lines, expected, name):
    """{procedure: (header start, header end, indentation)} after `contains`."""
    start = find_line(lines, "contains", name) + 1
    found = []
    i = start
    while i < len(lines):
        match = HEADER.match(lines[i])
        if match:
            end = header_end(lines, i, name)
            found.append((match.group(2).lower(), i, end, match.group(1)))
            i = end + 1
        else:
            i += 1
    names = tuple(entry[0] for entry in found)
    if names != expected:
        raise Drift(f"{name}: procedure list drifted: found {names}, expected {expected}")
    return {entry[0]: entry[1:] for entry in found}


def adapt(lines, name, binding, device, procedures, visibility, count):
    """Original lines plus the allowlisted insertions; returns (lines, inserted
    output indices, counts by kind)."""
    inserts, counts = {}, {}

    def add(after, line, kind):
        inserts.setdefault(after, []).append(line)
        counts[kind] = counts.get(kind, 0) + 1

    if binding is not None:
        header = find_block(lines, binding, name) + 1
        indent = re.match(r" *", lines[header]).group(0)
        add(header, indent + "  " + ROUTINE, "acc_routine_seq_in_binding")
    headers = procedure_headers(lines, procedures, name)
    for procedure in device:
        _, end, indent = headers[procedure]
        add(end, indent + "  " + ROUTINE, "acc_routine_seq_in_procedures")
    if visibility is not None:
        anchor, line = visibility
        add(find_line(lines, anchor, name), line, "visibility_lines")

    out, inserted = [], []
    for i, line in enumerate(lines):
        out.append(line)
        for new in inserts.get(i, ()):
            inserted.append(len(out))
            out.append(new)
    check(lines, out, inserted, name, count)
    return out, inserted, counts


def check(original, generated, inserted, name, count):
    """Independent postconditions on the generated lines."""
    if len(inserted) != count or len(generated) != len(original) + count:
        raise Drift(f"{name}: expected exactly {count} inserted lines, got {len(inserted)}")
    added = {generated[i] for i in inserted}
    for line in original:
        if line in added:
            raise Drift(f"{name}: original already contains {line.strip()!r}")
    by_index = [line for i, line in enumerate(generated) if i not in set(inserted)]
    by_text = [line for line in generated if line not in added]
    if by_index != original or by_text != original:
        raise Drift(f"{name}: generated text differs from the original outside the insertions")
    for i in inserted:
        text = generated[i].strip()
        if text != ROUTINE and not text.startswith("public :: "):
            raise Drift(f"{name}: unexpected inserted line {text!r}")


def unified(original, generated, name):
    return "".join(difflib.unified_diff(
        [line + "\n" for line in original], [line + "\n" for line in generated],
        fromfile="a/" + name, tofile="b/" + name, n=3))


def generate(production_dir):
    files, inputs, outputs = {}, {}, {}
    for name, binding, device, procedures, visibility, count in PLAN:
        data, lines = read_lines(production_dir / name, name)
        new, inserted, counts = adapt(lines, name, binding, device, procedures, visibility, count)
        text = ("\n".join(new) + "\n").encode("ascii")
        stripped = "\n".join(line for i, line in enumerate(new) if i not in set(inserted)) + "\n"
        if stripped.encode("ascii") != data:
            raise Drift(f"{name}: removing the insertions does not restore the original bytes")
        diff = unified(lines, new, name).encode("ascii")
        files[name], files[name + ".diff"] = text, diff
        inputs[name] = {"sha256": sha256(data), "bytes": len(data)}
        outputs[name] = {
            "from": name, "sha256": sha256(text), "bytes": len(text),
            "diff": name + ".diff", "diff_sha256": sha256(diff),
            "inserted_line_numbers": [i + 1 for i in inserted], "added_lines": counts,
        }
    manifest = {
        "contract": "docs/openacc-public-contract.md (M3B1)",
        "generator_sha256": sha256(Path(__file__).read_bytes()),
        "production_dir": str(production_dir),
        "inputs": inputs,
        "outputs": outputs,
    }
    sums = "".join(f"{sha256(files[name])}  {name}\n" for name in sorted(files))
    files["SHA256SUMS"] = sums.encode("ascii")
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--production-dir", required=True, type=Path,
                        help="directory holding the production nci_kinds/numerics/kernel.f90")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        files = generate(args.production_dir.resolve())
    except (Drift, OSError) as error:
        print(f"nci_openacc generator: ANCHOR DRIFT OR INPUT ERROR, nothing written: {error}",
              file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (args.output_dir / name).write_bytes(data)
    print(f"nci_openacc generator: wrote {len(files)} files to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
