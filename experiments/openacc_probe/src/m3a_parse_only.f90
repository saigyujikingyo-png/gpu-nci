! SPDX-License-Identifier: MIT
! Host-only parser regression entry. Never invokes a numerical evaluator.
program m3a_parse_only
  use nci_kinds, only: dp, i64
  use m3a_io, only: read_input
  implicit none
  real(dp), allocatable :: x(:), gradient(:, :), rho(:), floor_abs(:), m(:, :, :), blk(:, :, :, :)
  integer, allocatable :: scale_exponent(:), max_rot(:)
  integer :: i, a, b, ix, iy, iz
  call read_input(x, scale_exponent, gradient, rho, floor_abs, max_rot, m, blk)
  ! Echo the actual parsed data, not the original input bytes. One token per
  ! line is canonical modulo whitespace and exposes exact bits/Fortran order.
  write(*, '(a)') 'M3A1'
  write(*, '(3(i0,1x))') size(x), size(rho), size(floor_abs)
  do i = 1, size(x)
    call emit_bits(x(i))
    write(*, '(i0)') scale_exponent(i)
  end do
  do i = 1, size(rho)
    do a = 1, 3
      call emit_bits(gradient(a, i))
    end do
    call emit_bits(rho(i))
  end do
  do i = 1, size(floor_abs)
    call emit_bits(floor_abs(i))
    write(*, '(i0)') max_rot(i)
    do b = 1, 3
      do a = 1, 3
        call emit_bits(m(a, b, i))
      end do
    end do
    do iz = -2, 2
      do iy = -2, 2
        do ix = -2, 2
          call emit_bits(blk(ix, iy, iz, i))
        end do
      end do
    end do
  end do
contains
  subroutine emit_bits(v)
    real(dp), intent(in) :: v
    write(*, '(z16.16)') transfer(v, 0_i64)
  end subroutine emit_bits
end program m3a_parse_only
