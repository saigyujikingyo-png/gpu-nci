! SPDX-License-Identifier: MIT
!> Complete-grid CPU kernel: density preflight and the OpenMP point loop.
!> Points are CUBE Z-fastest: p = (ix*Ny + iy)*Nz + iz (zero based).
module nci_kernel
  use nci_kinds
  use nci_abi, only: FLAG_BOUNDARY, FLAG_NONPOSITIVE_RHO, FLAG_LOW_RHO, &
                     FLAG_STENCIL_INVALID, FLAG_POINT_NUMERIC_FAILURE, &
                     FLAG_LAMBDA_NUM_UNCERTAIN, FLAG_LAMBDA_SCI_UNCERTAIN, FLAG_NOT_VALID_MASK
  use nci_numerics
  implicit none
  private

  integer, parameter, public :: KERNEL_OK = 0
  integer, parameter, public :: KERNEL_ALLOCATION_FAILURE = 1

  public :: preflight_density, evaluate_grid, diagnose_point

contains

  !> first_bad: 1-based index of the first non-finite sample or sample below
  !> -neg_tol (0 if none).  n_negative counts the accepted negative samples.
  subroutine preflight_density(n, rho, neg_tol, nthreads, first_bad, n_negative)
    integer(i64), intent(in) :: n
    real(dp), intent(in) :: rho(n), neg_tol
    integer, intent(in) :: nthreads
    integer(i64), intent(out) :: first_bad, n_negative
    integer(i64) :: p, fb, nn
    real(dp) :: lim

    lim = -neg_tol
    fb = huge(fb)
    nn = 0
    !$omp parallel do num_threads(nthreads) schedule(static) default(none) &
    !$omp   shared(n, rho, lim) private(p) reduction(min:fb) reduction(+:nn)
    do p = 1, n
      if (.not. is_finite(rho(p))) then
        fb = min(fb, p)
      else if (rho(p) < lim) then
        fb = min(fb, p)
      else if (rho(p) < 0.0_dp) then
        nn = nn + 1
      end if
    end do
    !$omp end parallel do
    if (fb == huge(fb)) fb = 0
    first_bad = fb
    n_negative = nn
  end subroutine preflight_density

  !> tab(o, i) = linear offset of neighbour i+o along one axis (wrapped on a
  !> periodic axis, -1 outside a finite axis).
  pure subroutine index_table(n, periodic, stride, tab)
    integer(i64), intent(in) :: n, stride
    logical, intent(in) :: periodic
    integer(i64), intent(out) :: tab(-2:2, 0:n - 1)
    integer(i64) :: i, j
    integer :: o
    do i = 0, n - 1
      do o = -2, 2
        j = i + o
        if (periodic) then
          tab(o, i) = modulo(j, n)*stride
        else if (j < 0 .or. j >= n) then
          tab(o, i) = -1
        else
          tab(o, i) = j*stride
        end if
      end do
    end do
  end subroutine index_table

  pure function on_boundary(i, n, periodic) result(b)
    integer(i64), intent(in) :: i, n
    logical, intent(in) :: periodic
    logical :: b
    b = (.not. periodic) .and. (i < 2 .or. i > n - 3)
  end function on_boundary

  !> Flags of bits 0-3 for point (ix,iy,iz); fills blk when the result is 0.
  pure subroutine classify_point(ix, iy, iz, nx, ny, nz, periodic, tx, ty, tz, off, &
                                 rho, rho_min, has_negative, fl, blk)
    integer(i64), intent(in) :: ix, iy, iz, nx, ny, nz
    logical, intent(in) :: periodic(3), has_negative
    integer(i64), intent(in) :: tx(-2:2, 0:nx - 1), ty(-2:2, 0:ny - 1), tz(-2:2, 0:nz - 1)
    integer, intent(in) :: off(3, 61)
    real(dp), intent(in) :: rho(:), rho_min
    integer, intent(out) :: fl
    real(dp), intent(inout) :: blk(-2:2, -2:2, -2:2)
    integer(i64) :: ox, oy, oz
    real(dp) :: rc
    integer :: k

    fl = 0
    if (on_boundary(ix, nx, periodic(1)) .or. on_boundary(iy, ny, periodic(2)) &
        .or. on_boundary(iz, nz, periodic(3))) fl = ior(fl, FLAG_BOUNDARY)
    rc = rho(tx(0, ix) + ty(0, iy) + tz(0, iz) + 1)
    if (.not. (rc > 0.0_dp)) then
      fl = ior(fl, FLAG_NONPOSITIVE_RHO)
    else if (rc <= rho_min) then
      fl = ior(fl, FLAG_LOW_RHO)
    end if
    if (has_negative) then
      ! Every point whose (clipped) 61-point stencil contains an accepted
      ! negative sample, including the negative sample itself.
      do k = 1, 61
        ox = tx(off(1, k), ix)
        oy = ty(off(2, k), iy)
        oz = tz(off(3, k), iz)
        if (ox >= 0 .and. oy >= 0 .and. oz >= 0) then
          if (rho(ox + oy + oz + 1) < 0.0_dp) then
            fl = ior(fl, FLAG_STENCIL_INVALID)
            exit
          end if
        end if
      end do
    end if
    if (fl == 0) then
      do k = 1, 61
        blk(off(1, k), off(2, k), off(3, k)) = &
          rho(tx(off(1, k), ix) + ty(off(2, k), iy) + tz(off(3, k), iz) + 1)
      end do
    end if
  end subroutine classify_point

  !> Evaluate every point.  counts(0:6) = per-bit counts, counts(7) = |V|.
  !> No output is written when the neighbour tables cannot be allocated.
  subroutine evaluate_grid(nx, ny, nz, periodic, m, rho, rho_min, has_negative, diagnostic, &
                           nthreads, rdg, srho, lam2, grad, hess, flags, counts, kstatus)
    integer(i64), intent(in) :: nx, ny, nz
    logical, intent(in) :: periodic(3), has_negative, diagnostic
    real(dp), intent(in) :: m(3, 3), rho(:), rho_min
    integer, intent(in) :: nthreads
    real(dp), intent(inout) :: rdg(:), srho(:), lam2(:), grad(:, :), hess(:, :)
    integer(i8), intent(inout) :: flags(:)
    integer(i64), intent(out) :: counts(0:7)
    integer, intent(out) :: kstatus

    integer(i64), allocatable :: tx(:, :), ty(:, :), tz(:, :)
    integer(i64) :: ix, iy, iz, p, cnt(0:7)
    integer :: off(3, 61), fl, k, ierr
    real(dp) :: blk(-2:2, -2:2, -2:2), absm(3, 3), floor_abs, nan
    type(point_result) :: res

    counts = 0
    kstatus = KERNEL_ALLOCATION_FAILURE
    allocate (tx(-2:2, 0:nx - 1), ty(-2:2, 0:ny - 1), tz(-2:2, 0:nz - 1), stat=ierr)
    if (ierr /= 0) return
    kstatus = KERNEL_OK
    call index_table(nx, periodic(1), ny*nz, tx)
    call index_table(ny, periodic(2), nz, ty)
    call index_table(nz, periodic(3), 1_i64, tz)
    off = stencil61()
    absm = abs(m)
    floor_abs = underflow_floor(absm)
    nan = qnan()
    blk = 0.0_dp
    cnt = 0

    !$omp parallel do collapse(2) schedule(static) num_threads(nthreads) default(none) &
    !$omp   shared(nx, ny, nz, periodic, tx, ty, tz, off, rho, rho_min, has_negative, &
    !$omp          diagnostic, m, absm, floor_abs, nan, rdg, srho, lam2, grad, hess, flags) &
    !$omp   firstprivate(blk) private(ix, iy, iz, p, fl, k, res) reduction(+:cnt)
    do ix = 0, nx - 1
      do iy = 0, ny - 1
        do iz = 0, nz - 1
          p = tx(0, ix) + ty(0, iy) + tz(0, iz) + 1
          call classify_point(ix, iy, iz, nx, ny, nz, periodic, tx, ty, tz, off, &
                              rho, rho_min, has_negative, fl, blk)
          if (fl == 0) then
            call point_eval(blk, m, absm, floor_abs, JACOBI_MAX_ROTATIONS, res)
            if (res%status == PT_OK) then
              fl = FLAG_LAMBDA_SCI_UNCERTAIN
              if (res%uncertain) fl = ior(fl, FLAG_LAMBDA_NUM_UNCERTAIN)
              rdg(p) = res%rdg
              srho(p) = res%signed_rho
              lam2(p) = res%lambda(2)
              if (diagnostic) then
                grad(:, p) = res%grad
                hess(:, p) = res%hess
              end if
            else
              fl = FLAG_POINT_NUMERIC_FAILURE
              rdg(p) = nan
              srho(p) = nan
              lam2(p) = nan
              if (diagnostic) then
                grad(:, p) = nan
                hess(:, p) = nan
              end if
            end if
          else
            rdg(p) = nan
            srho(p) = nan
            lam2(p) = nan
            if (diagnostic) then
              grad(:, p) = nan
              hess(:, p) = nan
            end if
          end if
          flags(p) = int(fl, i8)
          do k = 0, 6
            if (btest(fl, k)) cnt(k) = cnt(k) + 1
          end do
          if (iand(fl, FLAG_NOT_VALID_MASK) == 0) cnt(7) = cnt(7) + 1
        end do
      end do
    end do
    !$omp end parallel do
    counts = cnt
  end subroutine evaluate_grid

  !> Recompute the point_eval status of linear point p (1-based) for messages.
  subroutine diagnose_point(nx, ny, nz, periodic, m, rho, rho_min, p, status, nrot)
    integer(i64), intent(in) :: nx, ny, nz, p
    logical, intent(in) :: periodic(3)
    real(dp), intent(in) :: m(3, 3), rho(:), rho_min
    integer, intent(out) :: status, nrot
    integer(i64), allocatable :: tx(:, :), ty(:, :), tz(:, :)
    integer(i64) :: ix, iy, iz, q
    integer :: off(3, 61), fl, ierr
    real(dp) :: blk(-2:2, -2:2, -2:2), absm(3, 3)
    type(point_result) :: res

    status = -1
    nrot = 0
    allocate (tx(-2:2, 0:nx - 1), ty(-2:2, 0:ny - 1), tz(-2:2, 0:nz - 1), stat=ierr)
    if (ierr /= 0) return
    call index_table(nx, periodic(1), ny*nz, tx)
    call index_table(ny, periodic(2), nz, ty)
    call index_table(nz, periodic(3), 1_i64, tz)
    off = stencil61()
    q = p - 1
    iz = mod(q, nz)
    iy = mod(q/nz, ny)
    ix = q/(ny*nz)
    blk = 0.0_dp
    call classify_point(ix, iy, iz, nx, ny, nz, periodic, tx, ty, tz, off, &
                        rho, rho_min, .false., fl, blk)
    if (fl /= 0) return
    absm = abs(m)
    call point_eval(blk, m, absm, underflow_floor(absm), JACOBI_MAX_ROTATIONS, res)
    status = res%status
    nrot = res%nrot
  end subroutine diagnose_point

end module nci_kernel
