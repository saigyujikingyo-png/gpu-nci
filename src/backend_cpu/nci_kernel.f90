! SPDX-License-Identifier: MIT
!> CPU kernel: density preflight and the OpenMP point loop over the output X
!> planes of a validated layout (the complete grid or a canonical X slab).
!> Output points are local dense Z-fastest: p = (i*Ny + iy)*Nz + iz (zero
!> based, i = output plane); flags use the global coordinates (x0+i, iy, iz).
module nci_kernel
  use nci_kinds
  use nci_abi, only: FLAG_BOUNDARY, FLAG_NONPOSITIVE_RHO, FLAG_LOW_RHO, &
                     FLAG_STENCIL_INVALID, FLAG_POINT_NUMERIC_FAILURE, &
                     FLAG_LAMBDA_NUM_UNCERTAIN, FLAG_LAMBDA_SCI_UNCERTAIN, FLAG_NOT_VALID_MASK
  use nci_numerics
  use nci_validate, only: tile_layout
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

  !> tab(o, i) = input offset of the neighbour at global coordinate first+i+o
  !> (i = 0..count-1) along one axis of n points, whose input position k holds
  !> global coordinate origin+k.  A periodic axis with wrap (complete input,
  !> origin 0) folds modulo n; an unwrapped periodic halo is indexed directly;
  !> a finite axis gives -1 outside 0..n-1.
  pure subroutine axis_table(n, first, count, origin, periodic, wrap, stride, tab)
    integer(i64), intent(in) :: n, first, count, origin, stride
    logical, intent(in) :: periodic, wrap
    integer(i64), intent(out) :: tab(-2:2, 0:count - 1)
    integer(i64) :: i, j
    integer :: o
    do i = 0, count - 1
      do o = -2, 2
        j = first + i + o
        if (periodic .and. wrap) then
          tab(o, i) = modulo(j, n)*stride
        else if (.not. periodic .and. (j < 0 .or. j >= n)) then
          tab(o, i) = -1
        else
          tab(o, i) = (j - origin)*stride
        end if
      end do
    end do
  end subroutine axis_table

  pure function on_boundary(i, n, periodic) result(b)
    integer(i64), intent(in) :: i, n
    logical, intent(in) :: periodic
    logical :: b
    b = (.not. periodic) .and. (i < 2 .or. i > n - 3)
  end function on_boundary

  !> Flags of bits 0-3 for the point at global (gx,iy,iz) whose neighbour input
  !> offsets along X/Y/Z are cx/cy/cz; fills blk when the result is 0.
  pure subroutine classify_point(gx, iy, iz, nx, ny, nz, periodic, cx, cy, cz, off, &
                                 rho, rho_min, has_negative, fl, blk)
    integer(i64), intent(in) :: gx, iy, iz, nx, ny, nz
    logical, intent(in) :: periodic(3), has_negative
    integer(i64), intent(in) :: cx(-2:2), cy(-2:2), cz(-2:2)
    integer, intent(in) :: off(3, 61)
    real(dp), intent(in) :: rho(:), rho_min
    integer, intent(out) :: fl
    real(dp), intent(inout) :: blk(-2:2, -2:2, -2:2)
    integer(i64) :: ox, oy, oz
    real(dp) :: rc
    integer :: k

    fl = 0
    if (on_boundary(gx, nx, periodic(1)) .or. on_boundary(iy, ny, periodic(2)) &
        .or. on_boundary(iz, nz, periodic(3))) fl = ior(fl, FLAG_BOUNDARY)
    rc = rho(cx(0) + cy(0) + cz(0) + 1)
    if (.not. (rc > 0.0_dp)) then
      fl = ior(fl, FLAG_NONPOSITIVE_RHO)
    else if (rc <= rho_min) then
      fl = ior(fl, FLAG_LOW_RHO)
    end if
    if (has_negative) then
      ! Every point whose (clipped) 61-point stencil contains an accepted
      ! negative sample, including the negative sample itself.
      do k = 1, 61
        ox = cx(off(1, k))
        oy = cy(off(2, k))
        oz = cz(off(3, k))
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
          rho(cx(off(1, k)) + cy(off(2, k)) + cz(off(3, k)) + 1)
      end do
    end if
  end subroutine classify_point

  !> Evaluate every output point of lay: rho holds the lay%nin supplied input
  !> samples, the outputs lay%nout points.  counts(0:6) = per-bit counts,
  !> counts(7) = |V|.  The neighbour tables take 40*(B+Ny+Nz) bytes; no output
  !> is written when they cannot be allocated.
  subroutine evaluate_grid(lay, periodic, m, rho, rho_min, has_negative, diagnostic, &
                           nthreads, rdg, srho, lam2, grad, hess, flags, counts, kstatus)
    type(tile_layout), intent(in) :: lay
    logical, intent(in) :: periodic(3), has_negative, diagnostic
    real(dp), intent(in) :: m(3, 3), rho(:), rho_min
    integer, intent(in) :: nthreads
    real(dp), intent(inout) :: rdg(:), srho(:), lam2(:), grad(:, :), hess(:, :)
    integer(i8), intent(inout) :: flags(:)
    integer(i64), intent(out) :: counts(0:7)
    integer, intent(out) :: kstatus

    integer(i64), allocatable :: tx(:, :), ty(:, :), tz(:, :)
    integer(i64) :: nx, ny, nz, x0, nb, ix, iy, iz, p, cnt(0:7)
    integer :: off(3, 61), fl, k, ierr
    real(dp) :: blk(-2:2, -2:2, -2:2), absm(3, 3), floor_abs, nan
    type(point_result) :: res

    nx = lay%gn(1)
    ny = lay%gn(2)
    nz = lay%gn(3)
    x0 = lay%x0
    nb = lay%nb
    counts = 0
    kstatus = KERNEL_ALLOCATION_FAILURE
    allocate (tx(-2:2, 0:nb - 1), ty(-2:2, 0:ny - 1), tz(-2:2, 0:nz - 1), stat=ierr)
    if (ierr /= 0) return
    kstatus = KERNEL_OK
    call axis_table(nx, x0, nb, lay%xlo, periodic(1), lay%wrap, ny*nz, tx)
    call axis_table(ny, 0_i64, ny, 0_i64, periodic(2), .true., nz, ty)
    call axis_table(nz, 0_i64, nz, 0_i64, periodic(3), .true., 1_i64, tz)
    off = stencil61()
    absm = abs(m)
    floor_abs = underflow_floor(absm)
    nan = qnan()
    blk = 0.0_dp
    cnt = 0

    !$omp parallel do collapse(2) schedule(static) num_threads(nthreads) default(none) &
    !$omp   shared(nx, ny, nz, x0, nb, periodic, tx, ty, tz, off, rho, rho_min, has_negative, &
    !$omp          diagnostic, m, absm, floor_abs, nan, rdg, srho, lam2, grad, hess, flags) &
    !$omp   firstprivate(blk) private(ix, iy, iz, p, fl, k, res) reduction(+:cnt)
    do ix = 0, nb - 1
      do iy = 0, ny - 1
        do iz = 0, nz - 1
          p = (ix*ny + iy)*nz + iz + 1
          call classify_point(x0 + ix, iy, iz, nx, ny, nz, periodic, tx(:, ix), ty(:, iy), &
                              tz(:, iz), off, rho, rho_min, has_negative, fl, blk)
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

  !> Recompute the point_eval status of local output point p (1-based) of lay
  !> for messages; gpoint is its zero-based global Z-fastest index.  Only that
  !> point's 5-entry neighbour columns are formed (no allocation).
  subroutine diagnose_point(lay, periodic, m, rho, rho_min, p, gpoint, status, nrot)
    type(tile_layout), intent(in) :: lay
    logical, intent(in) :: periodic(3)
    real(dp), intent(in) :: m(3, 3), rho(:), rho_min
    integer(i64), intent(in) :: p
    integer(i64), intent(out) :: gpoint
    integer, intent(out) :: status, nrot
    integer(i64) :: cx(-2:2, 0:0), cy(-2:2, 0:0), cz(-2:2, 0:0)
    integer(i64) :: nx, ny, nz, gx, iy, iz, q
    integer :: off(3, 61), fl
    real(dp) :: blk(-2:2, -2:2, -2:2), absm(3, 3)
    type(point_result) :: res

    nx = lay%gn(1)
    ny = lay%gn(2)
    nz = lay%gn(3)
    q = p - 1
    iz = mod(q, nz)
    iy = mod(q/nz, ny)
    gx = lay%x0 + q/(ny*nz)
    gpoint = (gx*ny + iy)*nz + iz
    status = -1
    nrot = 0
    call axis_table(nx, gx, 1_i64, lay%xlo, periodic(1), lay%wrap, ny*nz, cx)
    call axis_table(ny, iy, 1_i64, 0_i64, periodic(2), .true., nz, cy)
    call axis_table(nz, iz, 1_i64, 0_i64, periodic(3), .true., 1_i64, cz)
    off = stencil61()
    blk = 0.0_dp
    call classify_point(gx, iy, iz, nx, ny, nz, periodic, cx(:, 0), cy(:, 0), cz(:, 0), off, &
                        rho, rho_min, .false., fl, blk)
    if (fl /= 0) return
    absm = abs(m)
    call point_eval(blk, m, absm, underflow_floor(absm), JACOBI_MAX_ROTATIONS, res)
    status = res%status
    nrot = res%nrot
  end subroutine diagnose_point

end module nci_kernel
