"""Exact rational derivatives and arbitrary-precision RDG for a tiny fixture.

No binary exponent algorithm from any production implementation is used:
Fraction evaluates the stencil exactly, Decimal evaluates the defining formula.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import combinations, product

import numpy as np


def finite_large_rdg_fixture():
    rho = np.full((5, 5, 5), 1/64)
    amplitude = np.ldexp(3.0, 1017)
    rho[0, 2, 2] = rho[1, 2, 2] = 0
    rho[3, 2, 2], rho[4, 2, 2] = amplitude, 16*amplitude
    return rho


def exact_center_derivatives(rho):
    """Unit-J FD4 at (2,2,2), all coefficients and binary64 inputs rational."""
    center = (2, 2, 2)

    def sample(offset):
        index = tuple(a+b for a, b in zip(center, offset))
        return Fraction.from_float(float(rho[index]))

    first = dict(zip((-2, -1, 1, 2), (1, -8, 8, -1)))
    second = dict(zip(range(-2, 3), (-1, 16, -30, 16, -1)))
    grad = [Fraction(0) for _ in range(3)]
    hess = [[Fraction(0) for _ in range(3)] for _ in range(3)]
    for axis in range(3):
        for step, numerator in first.items():
            offset = [0, 0, 0]
            offset[axis] = step
            grad[axis] += numerator*sample(offset)/12
        for step, numerator in second.items():
            offset = [0, 0, 0]
            offset[axis] = step
            hess[axis][axis] += numerator*sample(offset)/12
    for a, b in combinations(range(3), 2):
        for (p, wp), (q, wq) in product(first.items(), repeat=2):
            offset = [0, 0, 0]
            offset[a], offset[b] = p, q
            hess[a][b] += wp*wq*sample(offset)/144
        hess[b][a] = hess[a][b]
    return grad, hess


def _decimal_pi():
    # Machin identity, independent of platform pi or production RDG constants.
    def atan_inverse(n):
        x = Decimal(1)/n
        power, total, index = x, x, 1
        while True:
            power *= -x*x
            term = power/(2*index+1)
            previous, total = total, total+term
            if total == previous:
                return total
            index += 1
    return 16*atan_inverse(5)-4*atan_inverse(239)


def high_precision_rdg(rho, gradient, precision=100):
    """Evaluate |g|/[2(3*pi²)^(1/3)rho^(4/3)] directly in Decimal."""
    def decimal(value):
        value = Fraction(value)
        return Decimal(value.numerator)/value.denominator

    with localcontext() as ctx:
        ctx.prec = precision
        norm = sum(decimal(g)**2 for g in gradient).sqrt()
        pi = _decimal_pi()
        constant = 2*(3*pi*pi)**(Decimal(1)/3)
        return norm/(constant*decimal(rho)**(Decimal(4)/3))
