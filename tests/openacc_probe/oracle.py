"""Independent rational IEEE rounding and high precision defining RDG formula.

No production routine or native output is imported. Positive binary64 bit order
is used as a search space, with exact rational comparisons at rounding midpoints.
"""
from fractions import Fraction
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from reference.extreme import high_precision_rdg, exact_center_derivatives

SIGN = 1 << 63
INF = 0x7ff0000000000000
MAX = INF - 1
QNAN = 0x7ff8000000000000
ETA = Fraction(1, 1 << 1074)


def bits(value):
    return struct.unpack(">Q", struct.pack(">d", float(value)))[0]


def value(raw):
    return struct.unpack(">d", struct.pack(">Q", int(raw)))[0]


def token(value_):
    return f"{bits(value_):016X}"


def rational(raw):
    return Fraction.from_float(value(raw))


def classification(raw):
    x = value(raw)
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "-inf" if raw & SIGN else "+inf"
    if x == 0:
        return "-zero" if raw & SIGN else "+zero"
    return "subnormal" if abs(x) < value(1 << 52) else "normal"


def _bracket(target, power=1):
    lo, hi = 0, MAX
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if rational(mid)**power <= target:
            lo = mid
        else:
            hi = mid - 1
    return lo


def round_rational(x, negative_zero=False):
    x = Fraction(x)
    sign = SIGN if x < 0 or (x == 0 and negative_zero) else 0
    x = abs(x)
    # Midpoint to the hypothetical next finite significand 1*2**1024.
    # At the tie the latter significand is even and IEEE round-to-nearest overflows.
    if x >= Fraction(1 << 1024) - Fraction(1 << 970):
        return sign | INF
    lo = _bracket(x)
    if lo == MAX:
        return sign | lo
    midpoint = (rational(lo) + rational(lo+1))/2
    chosen = lo + (x > midpoint or (x == midpoint and lo % 2 == 1))
    return sign | chosen


def correctly_rounded_cbrt(raw):
    kind = classification(raw)
    if kind == "nan":
        return QNAN
    if kind in ("+zero", "-zero", "+inf", "-inf"):
        return raw
    x, sign = abs(rational(raw)), raw & SIGN
    lo = _bracket(x, power=3)
    midpoint = (rational(lo) + rational(lo+1))/2
    cube = midpoint**3
    chosen = lo + (x > cube or (x == cube and lo % 2 == 1))
    return sign | chosen


def scalar_expected(raw, shift):
    kind = classification(raw)
    if kind in ("nan", "+inf", "-inf"):
        return dict(finite=0, exponent=0, fraction=f"{QNAN:016X}",
                    scaled=f"{(QNAN if kind == 'nan' else raw):016X}",
                    cbrt=f"{correctly_rounded_cbrt(raw):016X}")
    x = rational(raw)
    if x == 0:
        exponent = 0
    else:
        a = abs(x)
        k = a.numerator.bit_length() - a.denominator.bit_length()
        power = Fraction(2)**k
        if a < power:
            k -= 1
        exponent = k + 1
    fraction = round_rational(x * Fraction(2)**(-exponent), bool(raw & SIGN))
    scaled = round_rational(x * Fraction(2)**shift, bool(raw & SIGN))
    return dict(finite=1, exponent=exponent, fraction=f"{fraction:016X}",
                scaled=f"{scaled:016X}", cbrt=f"{correctly_rounded_cbrt(raw):016X}")


def rdg_reference(rho, gradient):
    a = high_precision_rdg(float(rho), [Fraction(float(g)) for g in gradient], 160)
    b = high_precision_rdg(float(rho), [Fraction(float(g)) for g in gradient], 210)
    assert bits(float(a)) == bits(float(b)), "RDG reference precision did not stabilize"
    return str(b), token(float(b))


def derivatives(block, inverse):
    g, h = exact_center_derivatives(block)
    m = [[Fraction(float(v)) for v in row] for row in inverse]
    gr = [sum(g[i]*m[i][a] for i in range(3)) for a in range(3)]
    hr = [[sum(m[i][a]*h[i][j]*m[j][b] for i in range(3) for j in range(3))
           for b in range(3)] for a in range(3)]
    return gr, hr
