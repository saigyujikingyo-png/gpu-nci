! SPDX-License-Identifier: MIT
!> Descriptor validation for ABI v1: options, tile header/geometry, capacities,
!> int64 overflow, buffer overlap and the J inverse condition number.
!> Messages are assembled in a fixed buffer (no allocation, no I/O).
module nci_validate
  use, intrinsic :: iso_c_binding, only: c_int
  use nci_kinds
  use nci_abi
  use nci_numerics, only: fro_norm, hypot2
  implicit none
  private

  integer, parameter, public :: MSG_CAP = 255
  real(dp), parameter, public :: COND_MAX = 1000.0_dp

  integer, parameter, public :: COND_ACCEPTED = 0
  integer, parameter, public :: COND_NONFINITE = 1
  integer, parameter, public :: COND_SINGULAR = 2
  integer, parameter, public :: COND_TOO_LARGE = 3
  integer, parameter, public :: COND_UNVERIFIED = 4

  integer, parameter :: SVD_MAX_SWEEPS = 30
  real(dp), parameter :: SVD_ORTHO_TOL = 16*EPS_MACH
  real(dp), parameter :: PRECHECK_MARGIN = 1.0_dp + 2.0_dp**(-40)

  type, public :: message_t
    character(len=MSG_CAP) :: text = ''
    integer :: n = 0
  end type message_t

  public :: msg_add, msg_add_int, msg_set
  public :: mul_overflows, check_options, check_tile_header, check_tile_geometry
  public :: jinv_condition, check_jinv, ranges_overlap

