"""Analytic fields and an independent vectorized FD4 reference.

Only tiny synthetic arrays belong here. Index order is (x,y,z), z contiguous.
The periodic oracle uses Fourier symbols, not the production FD implementation.
"""
from itertools import combinations, product

import numpy as np
from scipy.linalg import eigvalsh

BOUNDARY, NONPOSITIVE, LOW, STENCIL, FAILURE, NUM_UNCERTAIN, SCI_UNCERTAIN = (
    1, 2, 4, 8, 16, 32, 64
)
INVALID = BOUNDARY | NONPOSITIVE | LOW | STENCIL | FAILURE
OFFSETS = np.array([-2, -1, 1, 2])
D1 = np.array([1, -8, 8, -1], dtype=np.float64) / 12
D2_OFFSETS = np.arange(-2, 3)
D2 = np.array([-1, 16, -30, 16, -1], dtype=np.float64) / 12
RDG_DENOMINATOR = 2 * np.cbrt(3 * np.pi**2)


def indices(shape):
    return np.moveaxis(np.indices(shape, dtype=np.float64), 0, -1)


def cartesian(shape, jacobian, origin=None):
    origin = np.zeros(3) if origin is None else np.asarray(origin)
    return indices(shape) @ np.asarray(jacobian).T + origin


def quadratic(shape, jacobian, hessian, linear=None, origin=None, offset=20.0):
    """rho = offset + b.r + r.H.r/2 with exact Cartesian derivatives."""
    r = cartesian(shape, jacobian, origin)
    h = np.asarray(hessian, dtype=np.float64)
    b = np.zeros(3) if linear is None else np.asarray(linear)
    rho = offset + r @ b + np.einsum("...i,ij,...j->...", r, h, r) / 2
    grad = r @ h.T + b
    return rho, grad, np.broadcast_to(h, (*shape, 3, 3)).copy()


def gaussian(shape, jacobian, exponent, origin=None, amplitude=1.0):
    r = cartesian(shape, jacobian, origin)
    b = np.asarray(exponent, dtype=np.float64)
    br = r @ b.T
    rho = amplitude * np.exp(-np.einsum("...i,...i->...", r, br))
    grad = -2 * rho[..., None] * br
    hess = rho[..., None, None] * (
        4 * br[..., :, None] * br[..., None, :] - 2 * b
    )
    return rho, grad, hess


def periodic_fourier(shape, jacobian, modes, background=1.0):
    """Exact DISCRETE FD4 derivatives of Fourier modes (not continuous ones).

    modes contains (amplitude, integer frequency triple, phase).
    D1 symbol is i*(8*sin(theta)-sin(2*theta))/6;
    D2 symbol is (-cos(2*theta)+16*cos(theta)-15)/6.
    """
    q = indices(shape)
    rho = np.full(shape, background, dtype=np.float64)
    gq = np.zeros((*shape, 3))
    hq = np.zeros((*shape, 3, 3))
    for amplitude, frequency, phase in modes:
        theta = 2 * np.pi * np.asarray(frequency) / np.asarray(shape)
        angle = q @ theta + phase
        sine, cosine = np.sin(angle), np.cos(angle)
        d1 = (8 * np.sin(theta) - np.sin(2 * theta)) / 6
        d2 = (-np.cos(2 * theta) + 16 * np.cos(theta) - 15) / 6
        rho += amplitude * cosine
        gq -= amplitude * sine[..., None] * d1
        hq -= amplitude * cosine[..., None, None] * np.outer(d1, d1)
        for axis in range(3):
            # Pure second derivative is NOT D1 composed with D1.
            hq[..., axis, axis] += amplitude * cosine * (d2[axis] + d1[axis]**2)
    inverse = np.linalg.inv(jacobian)
    return rho, gq @ inverse, np.einsum("ai,...ab,bj->...ij", inverse, hq, inverse)


def stencil_offsets():
    offsets = {(0, 0, 0)}
    for axis in range(3):
        for step in OFFSETS:
            offset = [0, 0, 0]
            offset[axis] = int(step)
            offsets.add(tuple(offset))
    for a, b in combinations(range(3), 2):
        for p, t in product(OFFSETS, repeat=2):
            offset = [0, 0, 0]
            offset[a], offset[b] = int(p), int(t)
            offsets.add(tuple(offset))
    return tuple(sorted(offsets))


def input_flags(rho, periodic=(False, False, False), rho_min=1e-8):
    """Bits 0..3 only. Small allowed negatives invalidate the exact stencil.

    A zero is an allowed derivative sample; only its own RDG is unavailable.
    """
    rho = np.asarray(rho)
    flags = np.zeros(rho.shape, dtype=np.uint8)
    q = indices(rho.shape)
    boundary = np.zeros(rho.shape, dtype=bool)
    for axis in range(3):
        if not periodic[axis]:
            boundary |= (q[..., axis] < 2) | (q[..., axis] >= rho.shape[axis] - 2)
    flags[boundary] |= BOUNDARY
    flags[rho <= 0] |= NONPOSITIVE
    flags[(rho > 0) & (rho <= rho_min)] |= LOW
    negative = rho < 0
    # No wrap at finite boundaries. Only actually present samples contribute.
    for offset in stencil_offsets():
        shifted = np.roll(negative, tuple(-x for x in offset), axis=(0, 1, 2))
        exists = np.ones(rho.shape, dtype=bool)
        for axis, step in enumerate(offset):
            if not periodic[axis]:
                exists &= (q[..., axis] + step >= 0) & (
                    q[..., axis] + step < rho.shape[axis]
                )
        flags[shifted & exists] |= STENCIL
    return flags


def fd4(rho, jacobian):
    """Independent rolled-array discrete reference; boundary values unused."""
    rho = np.asarray(rho, dtype=np.float64)
    gq = np.zeros((*rho.shape, 3))
    hq = np.zeros((*rho.shape, 3, 3))
    for axis in range(3):
        for step, weight in zip(OFFSETS, D1):
            gq[..., axis] += weight * np.roll(rho, -int(step), axis=axis)
        for step, weight in zip(D2_OFFSETS, D2):
            hq[..., axis, axis] += weight * np.roll(rho, -int(step), axis=axis)
    for a, b in combinations(range(3), 2):
        for p, wp in zip(OFFSETS, D1):
            for t, wt in zip(OFFSETS, D1):
                hq[..., a, b] += wp * wt * np.roll(
                    rho, (-int(p), -int(t)), axis=(a, b)
                )
        hq[..., b, a] = hq[..., a, b]
    inverse = np.linalg.inv(jacobian)
    return gq @ inverse, np.einsum("ai,...ab,bj->...ij", inverse, hq, inverse)


def pack_hessian(hess):
    return np.stack([hess[..., a, b] for a, b in
                     ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))], axis=-1)


def nci(rho, grad, hess):
    """Independent LAPACK eigensolver. Caller selects positive valid points."""
    if not np.allclose(hess, np.swapaxes(hess, -1, -2), atol=1e-14, rtol=0):
        raise ValueError("reference Hessian must be symmetric")
    flat = hess.reshape(-1, 3, 3)
    spectrum = np.stack([eigvalsh(h, driver="evr", check_finite=True) for h in flat])
    lambda2 = spectrum[:, 1].reshape(rho.shape)
    rdg = np.linalg.norm(grad, axis=-1) / (RDG_DENOMINATOR * rho**(4/3))
    return rdg, np.sign(lambda2) * rho, lambda2
