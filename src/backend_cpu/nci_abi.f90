! SPDX-License-Identifier: MIT
!> Fortran mirror of include/nci_api.h (ABI v1).  The derived types are
!> BIND(C) and are only ever reached through C pointers, never descriptors.
module nci_abi
  use, intrinsic :: iso_c_binding, only: c_int, c_int32_t, c_int64_t, c_double, c_sizeof
  implicit none
  private

  integer(c_int32_t), parameter, public :: NCI_ABI_VERSION = 1

  integer(c_int), parameter, public :: NCI_OK = 0
  integer(c_int), parameter, public :: NCI_INVALID_ARGUMENT = 1
  integer(c_int), parameter, public :: NCI_UNSUPPORTED = 2
  integer(c_int), parameter, public :: NCI_INVALID_INPUT = 3
  integer(c_int), parameter, public :: NCI_NUMERIC_FAILURE = 4
  integer(c_int), parameter, public :: NCI_ALLOCATION_FAILURE = 5
  integer(c_int), parameter, public :: NCI_BACKEND_UNAVAILABLE = 6

  integer(c_int32_t), parameter, public :: NCI_CPU = 0
  integer(c_int32_t), parameter, public :: NCI_OPENACC = 1
  integer(c_int32_t), parameter, public :: NCI_CUDA = 2

  integer(c_int32_t), parameter, public :: NCI_FULL = 0
  integer(c_int32_t), parameter, public :: NCI_DIAGNOSTIC = 1

  integer, parameter, public :: FLAG_BOUNDARY = 1
  integer, parameter, public :: FLAG_NONPOSITIVE_RHO = 2
  integer, parameter, public :: FLAG_LOW_RHO = 4
  integer, parameter, public :: FLAG_STENCIL_INVALID = 8
  integer, parameter, public :: FLAG_POINT_NUMERIC_FAILURE = 16
  integer, parameter, public :: FLAG_LAMBDA_NUM_UNCERTAIN = 32
  integer, parameter, public :: FLAG_LAMBDA_SCI_UNCERTAIN = 64
  !> Points outside the numerically valid set V carry one of bits 0-4.
  integer, parameter, public :: FLAG_NOT_VALID_MASK = 31

  integer, parameter, public :: OPTIONS_V1_BYTES = 40
  integer, parameter, public :: TILE_V1_BYTES = 280
  integer, parameter, public :: STATS_V1_BYTES = 88
  integer, parameter, public :: MAX_OMP_THREADS = 16

  type, bind(C), public :: nci_options_v1
    integer(c_int32_t) :: abi_version, struct_bytes, backend, output_mode
    integer(c_int32_t) :: omp_threads, reserved
    real(c_double) :: rho_min, negative_tolerance
  end type nci_options_v1

  type, bind(C), public :: nci_tile_v1
    integer(c_int32_t) :: abi_version, struct_bytes
    integer(c_int64_t) :: global_n(3), tile_start(3), tile_count(3)
    integer(c_int64_t) :: input_origin(3), input_shape(3), input_strides(3)
    real(c_double) :: j_inv(9)
    integer(c_int32_t) :: periodic(3), reserved
    integer(c_int64_t) :: rho_capacity, field_capacity, flags_capacity
    integer(c_int64_t) :: grad_capacity, hess_capacity
  end type nci_tile_v1

  type, bind(C), public :: nci_tile_stats_v1
    integer(c_int64_t) :: total_points, valid_points, invalid_points, numeric_failures
    integer(c_int64_t) :: bit_counts(7)
  end type nci_tile_stats_v1

  public :: abi_layout_ok

contains

  !> Runtime confirmation that this build's interoperable layouts match the
  !> sizes frozen in docs/abi.md.
  pure function abi_layout_ok() result(ok)
    logical :: ok
    type(nci_options_v1) :: o
    type(nci_tile_v1) :: t
    type(nci_tile_stats_v1) :: s
    ok = c_sizeof(o) == OPTIONS_V1_BYTES .and. c_sizeof(t) == TILE_V1_BYTES &
         .and. c_sizeof(s) == STATS_V1_BYTES
  end function abi_layout_ok

end module nci_abi