contains

  pure subroutine msg_add(m, s)
    type(message_t), intent(inout) :: m
    character(len=*), intent(in) :: s
    integer :: k
    do k = 1, len(s)
      if (m%n >= MSG_CAP) return
      m%n = m%n + 1
      m%text(m%n:m%n) = s(k:k)
    end do
  end subroutine msg_add

  pure subroutine msg_set(m, s)
    type(message_t), intent(inout) :: m
    character(len=*), intent(in) :: s
    m%n = 0
    m%text = ''
    call msg_add(m, s)
  end subroutine msg_set

  pure subroutine msg_add_int(m, v)
    type(message_t), intent(inout) :: m
    integer(i64), intent(in) :: v
    character(len=20) :: digits
    integer(i64) :: x
    integer :: k, dgt
    k = 20
    x = v
    do
      dgt = int(abs(mod(x, 10_i64)))
      digits(k:k) = achar(iachar('0') + dgt)
      x = x/10_i64
      if (x == 0) exit
      k = k - 1
    end do
    if (v < 0) call msg_add(m, '-')
    call msg_add(m, digits(k:20))
  end subroutine msg_add_int

  !> True when a*b exceeds huge(int64) for nonnegative a, b.
  pure function mul_overflows(a, b) result(ovf)
    integer(i64), intent(in) :: a, b
    logical :: ovf
    ovf = .false.
    if (a == 0 .or. b == 0) return
    ovf = a > huge(a)/b
  end function mul_overflows

  pure subroutine check_options(o, status, msg)
    type(nci_options_v1), intent(in) :: o
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    status = NCI_INVALID_ARGUMENT
    if (o%abi_version /= NCI_ABI_VERSION) then
      call msg_set(msg, 'options.abi_version must be NCI_ABI_VERSION (1)')
    else if (o%struct_bytes /= OPTIONS_V1_BYTES) then
      call msg_set(msg, 'options.struct_bytes must be sizeof(nci_options_v1) = 40')
    else if (o%reserved /= 0) then
      call msg_set(msg, 'options.reserved must be zero')
    else if (o%backend == NCI_OPENACC .or. o%backend == NCI_CUDA) then
      status = NCI_BACKEND_UNAVAILABLE
      call msg_set(msg, 'only the CPU backend is available in this library')
    else if (o%backend /= NCI_CPU) then
      call msg_set(msg, 'options.backend is not a known backend')
    else if (o%output_mode /= NCI_FULL .and. o%output_mode /= NCI_DIAGNOSTIC) then
      call msg_set(msg, 'options.output_mode must be NCI_FULL or NCI_DIAGNOSTIC')
    else if (o%omp_threads < 1 .or. o%omp_threads > MAX_OMP_THREADS) then
      call msg_set(msg, 'options.omp_threads must be in 1..16')
    else if (.not. is_finite(o%rho_min) .or. .not. (o%rho_min > 0.0_dp)) then
      call msg_set(msg, 'options.rho_min must be finite and positive')
    else if (.not. is_finite(o%negative_tolerance) &
             .or. .not. (o%negative_tolerance >= 0.0_dp)) then
      call msg_set(msg, 'options.negative_tolerance must be finite and nonnegative')
    else
      status = NCI_OK
    end if
  end subroutine check_options

  pure subroutine check_tile_header(t, status, msg)
    type(nci_tile_v1), intent(in) :: t
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    status = NCI_INVALID_ARGUMENT
    if (t%abi_version /= NCI_ABI_VERSION) then
      call msg_set(msg, 'tile.abi_version must be NCI_ABI_VERSION (1)')
    else if (t%struct_bytes /= TILE_V1_BYTES) then
      call msg_set(msg, 'tile.struct_bytes must be sizeof(nci_tile_v1) = 280')
    else if (t%reserved /= 0) then
      call msg_set(msg, 'tile.reserved must be zero')
    else
      status = NCI_OK
    end if
  end subroutine check_tile_header

  !> Dimensions, periodic flags, int64 overflow, layout and capacities.
  !> On success n = Nx*Ny*Nz and every byte extent up to 48*n fits in int64.
  pure subroutine check_tile_geometry(t, diagnostic, n, status, msg)
    type(nci_tile_v1), intent(in) :: t
    logical, intent(in) :: diagnostic
    integer(i64), intent(out) :: n
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    integer(i64) :: gn(3), nyz
    integer :: d
    status = NCI_INVALID_ARGUMENT
    n = 0
    gn = t%global_n
    do d = 1, 3
      if (gn(d) < 5) then
        call msg_set(msg, 'tile.global_n[')
        call msg_add_int(msg, int(d - 1, i64))
        call msg_add(msg, '] must be >= 5')
        return
      end if
    end do
    do d = 1, 3
      if (t%periodic(d) /= 0 .and. t%periodic(d) /= 1) then
        call msg_set(msg, 'tile.periodic[')
        call msg_add_int(msg, int(d - 1, i64))
        call msg_add(msg, '] must be 0 or 1')
        return
      end if
    end do
    if (mul_overflows(gn(2), gn(3))) then
      call msg_set(msg, 'grid point count overflows int64')
      return
    end if
    nyz = gn(2)*gn(3)
    if (mul_overflows(gn(1), nyz)) then
      call msg_set(msg, 'grid point count overflows int64')
      return
    end if
    n = gn(1)*nyz
    if (mul_overflows(n, 48_i64)) then
      call msg_set(msg, 'grid too large: Hessian byte extent overflows int64')
      return
    end if
    do d = 1, 3
      ! Fortran .or. need not short-circuit: reject negative extents before
      ! evaluating gn-count, in particular when count is INT64_MIN.
      if (t%tile_count(d) < 1 .or. t%tile_start(d) < 0) then
        call msg_set(msg, 'tile_start/tile_count lie outside the global grid')
        return
      end if
      if (t%tile_start(d) > gn(d) - t%tile_count(d)) then
        call msg_set(msg, 'tile_start/tile_count lie outside the global grid')
        return
      end if
      if (t%input_shape(d) < 1) then
        call msg_set(msg, 'tile.input_shape entries must be positive')
        return
      end if
    end do
    if (any(t%tile_start /= 0) .or. any(t%tile_count /= gn) &
        .or. any(t%input_origin /= 0) .or. any(t%input_shape /= gn) &
        .or. t%input_strides(1) /= nyz .or. t%input_strides(2) /= gn(3) &
        .or. t%input_strides(3) /= 1) then
      status = NCI_UNSUPPORTED
      call msg_set(msg, 'only complete-grid dense Z-fastest layouts are supported '// &
                   '(start/origin 0, count/shape = global_n, strides = [Ny*Nz,Nz,1])')
      return
    end if
    if (t%rho_capacity < n) then
      call msg_set(msg, 'tile.rho_capacity is smaller than Nx*Ny*Nz')
    else if (t%field_capacity < n) then
      call msg_set(msg, 'tile.field_capacity is smaller than Nx*Ny*Nz')
    else if (t%flags_capacity < n) then
      call msg_set(msg, 'tile.flags_capacity is smaller than Nx*Ny*Nz')
    else if (diagnostic .and. t%grad_capacity < 3*n) then
      call msg_set(msg, 'tile.grad_capacity is smaller than 3*Nx*Ny*Nz')
    else if (diagnostic .and. t%hess_capacity < 6*n) then
      call msg_set(msg, 'tile.hess_capacity is smaller than 6*Nx*Ny*Nz')
    else
      status = NCI_OK
    end if
  end subroutine check_tile_geometry

  !> 2-norm condition number of the 3x3 matrix stored in jinv.
  !>
  !> One-sided (Hestenes) Jacobi orthogonalizes the columns of the exactly
  !> power-of-two scaled matrix; the singular values are the final column
  !> norms.  The condition number is never squared (no eigenvalues of M^T M).
  !> Before the sweeps, max/min column norm (a lower bound of kappa) rejects
  !> grossly ill-conditioned or graded matrices.
  pure subroutine jinv_condition(jinv, verdict, kappa)
    real(dp), intent(in) :: jinv(9)
    integer, intent(out) :: verdict
    real(dp), intent(out) :: kappa
    integer, parameter :: PAIRS(2, 3) = reshape([1, 2, 1, 3, 2, 3], [2, 3])
    real(dp) :: a(3, 3), cn(3), ap(3), aq(3), amax, gam, d, t, c, s, np, nq
    integer :: i, k, e, sweep, ip, p, q
    logical :: rotated

    kappa = huge(1.0_dp)
    do i = 1, 9
      if (.not. is_finite(jinv(i))) then
        verdict = COND_NONFINITE
        return
      end if
    end do
    do i = 1, 3
      do k = 1, 3
        a(i, k) = jinv(3*(i - 1) + k)
      end do
    end do
    amax = maxval(abs(a))
    if (amax == 0.0_dp) then
      verdict = COND_SINGULAR
      return
    end if
    e = exponent(amax)
    a = scale(a, -e)
    do k = 1, 3
      cn(k) = fro_norm(3, a(:, k))
    end do
    if (minval(cn) == 0.0_dp) then
      verdict = COND_SINGULAR
      return
    end if
    if (maxval(cn) > (COND_MAX*minval(cn))*PRECHECK_MARGIN) then
      kappa = maxval(cn)/minval(cn)
      verdict = COND_TOO_LARGE
      return
    end if

    rotated = .true.
    do sweep = 1, SVD_MAX_SWEEPS
      rotated = .false.
      do ip = 1, 3
        p = PAIRS(1, ip)
        q = PAIRS(2, ip)
        np = fro_norm(3, a(:, p))
        nq = fro_norm(3, a(:, q))
        gam = ((a(1, p)*a(1, q)) + (a(2, p)*a(2, q))) + (a(3, p)*a(3, q))
        if (abs(gam) <= (SVD_ORTHO_TOL*np)*nq) cycle
        rotated = .true.
        d = 0.5_dp*((nq - np)*(nq + np))
        t = gam/(abs(d) + hypot2(d, gam))
        if (d < 0.0_dp) t = -t
        c = 1.0_dp/sqrt(1.0_dp + t*t)
        s = c*t
        ap = a(:, p)
        aq = a(:, q)
        a(:, p) = c*ap - s*aq
        a(:, q) = s*ap + c*aq
      end do
      if (.not. rotated) exit
    end do
    if (rotated) then
      verdict = COND_UNVERIFIED
      return
    end if
    do k = 1, 3
      cn(k) = fro_norm(3, a(:, k))
    end do
    if (.not. (minval(cn) > 0.0_dp)) then
      verdict = COND_SINGULAR
      return
    end if
    kappa = maxval(cn)/minval(cn)
    if (maxval(cn) <= COND_MAX*minval(cn)) then
      verdict = COND_ACCEPTED
    else
      verdict = COND_TOO_LARGE
    end if
  end subroutine jinv_condition

  pure subroutine check_jinv(jinv, status, msg)
    real(dp), intent(in) :: jinv(9)
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    integer :: verdict
    real(dp) :: kappa
    call jinv_condition(jinv, verdict, kappa)
    status = NCI_INVALID_ARGUMENT
    select case (verdict)
    case (COND_ACCEPTED)
      status = NCI_OK
    case (COND_NONFINITE)
      call msg_set(msg, 'tile.j_inv has a non-finite entry')
    case (COND_SINGULAR)
      call msg_set(msg, 'tile.j_inv is singular')
    case (COND_TOO_LARGE)
      call msg_set(msg, 'tile.j_inv 2-norm condition number exceeds 1000')
    case default
      call msg_set(msg, 'tile.j_inv condition number could not be verified')
    end select
  end subroutine check_jinv

  !> Half-open byte ranges [a0, a0+alen) and [b0, b0+blen); lengths >= 0.
  pure function ranges_overlap(a0, alen, b0, blen) result(ovl)
    integer(i64), intent(in) :: a0, alen, b0, blen
    logical :: ovl
    if (alen == 0 .or. blen == 0) then
      ovl = .false.
    else
      ovl = (a0 - b0 < blen) .and. (b0 - a0 < alen)
    end if
  end function ranges_overlap

end module nci_validate
