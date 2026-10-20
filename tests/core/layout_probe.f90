! SPDX-License-Identifier: MIT
!> Test-only probe: reports the library's Fortran view (module nci_abi) of the
!> ABI v1 structs so that a C program can compare it with offsetof/sizeof,
!> and echoes struct contents to prove field-by-field interoperation.
module nci_layout_probe
  use, intrinsic :: iso_c_binding
  use nci_abi
  implicit none
  private
  public :: nci_test_fortran_layout, nci_test_fortran_echo

contains

  pure function addr(p) result(a)
    type(c_ptr), intent(in) :: p
    integer(c_int64_t) :: a
    a = int(transfer(p, 0_c_intptr_t), c_int64_t)
  end function addr

  !> out = [sizeof(options), offsets of its 8 fields,
  !>        sizeof(tile), offsets of its 16 fields,
  !>        sizeof(stats), offsets of its 5 fields]  (32 entries)
  subroutine nci_test_fortran_layout(out, nout) bind(C, name='nci_test_fortran_layout')
    integer(c_int64_t), intent(out) :: out(33)
    integer(c_int32_t), intent(out) :: nout
    type(nci_options_v1), target :: o
    type(nci_tile_v1), target :: t
    type(nci_tile_stats_v1), target :: s
    integer(c_int64_t) :: b
    integer :: k

    k = 0
    b = addr(c_loc(o))
    call put(int(c_sizeof(o), c_int64_t))
    call put(addr(c_loc(o%abi_version)) - b)
    call put(addr(c_loc(o%struct_bytes)) - b)
    call put(addr(c_loc(o%backend)) - b)
    call put(addr(c_loc(o%output_mode)) - b)
    call put(addr(c_loc(o%omp_threads)) - b)
    call put(addr(c_loc(o%reserved)) - b)
    call put(addr(c_loc(o%rho_min)) - b)
    call put(addr(c_loc(o%negative_tolerance)) - b)
    b = addr(c_loc(t))
    call put(int(c_sizeof(t), c_int64_t))
    call put(addr(c_loc(t%abi_version)) - b)
    call put(addr(c_loc(t%struct_bytes)) - b)
    call put(addr(c_loc(t%global_n)) - b)
    call put(addr(c_loc(t%tile_start)) - b)
    call put(addr(c_loc(t%tile_count)) - b)
    call put(addr(c_loc(t%input_origin)) - b)
    call put(addr(c_loc(t%input_shape)) - b)
    call put(addr(c_loc(t%input_strides)) - b)
    call put(addr(c_loc(t%j_inv)) - b)
    call put(addr(c_loc(t%periodic)) - b)
    call put(addr(c_loc(t%reserved)) - b)
    call put(addr(c_loc(t%rho_capacity)) - b)
    call put(addr(c_loc(t%field_capacity)) - b)
    call put(addr(c_loc(t%flags_capacity)) - b)
    call put(addr(c_loc(t%grad_capacity)) - b)
    call put(addr(c_loc(t%hess_capacity)) - b)
    b = addr(c_loc(s))
    call put(int(c_sizeof(s), c_int64_t))
    call put(addr(c_loc(s%total_points)) - b)
    call put(addr(c_loc(s%valid_points)) - b)
    call put(addr(c_loc(s%invalid_points)) - b)
    call put(addr(c_loc(s%numeric_failures)) - b)
    call put(addr(c_loc(s%bit_counts)) - b)
    nout = int(k, c_int32_t)
  contains
    subroutine put(v)
      integer(c_int64_t), intent(in) :: v
      k = k + 1
      if (k <= size(out)) out(k) = v
    end subroutine put
  end subroutine nci_test_fortran_layout

  !> Flattens every field of o and t in declaration order (reals as raw bits)
  !> and fills s with total=101, valid=102, invalid=103, failures=104,
  !> bit_counts(k)=200+k.  Returns the number of values written (46).
  subroutine nci_test_fortran_echo(o, t, s, vals, nvals) bind(C, name='nci_test_fortran_echo')
    type(nci_options_v1), intent(in) :: o
    type(nci_tile_v1), intent(in) :: t
    type(nci_tile_stats_v1), intent(out) :: s
    integer(c_int64_t), intent(out) :: vals(46)
    integer(c_int32_t), intent(out) :: nvals
    integer :: k, i

    k = 0
    call put(int(o%abi_version, c_int64_t))
    call put(int(o%struct_bytes, c_int64_t))
    call put(int(o%backend, c_int64_t))
    call put(int(o%output_mode, c_int64_t))
    call put(int(o%omp_threads, c_int64_t))
    call put(int(o%reserved, c_int64_t))
    call put(transfer(o%rho_min, 0_c_int64_t))
    call put(transfer(o%negative_tolerance, 0_c_int64_t))
    call put(int(t%abi_version, c_int64_t))
    call put(int(t%struct_bytes, c_int64_t))
    do i = 1, 3
      call put(t%global_n(i))
    end do
    do i = 1, 3
      call put(t%tile_start(i))
    end do
    do i = 1, 3
      call put(t%tile_count(i))
    end do
    do i = 1, 3
      call put(t%input_origin(i))
    end do
    do i = 1, 3
      call put(t%input_shape(i))
    end do
    do i = 1, 3
      call put(t%input_strides(i))
    end do
    do i = 1, 9
      call put(transfer(t%j_inv(i), 0_c_int64_t))
    end do
    do i = 1, 3
      call put(int(t%periodic(i), c_int64_t))
    end do
    call put(int(t%reserved, c_int64_t))
    call put(t%rho_capacity)
    call put(t%field_capacity)
    call put(t%flags_capacity)
    call put(t%grad_capacity)
    call put(t%hess_capacity)
    nvals = int(k, c_int32_t)
    s%total_points = 101
    s%valid_points = 102
    s%invalid_points = 103
    s%numeric_failures = 104
    do i = 1, 7
      s%bit_counts(i) = 200 + i - 1
    end do
  contains
    subroutine put(v)
      integer(c_int64_t), intent(in) :: v
      k = k + 1
      if (k <= size(vals)) vals(k) = v
    end subroutine put
  end subroutine nci_test_fortran_echo

end module nci_layout_probe
