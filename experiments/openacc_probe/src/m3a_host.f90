! SPDX-License-Identifier: MIT
!> M3A host reference (docs/openacc-probe-contract.md): evaluates every M3A1
!> record with the unchanged CPU source and its C library bindings, built
!> without OpenACC, and writes the output with DEVICE = 0.
program m3a_host
  use nci_kinds, only: dp
  use nci_numerics, only: point_result
  use m3a_records, only: scalar_record, rdg_record, point_record
  use m3a_io, only: read_input, write_output
  implicit none
  real(dp), allocatable :: x(:), gradient(:, :), rho(:), floor_abs(:), m(:, :, :), blk(:, :, :, :)
  integer, allocatable :: scale_exponent(:), max_rot(:), s_exponent(:)
  logical, allocatable :: s_device(:), s_finite(:), r_device(:), p_device(:)
  real(dp), allocatable :: s_fraction(:), s_scaled(:), s_cbrt(:), r_rdg(:)
  type(point_result), allocatable :: p_result(:)
  integer :: ns, nr, np, i

  call read_input(x, scale_exponent, gradient, rho, floor_abs, max_rot, m, blk)
  ns = size(x)
  nr = size(rho)
  np = size(floor_abs)
  allocate(s_device(ns), s_finite(ns), s_exponent(ns), s_fraction(ns), s_scaled(ns), s_cbrt(ns))
  allocate(r_device(nr), r_rdg(nr), p_device(np), p_result(np))
  s_device = .false.
  r_device = .false.
  p_device = .false.

  do i = 1, ns
    call scalar_record(x(i), scale_exponent(i), s_finite(i), s_exponent(i), s_fraction(i), &
                       s_scaled(i), s_cbrt(i))
  end do
  do i = 1, nr
    call rdg_record(gradient(:, i), rho(i), r_rdg(i))
  end do
  do i = 1, np
    call point_record(blk(:, :, :, i), m(:, :, i), floor_abs(i), max_rot(i), p_result(i))
  end do

  call write_output(s_device, s_finite, s_exponent, s_fraction, s_scaled, s_cbrt, &
                    r_device, r_rdg, p_device, p_result)
end program m3a_host
