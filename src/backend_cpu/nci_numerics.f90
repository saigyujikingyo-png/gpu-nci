! SPDX-License-Identifier: MIT
!> Pointwise numerics of the CPU core:
!>   * integer-index fourth-order differences on the 61-point stencil,
!>   * Cartesian transform g_r = Jinv^T g_q, H_r = Jinv^T H_q Jinv,
!>   * scaled classical (largest-pivot) Jacobi eigenvalues of the symmetric
!>     3x3 H_r with an a-posteriori residual/orthogonality bound,
!>   * the implementation-roundoff bound behind LAMBDA_NUM_UNCERTAIN.
!> The derivation of every bound is in docs/cpu-core.md.  All procedures are
!> pure; there is no module state.
module nci_numerics
  use, intrinsic :: iso_c_binding, only: c_double
  use nci_kinds
  implicit none
  private

  !> Frozen production Jacobi controls (numerics.md section 4).
  integer, parameter, public :: JACOBI_MAX_ROTATIONS = 30
  real(dp), parameter, public :: JACOBI_OFFDIAG_TOL = 64*EPS_MACH

  !> Provisional tau_num margins of numerics.md section 6, in e*bohr**-5 and
  !> dimensionless; they only enlarge the uncertain set.
  real(dp), parameter, public :: TAU_ABS = 1.0e-12_dp
  real(dp), parameter, public :: TAU_REL = 1.0e-10_dp

  !> Relative inflation covering the rounding of the bound arithmetic itself.
  real(dp), parameter, public :: BOUND_SAFETY = 1.0_dp + 2.0_dp**(-40)
  !> Largest orthogonality defect accepted by the residual theorem.
  real(dp), parameter, public :: MAX_ORTHO_DEFECT = 0.25_dp
  !> (1 + s)*2**-532 squared dominates every underflow contribution.
  real(dp), parameter :: FLOOR_SCALE = 2.0_dp**(-532)

  integer, parameter, public :: EIG_OK = 0
  integer, parameter, public :: EIG_NONCONVERGED = 1
  integer, parameter, public :: EIG_RESIDUAL_FAILURE = 2

  integer, parameter, public :: PT_OK = 0
  integer, parameter, public :: PT_NONFINITE_DERIVATIVE = 1
  integer, parameter, public :: PT_NONFINITE_TRANSFORM = 2
  integer, parameter, public :: PT_ASYMMETRIC = 3
  integer, parameter, public :: PT_EIGEN_NONCONVERGED = 4
  integer, parameter, public :: PT_EIGEN_RESIDUAL = 5
  integer, parameter, public :: PT_NONFINITE_RESULT = 6

  type, public :: point_result
    integer :: status = PT_OK
    integer :: nrot = 0
    logical :: uncertain = .true.
    real(dp) :: grad(3) = 0.0_dp      !< Cartesian gradient x,y,z
    real(dp) :: hess(6) = 0.0_dp      !< symmetrized xx,yy,zz,xy,xz,yz
    real(dp) :: lambda(3) = 0.0_dp    !< ascending eigenvalues of hess
    real(dp) :: rdg = 0.0_dp
    real(dp) :: signed_rho = 0.0_dp
    real(dp) :: bound = 0.0_dp        !< rigorous |lambda_k - exact| bound
    real(dp) :: tau = 0.0_dp          !< TAU_ABS + TAU_REL*|H|_2 + bound
  end type point_result

  interface
    pure function c_cbrt(x) bind(C, name='cbrt') result(y)
      import :: c_double
      real(c_double), value :: x
      real(c_double) :: y
    end function c_cbrt
  end interface

  public :: stencil61, fro_norm, hypot2, jinv_matrix, underflow_floor
  public :: index_derivatives, cartesian_transform, bound_matrix
  public :: eig3_jacobi, point_eval

