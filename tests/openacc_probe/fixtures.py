"""Deterministic finite M3A1 corpus. Generation never runs a native binary."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.linalg import eigvalsh

from oracle import (ROOT, SIGN, INF, QNAN, bits, classification, derivatives,
                    rdg_reference, scalar_expected, token, value)

GATES = {
    "scalar_scaled_fraction": "exact_bits; nonfinite scale classification only",
    "scalar_cbrt": {"ulp": 1, "signed_zero_inf_nan": "separate classification"},
    "derivative_eigen": {"atol": "1e-12", "rtol": "1e-10"},
    "rdg": {"atol": "1e-11", "rtol": "1e-9"},
    "bound_tau_host_portability": {"atol_eta_units": 8, "rtol": "1e-10"},
    "tau_relation": "exact bits: (1e-12 + 1e-10*max(abs(lambda1),abs(lambda3))) + bound",
    "uncertain": "exact: not(abs(lambda2)>tau); host/device equality",
    "reference_sign_band": "1e-9", "raw_sign": "exact sign(lambda2)*original center rho",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar_cases():
    seeds = [("positive zero", 0), ("negative zero", SIGN),
        ("least subnormal", 1), ("subnormal16", 16),
        ("representative subnormal", 0x8000000000000),
        ("largest subnormal", 0xfffffffffffff),
        ("least normal", 0x10000000000000), ("largest finite", INF-1),
        ("one", bits(1.)), ("two", bits(2.)), ("eight", bits(8.)),
        ("twenty seven", bits(27.))]
    cases = [(label, raw, 0) for label, raw in seeds]
    cases += [("negative " + label, raw | SIGN, 0) for label, raw in seeds[2:]]
    cases += [("endpoint .75", bits(.75), s) for s in (1024, -1073, -1074, -1075)]
    cases += [("half ULP tie signed zero", bits(s*.5), -1074) for s in (1, -1)]
    cases += [("normal/subnormal tie", bits(value(0x1fffffffffffff)), -1),
              ("genuine overflow", INF-1, 1), ("large exponent overflow", 1, 4096),
              ("large exponent underflow", bits(-1.), -4096),
              ("positive infinity", INF, 0), ("negative infinity", SIGN|INF, 1),
              ("quiet NaN", QNAN, -1), ("signed payload NaN", SIGN|QNAN|17, 4096)]
    return [dict(label=label, x=f"{raw:016X}", shift=shift,
                 expected=scalar_expected(raw, shift)) for label, raw, shift in cases]


def rdg_cases():
    eta, largest = value(1), value(INF-1)
    data = [
        ("zero gradient", [0., -0., 0.], .015625, "standard"),
        ("intermediate quotient overflow final finite", [-value(0x7f90000000000000),0.,0.], .015625, "relative16eps"),
        ("physical norm overflow final finite", [largest,largest,0.], 64., "relative16eps"),
        ("subnormal gradient finite result", [eta,eta,eta], value(0x1a70000000000000), "relative16eps"),
        ("genuine final underflow", [eta,eta,eta], value(0x6570000000000000), "class_zero"),
        ("genuine final overflow", [1.,0.,0.], value(0x07b0000000000000), "class_inf"),
        ("nonzero least-subnormal RDG", [8*eta,0.,0.], 1., "subnormal1ulp"),
        ("nonzero subnormal vector RDG", [16*eta]*3, 1., "subnormal1ulp"),
        ("ordinary signed gradient", [-.125,.25,-.5], 20., "standard")]
    result = []
    for label, g, rho, gate in data:
        decimal, expected = rdg_reference(rho, g)
        result.append(dict(label=label, gradient=[token(v) for v in g], rho=token(rho),
            expected=expected, decimal=decimal,
            expected_class=classification(int(expected,16)), gate=gate))
    return result


def polynomial(h, g=(.125,-.25,.5), offset=20.):
    q = np.moveaxis(np.indices((5,5,5)), 0, -1).astype(float) - 2
    h = np.array(h, dtype=float)
    return offset + q @ np.array(g) + np.einsum("...i,ij,...j->...", q,h,q)/2


def point_cases():
    eye = np.eye(3)
    mixed = [[-.5,.0625,-.125],[.0625,.25,.03125],[-.125,.03125,.75]]
    known = [[2.,1.,1.],[1.,2.,1.],[1.,1.,2.]]
    skew = np.array([[1., .25, -.125],[.0625,.75,.125],[0.,-.0625,1.25]])
    overflow = np.ones((5,5,5)); overflow[2,2,2] = 1e-250; overflow[3,2,2] = 2.
    data = [
        ("constant exact zero", np.ones((5,5,5)), eye, 30, 0, None),
        ("mixed polynomial", polynomial(mixed), eye, 30, 0, None),
        ("skew transformed mixed polynomial", polynomial(mixed), skew, 30, 0, None),
        ("known roots 1 1 4", polynomial(known, (0.,0.,0.)), eye, 30, 0, [1.,1.,4.]),
        ("known negative middle root", polynomial(np.diag([-.75,-.25,.5])), eye, 30, 0, [-.75,-.25,.5]),
        ("near-zero positive raw sign", polynomial(np.diag([-1e-7,1e-13,1e-7]), (0.,0.,0.), 1e-4), eye, 30, 0, None),
        ("forced nonconvergence", polynomial(known, (0.,0.,0.)), eye, 1, 4, None),
        ("finite density derivative overflow", np.full((5,5,5), value(INF-1)), eye, 30, 1, None),
        ("true RDG overflow", overflow, eye, 30, 6, None)]
    result=[]
    for label, block, inverse, rotations, status, roots in data:
        item = dict(label=label, floor=token(float.fromhex('0x1p-1060')), max_rot=rotations,
            inverse=[token(x) for x in inverse.ravel(order="F")],
            block=[token(x) for x in block.ravel(order="F")], center=token(block[2,2,2]),
            status=status, expected={})
        if status != 1:
            g,h=derivatives(block,inverse)
            hf=np.array([[float(x) for x in row] for row in h])
            item["expected"].update(grad=[token(float(x)) for x in g],
                hess=[token(hf[a,b]) for a,b in ((0,0),(1,1),(2,2),(0,1),(0,2),(1,2))])
            if status != 4:
                eigen = roots if roots is not None else eigvalsh(hf, driver="evr").tolist()
                decimal, rdg = rdg_reference(block[2,2,2], [float(x) for x in g])
                item["expected"].update(eigen=[token(x) for x in eigen], rdg=rdg,
                                          rdg_decimal=decimal)
        item["failure_classes"] = ({"all16":"nan"} if status == 1 else
            {"grad_hess":"finite", "tail7":"nan"} if status == 4 else
            {"grad_hess_eigen_bound_tau":"finite", "rdg":"+inf", "signed_rho":"nan"} if status == 6 else {})
        result.append(item)
    return result


def input_text(manifest):
    s,r,p = (manifest[k] for k in ("scalars","rdg","points"))
    lines=["M3A1", f"{len(s)} {len(r)} {len(p)}"]
    lines += [f"{c['x']} {c['shift']}" for c in s]
    lines += [" ".join(c["gradient"]+[c["rho"]]) for c in r]
    for c in p:
        lines += [f"{c['floor']} {c['max_rot']}", " ".join(c["inverse"]), " ".join(c["block"])]
    return "\n".join(lines)+"\n"


def generate(directory):
    directory = Path(directory)
    directory.mkdir()  # exclusive; originals and previous failures are never overwritten
    manifest = dict(schema=1, protocol="M3A1", scope="finite synthetic evaluator portability only",
        gates=GATES, scalars=scalar_cases(), rdg=rdg_cases(), points=point_cases())
    assert all(len(manifest[k]) <= 128 for k in ("scalars","rdg","points"))
    manifest["counts"] = dict(zip(("NS","NR","NP"),
                                 (len(manifest[k]) for k in ("scalars","rdg","points"))))
    manifest["limits"] = dict(max_records_per_kind=128, max_input_output_bytes=8388608,
                              max_host_sample_bytes=67108864, executable_timeout_seconds=30)
    data = input_text(manifest).encode("ascii")
    assert len(data) <= 8*1024*1024
    (directory/"input.m3a1").write_bytes(data)
    manifest["input"] = dict(name="input.m3a1", bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest["sources"] = {str(p.relative_to(ROOT)).replace("\\","/"):digest(p) for p in
        [Path(__file__), Path(__file__).with_name("oracle.py"), ROOT/"reference/extreme.py"]}
    (directory/"manifest.json").write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n", encoding="ascii")
    return manifest


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", required=True, type=Path)
    args=parser.parse_args()
    manifest=generate(args.generate)
    print("INPUTS_PREPARED_NOT_EXECUTED", {k:len(manifest[k]) for k in ("scalars","rdg","points")})
