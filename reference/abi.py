"""ctypes mirror of the PUBLIC v1 contract, never production internals."""
import ctypes as ct
from contextlib import contextmanager

import numpy as np

OK, INVALID_ARGUMENT, UNSUPPORTED, INVALID_INPUT, NUMERIC_FAILURE = range(5)
FULL, DIAGNOSTIC = 0, 1
DOUBLE_P = ct.POINTER(ct.c_double)
U8_P = ct.POINTER(ct.c_uint8)
SENTINEL = -12345.75


class Options(ct.Structure):
    _fields_ = [(name, ct.c_int32) for name in
                ("abi_version", "struct_bytes", "backend", "output_mode",
                 "omp_threads", "reserved")] + [
                     ("rho_min", ct.c_double), ("negative_tolerance", ct.c_double)]


class Tile(ct.Structure):
    _fields_ = [("abi_version", ct.c_int32), ("struct_bytes", ct.c_int32)] + [
        (name, ct.c_int64 * 3) for name in
        ("global_n", "tile_start", "tile_count", "input_origin", "input_shape",
         "input_strides")
    ] + [("j_inv", ct.c_double * 9), ("periodic", ct.c_int32 * 3),
         ("reserved", ct.c_int32)] + [(name, ct.c_int64) for name in
         ("rho_capacity", "field_capacity", "flags_capacity", "grad_capacity",
          "hess_capacity")]


class Stats(ct.Structure):
    _fields_ = [(name, ct.c_int64) for name in
                ("total_points", "valid_points", "invalid_points", "numeric_failures")]
    _fields_ += [("bit_counts", ct.c_int64 * 7)]


def options(mode=DIAGNOSTIC, rho_min=1e-8, negative_tolerance=0, threads=1):
    return Options(1, ct.sizeof(Options), 0, mode, threads, 0,
                   rho_min, negative_tolerance)


def ptr(array, kind=DOUBLE_P):
    return None if array is None else array.ctypes.data_as(kind)


class Evaluation:
    def __init__(self, rho, jacobian=None, periodic=(False, False, False), mode=DIAGNOSTIC):
        self.rho = np.array(rho, dtype=np.float64, order="C", copy=True)
        shape = self.rho.shape
        if len(shape) != 3:
            raise ValueError("three dimensions required")
        n = self.rho.size
        self.tile = Tile()
        self.tile.abi_version, self.tile.struct_bytes = 1, ct.sizeof(Tile)
        for name in ("global_n", "tile_count", "input_shape"):
            setattr(self.tile, name, (ct.c_int64 * 3)(*shape))
        self.tile.input_strides[:] = (shape[1] * shape[2], shape[2], 1)
        inverse = np.linalg.inv(np.eye(3) if jacobian is None else jacobian)
        self.tile.j_inv[:] = inverse.ravel(order="C")
        self.tile.periodic[:] = periodic
        self.tile.rho_capacity = self.tile.field_capacity = self.tile.flags_capacity = n
        self.rdg = np.full(shape, SENTINEL)
        self.signedrho = np.full(shape, SENTINEL)
        self.lambda2 = np.full(shape, SENTINEL)
        self.grad = np.full((*shape, 3), SENTINEL) if mode == DIAGNOSTIC else None
        self.hess = np.full((*shape, 6), SENTINEL) if mode == DIAGNOSTIC else None
        self.flags = np.full(shape, 0xA5, dtype=np.uint8)
        if mode == DIAGNOSTIC:
            self.tile.grad_capacity, self.tile.hess_capacity = 3 * n, 6 * n
        self.stats = Stats()

    def arrays(self):
        return [a for a in (self.rdg, self.signedrho, self.lambda2,
                           self.grad, self.hess, self.flags) if a is not None]

    def snapshot(self):
        return [a.copy() for a in self.arrays()]

    def unchanged(self, snapshot):
        return all(np.array_equal(a, b) for a, b in zip(self.arrays(), snapshot))


class Library:
    def __init__(self, path):
        self.lib = ct.CDLL(str(path))
        self.create = self.lib.nci_context_create_v1
        self.create.argtypes = [ct.POINTER(Options), ct.POINTER(ct.c_void_p),
                               ct.POINTER(ct.c_char), ct.c_size_t]
        self.create.restype = ct.c_int
        self.evaluate = self.lib.nci_eval_tile_f64_v1
        self.evaluate.argtypes = [ct.c_void_p, ct.POINTER(Tile)] + [DOUBLE_P] * 6 + [
            U8_P, ct.POINTER(Stats), ct.POINTER(ct.c_char), ct.c_size_t]
        self.evaluate.restype = ct.c_int
        self.destroy = self.lib.nci_context_destroy_v1
        self.destroy.argtypes = [ct.c_void_p, ct.POINTER(ct.c_char), ct.c_size_t]
        self.destroy.restype = ct.c_int

    @contextmanager
    def context(self, opts=None):
        opts = options() if opts is None else opts
        handle, error = ct.c_void_p(), ct.create_string_buffer(512)
        status = self.create(ct.byref(opts), ct.byref(handle), error, len(error))
        if status != OK or not handle.value:
            raise AssertionError(f"create: status={status}, error={error.value!r}")
        try:
            yield handle
        finally:
            status = self.destroy(handle, error, len(error))
            if status != OK:
                raise AssertionError(f"destroy: status={status}, error={error.value!r}")

    def run(self, handle, case):
        error = ct.create_string_buffer(512)
        status = self.evaluate(
            handle, ct.byref(case.tile), ptr(case.rho), ptr(case.rdg),
            ptr(case.signedrho), ptr(case.lambda2), ptr(case.grad), ptr(case.hess),
            ptr(case.flags, U8_P), ct.byref(case.stats), error, len(error))
        return status, error.value.decode("utf-8", errors="replace")
