"""Pure exact-reference/fixture checks; never executes the probe."""
from fractions import Fraction
import json
import math
from pathlib import Path

import pytest

from fixtures import GATES, digest, generate, input_text
from oracle import (ROOT, SIGN, INF, MAX, ETA, bits, classification,
    correctly_rounded_cbrt, rational, round_rational, scalar_expected, value)

FROZEN=Path(__file__).with_name("frozen")


@pytest.mark.parametrize("raw,shift,expected", [
    (bits(.75),1024,bits(float.fromhex('0x1.8p1023'))),
    (bits(.75),-1073,2), (bits(.75),-1074,1), (bits(.75),-1075,0),
    (bits(.5),-1074,0), (bits(-.5),-1074,SIGN),
    (MAX,1,INF), (1,1073,bits(.5)), (SIGN,4096,SIGN)])
def test_scaling_known_endpoints(raw,shift,expected):
    assert int(scalar_expected(raw,shift)["scaled"],16) == expected


def test_exact_nearest_even_midpoints_and_overflow():
    assert round_rational(ETA/2)==0
    assert round_rational(3*ETA/2)==2
    assert round_rational(5*ETA/2)==2
    boundary=Fraction(1<<1024)-Fraction(1<<970)
    assert round_rational(boundary)==INF
    assert round_rational(boundary-1)==MAX


@pytest.mark.parametrize("raw", [1,16,0xfffffffffffff,0x10000000000000,
    bits(1.),bits(2.),bits(8.),bits(27.),MAX])
def test_cbrt_reference_obeys_exact_rounding_cell(raw):
    nearest=correctly_rounded_cbrt(raw)
    lower=(rational(nearest-1)+rational(nearest))/2
    upper=(rational(nearest)+rational(nearest+1))/2
    assert lower**3 <= rational(raw) <= upper**3
    assert correctly_rounded_cbrt(raw|SIGN)==nearest|SIGN


def test_finite_helpers_reconstruct_original_rational():
    manifest=json.loads((FROZEN/"manifest.json").read_text())
    for c in manifest["scalars"]:
        raw=int(c["x"],16); e=c["expected"]
        if not e["finite"]:
            assert e["exponent"]==0 and e["fraction"]=="7FF8000000000000"
            continue
        assert rational(int(e["fraction"],16))*Fraction(2)**e["exponent"] == rational(raw)
        if value(raw):
            assert Fraction(1,2) <= abs(rational(int(e["fraction"],16))) < 1


def test_frozen_input_manifest_sources_and_limits():
    manifest=json.loads((FROZEN/"manifest.json").read_text())
    assert manifest["gates"] == GATES
    assert manifest["counts"]==dict(NS=36,NR=9,NP=9)
    assert input_text(manifest).encode()==(FROZEN/"input.m3a1").read_bytes()
    assert digest(FROZEN/"input.m3a1")==manifest["input"]["sha256"]
    for path,sha in manifest["sources"].items():
        assert digest(ROOT/path)==sha
    assert manifest["input"]["bytes"] < 8388608
    subnormal=[c for c in manifest["rdg"] if c["gate"]=="subnormal1ulp"]
    assert len(subnormal)==2
    assert all(c["expected_class"]=="subnormal" and int(c["expected"],16)>0 for c in subnormal)
    assert {c["status"] for c in manifest["points"]}=={0,1,4,6}


def test_generation_is_exclusive_and_deterministic(tmp_path):
    target=tmp_path/"fresh"
    generate(target)
    for name in ("input.m3a1","manifest.json"):
        assert (target/name).read_bytes()==(FROZEN/name).read_bytes()
    with pytest.raises(FileExistsError):
        generate(target)