contains

  !> The 61 distinct offsets read by one point: the centre, 4 axial offsets on
  !> each axis and the 16 off-axis offsets of each coordinate plane.
  pure function stencil61() result(off)
    integer :: off(3, 61)
    integer, parameter :: S(4) = [-2, -1, 1, 2]
    integer, parameter :: PLANE(2, 3) = reshape([1, 2, 1, 3, 2, 3], [2, 3])
    integer :: n, ax, ip, it, ipl
    off = 0
    n = 1
    do ax = 1, 3
      do ip = 1, 4
        n = n + 1
        off(ax, n) = S(ip)
      end do
    end do
    do ipl = 1, 3
      do ip = 1, 4
        do it = 1, 4
          n = n + 1
          off(PLANE(1, ipl), n) = S(ip)
          off(PLANE(2, ipl), n) = S(it)
        end do
      end do
    end do
  end function stencil61

  !> Frobenius norm with exact power-of-two scaling (no overflow, no harmful
  !> underflow).  Any non-finite entry is returned as is.
  pure function fro_norm(n, x) result(r)
    integer, intent(in) :: n
    real(dp), intent(in) :: x(n)
    real(dp) :: r
    real(dp) :: m, y, s
    integer :: i, e
    m = 0.0_dp
    do i = 1, n
      if (.not. is_finite(x(i))) then
        r = abs(x(i))
        return
      end if
      m = max(m, abs(x(i)))
    end do
    if (m == 0.0_dp) then
      r = 0.0_dp
      return
    end if
    e = exponent(m)
    s = 0.0_dp
    do i = 1, n
      y = scale(x(i), -e)
      s = s + y*y
    end do
    r = scale(sqrt(s), e)
  end function fro_norm

  !> sqrt(x**2 + y**2) with exact power-of-two scaling: no overflow, no
  !> harmful underflow, and only correctly rounded IEEE operations (no libm
  !> hypot, whose rounding is implementation defined).
  pure function hypot2(x, y) result(h)
    real(dp), intent(in) :: x, y
    real(dp) :: h
    real(dp) :: m, xs, ys
    integer :: e
    m = max(abs(x), abs(y))
    if (m == 0.0_dp .or. .not. is_finite(m)) then
      h = m
      return
    end if
    e = exponent(m)
    xs = scale(x, -e)
    ys = scale(y, -e)
    h = scale(sqrt(xs*xs + ys*ys), e)
  end function hypot2

  !> M(i,a) = j_inv[3*i + a] (row-major C, zero based) = d q_i / d r_a.
  pure function jinv_matrix(jinv) result(m)
    real(dp), intent(in) :: jinv(9)
    real(dp) :: m(3, 3)
    integer :: i, a
    do i = 1, 3
      do a = 1, 3
        m(i, a) = jinv(3*(i - 1) + a)
      end do
    end do
  end function jinv_matrix

  !> Absolute floor for underflow contributions of the derivative, transform
  !> and rescaling steps under IEEE round-to-nearest with gradual underflow.
  !> FTZ/DAZ and externally changed rounding modes are outside this contract.
  pure function underflow_floor(absm) result(f)
    real(dp), intent(in) :: absm(3, 3)
    real(dp) :: f
    real(dp) :: smax, x
    smax = max(sum(absm(:, 1)), sum(absm(:, 2)), sum(absm(:, 3)))
    x = (1.0_dp + smax)*FLOOR_SCALE
    f = x*x
  end function underflow_floor

  !> S = rho(-2) - 8 rho(-1) + 8 rho(+1) - rho(+2); multiplications by 8 are exact.
  pure function fd1(m2, m1, p1, p2) result(s)
    real(dp), intent(in) :: m2, m1, p1, p2
    real(dp) :: s
    s = (m2 - p2) + (8.0_dp*(p1 - m1))
  end function fd1

  pure function afd1(m2, m1, p1, p2) result(s)
    real(dp), intent(in) :: m2, m1, p1, p2
    real(dp) :: s
    s = (abs(m2) + abs(p2)) + (8.0_dp*(abs(m1) + abs(p1)))
  end function afd1

  !> First and pure second index derivative along one axis, plus the absolute
  !> weighted sum sum_k |w_k rho_k| of the second derivative.
  pure subroutine axial(v, g, h, a)
    real(dp), intent(in) :: v(-2:2)
    real(dp), intent(out) :: g, h, a
    g = fd1(v(-2), v(-1), v(1), v(2))/12.0_dp
    h = (((16.0_dp*(v(-1) + v(1))) - (v(-2) + v(2))) - (30.0_dp*v(0)))/12.0_dp
    a = (((16.0_dp*(abs(v(-1)) + abs(v(1)))) + (abs(v(-2)) + abs(v(2)))) &
         + (30.0_dp*abs(v(0))))/12.0_dp
  end subroutine axial

  !> Mixed derivative on a plane pl(p,t): inner difference along the second
  !> (higher) axis t, outer along the first axis p, both with c=(1,-8,8,-1)/12.
  pure subroutine mixed(pl, h, a)
    real(dp), intent(in) :: pl(-2:2, -2:2)
    real(dp), intent(out) :: h, a
    real(dp) :: s(4), sa(4)
    integer, parameter :: S4(4) = [-2, -1, 1, 2]
    integer :: k, p
    do k = 1, 4
      p = S4(k)
      s(k) = fd1(pl(p, -2), pl(p, -1), pl(p, 1), pl(p, 2))
      sa(k) = afd1(pl(p, -2), pl(p, -1), pl(p, 1), pl(p, 2))
    end do
    h = fd1(s(1), s(2), s(3), s(4))/144.0_dp
    a = afd1(sa(1), sa(2), sa(3), sa(4))/144.0_dp
  end subroutine mixed

  !> Index-space gradient gq, symmetric Hessian hq and absolute stencil sums aq.
  !> Lines and planes are copied into local arrays (no runtime packing).
  pure subroutine index_derivatives(blk, gq, hq, aq)
    real(dp), intent(in) :: blk(-2:2, -2:2, -2:2)
    real(dp), intent(out) :: gq(3), hq(3, 3), aq(3, 3)
    real(dp) :: v(-2:2), pl(-2:2, -2:2)
    v = blk(:, 0, 0)
    call axial(v, gq(1), hq(1, 1), aq(1, 1))
    v = blk(0, :, 0)
    call axial(v, gq(2), hq(2, 2), aq(2, 2))
    v = blk(0, 0, :)
    call axial(v, gq(3), hq(3, 3), aq(3, 3))
    pl = blk(:, :, 0)
    call mixed(pl, hq(1, 2), aq(1, 2))
    pl = blk(:, 0, :)
    call mixed(pl, hq(1, 3), aq(1, 3))
    pl = blk(0, :, :)
    call mixed(pl, hq(2, 3), aq(2, 3))
    hq(2, 1) = hq(1, 2)
    hq(3, 1) = hq(1, 3)
    hq(3, 2) = hq(2, 3)
    aq(2, 1) = aq(1, 2)
    aq(3, 1) = aq(1, 3)
    aq(3, 2) = aq(2, 3)
  end subroutine index_derivatives

  !> gr = M^T gq and hr = M^T (hq M), all nine entries (no symmetrization).
  pure subroutine cartesian_transform(m, gq, hq, gr, hr)
    real(dp), intent(in) :: m(3, 3), gq(3), hq(3, 3)
    real(dp), intent(out) :: gr(3), hr(3, 3)
    real(dp) :: w(3, 3)
    integer :: i, a, b
    do b = 1, 3
      do i = 1, 3
        w(i, b) = ((hq(i, 1)*m(1, b)) + (hq(i, 2)*m(2, b))) + (hq(i, 3)*m(3, b))
      end do
    end do
    do b = 1, 3
      do a = 1, 3
        hr(a, b) = ((m(1, a)*w(1, b)) + (m(2, a)*w(2, b))) + (m(3, a)*w(3, b))
      end do
    end do
    do a = 1, 3
      gr(a) = ((m(1, a)*gq(1)) + (m(2, a)*gq(2))) + (m(3, a)*gq(3))
    end do
  end subroutine cartesian_transform

  !> P = |M|^T aq |M|: physical-unit (e*bohr**-5) magnitude behind every
  !> stencil and transform rounding error.  h**-2 enters exactly once, via |M|.
  pure subroutine bound_matrix(absm, aq, pm)
    real(dp), intent(in) :: absm(3, 3), aq(3, 3)
    real(dp), intent(out) :: pm(3, 3)
    real(dp) :: w(3, 3)
    integer :: i, a, b
    do b = 1, 3
      do i = 1, 3
        w(i, b) = ((aq(i, 1)*absm(1, b)) + (aq(i, 2)*absm(2, b))) + (aq(i, 3)*absm(3, b))
      end do
    end do
    do b = 1, 3
      do a = 1, 3
        pm(a, b) = ((absm(1, a)*w(1, b)) + (absm(2, a)*w(2, b))) + (absm(3, a)*w(3, b))
      end do
    end do
  end subroutine bound_matrix

  !> One Jacobi rotation annihilating a(p,q) /= 0.  t = tan(theta) is formed
  !> as sign(d)*apq/(|d| + hypot(d, apq)), d = (aqq - app)/2, which never
  !> squares a ratio and therefore cannot overflow; |t| <= 1.
  pure subroutine jacobi_rotate(a, v, p, q)
    real(dp), intent(inout) :: a(3, 3), v(3, 3)
    integer, intent(in) :: p, q
    real(dp) :: apq, d, t, c, s, tau, xp, xq
    integer :: r
    apq = a(p, q)
    d = 0.5_dp*(a(q, q) - a(p, p))
    t = apq/(abs(d) + hypot2(d, apq))
    if (d < 0.0_dp) t = -t
    c = 1.0_dp/sqrt(1.0_dp + t*t)
    s = t*c
    tau = s/(1.0_dp + c)
    a(p, p) = a(p, p) - t*apq
    a(q, q) = a(q, q) + t*apq
    a(p, q) = 0.0_dp
    a(q, p) = 0.0_dp
    r = 6 - p - q
    xp = a(r, p)
    xq = a(r, q)
    a(r, p) = xp - s*(xq + tau*xp)
    a(r, q) = xq + s*(xp - tau*xq)
    a(p, r) = a(r, p)
    a(q, r) = a(r, q)
    do r = 1, 3
      xp = v(r, p)
      xq = v(r, q)
      v(r, p) = xp - s*(xq + tau*xp)
      v(r, q) = xq + s*(xp - tau*xq)
    end do
  end subroutine jacobi_rotate

  pure subroutine sort3(d)
    real(dp), intent(inout) :: d(3)
    real(dp) :: t
    if (d(1) > d(2)) then
      t = d(1); d(1) = d(2); d(2) = t
    end if
    if (d(2) > d(3)) then
      t = d(2); d(2) = d(3); d(3) = t
    end if
    if (d(1) > d(2)) then
      t = d(1); d(1) = d(2); d(2) = t
    end if
  end subroutine sort3

  !> Ascending eigenvalues of the finite symmetric matrix h6 = (xx,yy,zz,xy,xz,yz).
  !>
  !> The matrix is scaled by the exact power of two 2**-e with
  !> max|a| in [0.5,1).  Classical Jacobi (largest off-diagonal pivot) stops
  !> once the off-diagonal Frobenius norm is <= 64*eps*max|a|; at most max_rot
  !> rotations are performed (production: JACOBI_MAX_ROTATIONS). `bound` is the
  !> scaled residual/orthogonality contribution from R = A V - V D and V^T V-I.
  !> It is not a standalone uniform error certificate: rescaling can round
  !> eigenvalues into subnormals while this contribution rounds to zero.
  !> point_eval adds bound-arithmetic inflation and the underflow floor;
  !> the complete estimate assumes round-to-nearest with gradual underflow.
  pure subroutine eig3_jacobi(h6, max_rot, lam, bound, nrot, info)
    real(dp), intent(in) :: h6(6)
    integer, intent(in) :: max_rot
    real(dp), intent(out) :: lam(3), bound
    integer, intent(out) :: nrot, info
    real(dp) :: a(3, 3), a0(3, 3), v(3, 3), d(3), r(3, 3), rb(3, 3), g(3, 3), gb(3, 3)
    real(dp) :: amax, thresh, off, big, t1, t2, t3, t4, rnorm, delta, dmax, bs
    integer :: e, i, k, l, p, q

    nrot = 0
    info = EIG_OK
    amax = 0.0_dp
    do i = 1, 6
      amax = max(amax, abs(h6(i)))
    end do
    if (amax == 0.0_dp) then
      lam = 0.0_dp
      bound = 0.0_dp
      return
    end if
    e = exponent(amax)
    a0(1, 1) = scale(h6(1), -e)
    a0(2, 2) = scale(h6(2), -e)
    a0(3, 3) = scale(h6(3), -e)
    a0(1, 2) = scale(h6(4), -e)
    a0(1, 3) = scale(h6(5), -e)
    a0(2, 3) = scale(h6(6), -e)
    a0(2, 1) = a0(1, 2)
    a0(3, 1) = a0(1, 3)
    a0(3, 2) = a0(2, 3)
    a = a0
    thresh = JACOBI_OFFDIAG_TOL*scale(amax, -e)
    v = 0.0_dp
    v(1, 1) = 1.0_dp
    v(2, 2) = 1.0_dp
    v(3, 3) = 1.0_dp

    do
      off = sqrt(2.0_dp*(((a(1, 2)*a(1, 2)) + (a(1, 3)*a(1, 3))) + (a(2, 3)*a(2, 3))))
      if (off <= thresh) exit
      if (nrot >= max_rot) then
        info = EIG_NONCONVERGED
        lam = qnan()
        bound = qnan()
        return
      end if
      p = 1
      q = 2
      big = abs(a(1, 2))
      if (abs(a(1, 3)) > big) then
        p = 1
        q = 3
        big = abs(a(1, 3))
      end if
      if (abs(a(2, 3)) > big) then
        p = 2
        q = 3
      end if
      call jacobi_rotate(a, v, p, q)
      nrot = nrot + 1
    end do
    d = [a(1, 1), a(2, 2), a(3, 3)]

    ! Residual R = A0 V - V D with componentwise rounding bound gamma_4*rb.
    do k = 1, 3
      do i = 1, 3
        t1 = a0(i, 1)*v(1, k)
        t2 = a0(i, 2)*v(2, k)
        t3 = a0(i, 3)*v(3, k)
        t4 = v(i, k)*d(k)
        r(i, k) = ((t1 + t2) + t3) - t4
        rb(i, k) = ((abs(t1) + abs(t2)) + abs(t3)) + abs(t4)
      end do
    end do
    ! Orthogonality defect G = V^T V - I with bound gamma_4*gb.
    do l = 1, 3
      do k = 1, 3
        t1 = v(1, k)*v(1, l)
        t2 = v(2, k)*v(2, l)
        t3 = v(3, k)*v(3, l)
        if (k == l) then
          g(k, l) = ((t1 + t2) + t3) - 1.0_dp
          gb(k, l) = ((abs(t1) + abs(t2)) + abs(t3)) + 1.0_dp
        else
          g(k, l) = (t1 + t2) + t3
          gb(k, l) = (abs(t1) + abs(t2)) + abs(t3)
        end if
      end do
    end do
    rnorm = fro_norm(9, r) + GAMMA4*fro_norm(9, rb)
    delta = fro_norm(9, g) + GAMMA4*fro_norm(9, gb)
    if (.not. (delta <= MAX_ORTHO_DEFECT) .or. .not. is_finite(rnorm)) then
      info = EIG_RESIDUAL_FAILURE
      lam = qnan()
      bound = qnan()
      return
    end if
    dmax = max(abs(d(1)), abs(d(2)), abs(d(3)))
    ! |lambda_k(A0) - d_(k)| <= (|R|_2 + 2 delta |D|_2)/sqrt(1 - delta)
    !                       <= (1 + delta)(|R|_F + 2 delta max|d|), delta <= 1/2.
    bs = (1.0_dp + delta)*(rnorm + 2.0_dp*delta*dmax)
    call sort3(d)
    lam = scale(d, e)
    bound = scale(bs, e)
  end subroutine eig3_jacobi

  !> Full evaluation of one point whose 61-point stencil is complete and free
  !> of negative samples and whose centre density is above rho_min.
  pure subroutine point_eval(blk, m, absm, floor_abs, max_rot, res)
    real(dp), intent(in) :: blk(-2:2, -2:2, -2:2)
    real(dp), intent(in) :: m(3, 3), absm(3, 3), floor_abs
    integer, intent(in) :: max_rot
    type(point_result), intent(out) :: res
    real(dp) :: gq(3), hq(3, 3), aq(3, 3), gr(3), hr(3, 3), pm(3, 3)
    real(dp) :: lam(3), beig, blam, tol, hnorm, rho0, gnorm
    integer :: a, b, nrot, info

    res%grad = qnan()
    res%hess = qnan()
    res%lambda = qnan()
    res%rdg = qnan()
    res%signed_rho = qnan()
    res%bound = qnan()
    res%tau = qnan()
    res%uncertain = .true.

    call index_derivatives(blk, gq, hq, aq)
    if (.not. (all_finite(3, gq) .and. all_finite(9, hq))) then
      res%status = PT_NONFINITE_DERIVATIVE
      return
    end if

    call cartesian_transform(m, gq, hq, gr, hr)
    call bound_matrix(absm, aq, pm)
    res%grad = gr
    res%hess = [hr(1, 1), hr(2, 2), hr(3, 3), (hr(1, 2) + hr(2, 1))*0.5_dp, &
                (hr(1, 3) + hr(3, 1))*0.5_dp, (hr(2, 3) + hr(3, 2))*0.5_dp]
    if (.not. (all_finite(3, gr) .and. all_finite(9, hr))) then
      res%status = PT_NONFINITE_TRANSFORM
      return
    end if
    ! Both triangles approximate the same exact entry within gamma_11*P(a,b).
    do b = 2, 3
      do a = 1, b - 1
        tol = (2.0_dp*GAMMA12*max(pm(a, b), pm(b, a)))*BOUND_SAFETY + floor_abs
        if (.not. (abs(hr(a, b) - hr(b, a)) <= tol)) then
          res%status = PT_ASYMMETRIC
          return
        end if
      end do
    end do

    call eig3_jacobi(res%hess, max_rot, lam, beig, nrot, info)
    res%nrot = nrot
    if (info == EIG_NONCONVERGED) then
      res%status = PT_EIGEN_NONCONVERGED
      return
    else if (info /= EIG_OK) then
      res%status = PT_EIGEN_RESIDUAL
      return
    end if
    if (.not. all_finite(3, lam)) then
      res%status = PT_NONFINITE_RESULT
      return
    end if

    ! |lambda_k(computed) - lambda_k(exact discrete H_r)|
    !   <= gamma_12*|P|_F (stencil + transform + symmetrization)
    !    + beig (Jacobi residual theorem) + underflow floor.
    blam = (GAMMA12*fro_norm(9, pm) + beig)*BOUND_SAFETY + floor_abs
    hnorm = max(abs(lam(1)), abs(lam(3)))
    res%lambda = lam
    res%bound = blam
    res%tau = (TAU_ABS + TAU_REL*hnorm) + blam
    res%uncertain = .not. (abs(lam(2)) > res%tau)

    rho0 = blk(0, 0, 0)
    gnorm = fro_norm(3, gr)
    ! s = |g| / (C rho**(4/3)) evaluated as (|g|/rho)/(C*cbrt(rho)) so that
    ! rho**(4/3) never overflows or underflows on its own.
    res%rdg = (gnorm/rho0)/(C_RDG*c_cbrt(rho0))
    if (.not. is_finite(res%rdg)) then
      res%status = PT_NONFINITE_RESULT
      return
    end if
    if (lam(2) > 0.0_dp) then
      res%signed_rho = rho0
    else if (lam(2) < 0.0_dp) then
      res%signed_rho = -rho0
    else
      res%signed_rho = 0.0_dp
    end if
    res%status = PT_OK
  end subroutine point_eval

end module nci_numerics
