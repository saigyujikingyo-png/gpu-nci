! SPDX-License-Identifier: MIT
!> White-box tests of constants, the 61-point stencil, norms, the Cartesian
!> transform and row-major J inverse mapping, the J inverse condition check,
!> and the lambda roundoff bound of point_eval against a binary128 reference.
program test_numerics
  use nci_kinds
  use nci_numerics
  use nci_validate, only: jinv_condition, COND_ACCEPTED, COND_NONFINITE, COND_SINGULAR, &
                          COND_TOO_LARGE
  use nci_test_hooks
  use nci_ref_quad
  implicit none

  integer :: nfail, ncheck, ncases
  integer(i64) :: seed
  real(dp) :: worst_ratio, worst_grad, worst_rdg, sum_ratio

  nfail = 0
  ncheck = 0
  ncases = 0
  seed = 4242_i64
  worst_ratio = 0
  worst_grad = 0
  worst_rdg = 0
  sum_ratio = 0

  call test_constants()
  call test_stencil()
  call test_stencil_isolation()
  call test_norms()
  call test_transform()
  call test_condition()
  call test_bound_against_quad()
  call test_rdg_extremes()

  print '(a,i0,a,i0,a)', 'test_numerics: ', ncheck, ' checks, ', nfail, ' failures'
  print '(a,i0,a,es10.3,a,es10.3)', 'bound validation: ', ncases, ' points, max |err|/bound = ', &
    worst_ratio, ', mean = ', sum_ratio/max(1, 3*ncases)
  print '(a,es10.3,a,es10.3)', 'vs binary128: max rel gradient err = ', worst_grad, &
    ', max rel RDG err = ', worst_rdg
  if (nfail /= 0) error stop 1

contains

  subroutine check(cond, what)
    logical, intent(in) :: cond
    character(len=*), intent(in) :: what
    ncheck = ncheck + 1
    if (.not. cond) then
      nfail = nfail + 1
      if (nfail <= 40) print '(2a)', 'FAIL: ', what
    end if
  end subroutine check

  function rnd() result(x)
    real(dp) :: x
    seed = seed*6364136223846793005_i64 + 1442695040888963407_i64
    x = real(ishft(seed, -11), dp)*2.0_dp**(-53)
  end function rnd

  subroutine test_constants()
    real(qp) :: pi, c
    real(dp) :: lo, hi
    pi = 4*atan(1.0_qp)
    c = 2*(3*pi*pi)**(1.0_qp/3)
    call check(transfer(C_RDG, 0_i64) == C_RDG_BITS, 'C_RDG literal rounds to 0x4018BFD4DD6882CB')
    lo = nearest(C_RDG, -1.0_dp)
    hi = nearest(C_RDG, 1.0_dp)
    call check(abs(real(C_RDG, qp) - c) < abs(real(lo, qp) - c) .and. &
               abs(real(C_RDG, qp) - c) < abs(real(hi, qp) - c), 'C_RDG is the nearest binary64')
    call check(transfer(qnan(), 0_i64) == QNAN_BITS .and. qnan() /= qnan(), 'canonical quiet NaN')
    call check(U_ROUND == 2.0_dp**(-53) .and. EPS_MACH == 2.0_dp**(-52), 'unit roundoff')
    call check(GAMMA12 > 12*U_ROUND .and. GAMMA12 < 12.001_dp*U_ROUND, 'gamma_12')
    call check(is_finite(huge(1.0_dp)) .and. is_finite(-tiny(1.0_dp)) .and. &
               is_finite(2.0_dp**(-1074)) .and. is_finite(-0.0_dp), 'finite values')
    call check(.not. is_finite(transfer(int(z'7FF0000000000000', i64), 1.0_dp)) .and. &
               .not. is_finite(transfer(int(z'FFF0000000000000', i64), 1.0_dp)) .and. &
               .not. is_finite(qnan()) .and. &
               .not. is_finite(transfer(int(z'7FF0000000000001', i64), 1.0_dp)), 'Inf and NaN')
    call check(JACOBI_MAX_ROTATIONS == 30 .and. JACOBI_OFFDIAG_TOL == 64*EPS_MACH, &
               'frozen Jacobi controls')
  end subroutine test_constants

  subroutine test_stencil()
    integer :: off(3, 61), i, j, nz, naxial, nplane, ncentre
    logical :: unique
    off = stencil61()
    unique = .true.
    do i = 1, 61
      do j = i + 1, 61
        if (all(off(:, i) == off(:, j))) unique = .false.
      end do
    end do
    call check(unique, '61 distinct offsets')
    ncentre = 0
    naxial = 0
    nplane = 0
    do i = 1, 61
      nz = count(off(:, i) /= 0)
      if (nz == 0) ncentre = ncentre + 1
      if (nz == 1) naxial = naxial + 1
      if (nz == 2) nplane = nplane + 1
      call check(all(abs(off(:, i)) <= 2), 'radius 2')
    end do
    call check(ncentre == 1 .and. naxial == 12 .and. nplane == 48, 'centre 1 + axial 12 + planes 48')
  end subroutine test_stencil

  !> point_eval must read nothing outside the 61 offsets: NaN elsewhere.
  subroutine test_stencil_isolation()
    real(dp) :: blk(-2:2, -2:2, -2:2), clean(-2:2, -2:2, -2:2), m(3, 3)
    type(point_result) :: r1, r2
    integer :: i, j, k, off(3, 61), n
    off = stencil61()
    do k = -2, 2
      do j = -2, 2
        do i = -2, 2
          clean(i, j, k) = 1.0_dp + 0.3_dp*rnd()
        end do
      end do
    end do
    blk = qnan()
    do n = 1, 61
      blk(off(1, n), off(2, n), off(3, n)) = clean(off(1, n), off(2, n), off(3, n))
    end do
    m = reshape([2.0_dp, 0.1_dp, -0.3_dp, 0.4_dp, 1.7_dp, 0.2_dp, 0.0_dp, -0.5_dp, 2.2_dp], [3, 3])
    call hook_point_eval(blk, m, JACOBI_MAX_ROTATIONS, r1)
    call hook_point_eval(clean, m, JACOBI_MAX_ROTATIONS, r2)
    call check(r1%status == PT_OK, 'NaN outside the stencil is never read')
    call check(all(r1%hess == r2%hess) .and. all(r1%grad == r2%grad) .and. &
               all(r1%lambda == r2%lambda) .and. r1%rdg == r2%rdg, 'identical results')
  end subroutine test_stencil_isolation

  subroutine test_norms()
    call check(abs(fro_norm(3, [3.0e200_dp, 4.0e200_dp, 0.0_dp]) - 5.0e200_dp) <= 4*EPS_MACH*5.0e200_dp, &
               'no overflow at 1e200')
    call check(abs(fro_norm(3, [3.0e-200_dp, 4.0e-200_dp, 0.0_dp]) - 5.0e-200_dp) <= 4*EPS_MACH*5.0e-200_dp, &
               'no underflow at 1e-200')
    call check(fro_norm(2, [scale(3.0_dp, -1070), scale(4.0_dp, -1070)]) == scale(5.0_dp, -1070), &
               'subnormal components')
    call check(fro_norm(3, [0.0_dp, -0.0_dp, 0.0_dp]) == 0, 'zero vector')
    call check(fro_norm(3, [1.0_dp, huge(1.0_dp), huge(1.0_dp)]) > huge(1.0_dp), &
               'genuine overflow gives Inf')
    call check(.not. is_finite(fro_norm(2, [1.0_dp, qnan()])), 'NaN propagates')
    call check(fro_norm(1, [-7.0_dp]) == 7, 'single component exact')
    call check(abs(hypot2(3.0e300_dp, -4.0e300_dp) - 5.0e300_dp) <= 2*EPS_MACH*5.0e300_dp, &
               'hypot2 without overflow')
    call check(hypot2(scale(3.0_dp, -1070), scale(4.0_dp, -1070)) == scale(5.0_dp, -1070), &
               'hypot2 of subnormals')
    call check(abs(hypot2(1.0e-300_dp, 1.0e-300_dp) - sqrt(2.0_dp)*1.0e-300_dp) <= &
               2*EPS_MACH*1.5e-300_dp, 'hypot2 of two tiny equal values')
    call check(hypot2(0.0_dp, -2.0_dp) == 2 .and. hypot2(0.0_dp, 0.0_dp) == 0 .and. &
               hypot2(-3.0_dp, 4.0_dp) == 5, 'hypot2 exact small cases')
  end subroutine test_norms

  subroutine test_transform()
    real(dp) :: m(3, 3), gq(3), hq(3, 3), gr(3), hr(3, 3), ex(3, 3)
    real(dp), parameter :: jinv(9) = [1, 2, 3, 4, 5, 6, 7, 8, 10]
    integer :: i, j, a, b
    m = jinv_matrix(jinv)
    call check(m(1, 1) == 1 .and. m(1, 2) == 2 .and. m(1, 3) == 3 .and. m(2, 1) == 4 .and. &
               m(3, 3) == 10, 'row-major j_inv: M(i,a) = j_inv[3i+a]')
    hq = 0
    hq(1, 1) = 1
    gq = [1.0_dp, 0.0_dp, 0.0_dp]
    call cartesian_transform(m, gq, hq, gr, hr)
    call check(all(gr == [1.0_dp, 2.0_dp, 3.0_dp]), 'g_r = Jinv^T e_1 is the first row of j_inv')
    gq = [0.0_dp, 1.0_dp, 0.0_dp]
    call cartesian_transform(m, gq, hq, gr, hr)
    call check(all(gr == [4.0_dp, 5.0_dp, 6.0_dp]), 'g_r = Jinv^T e_2 is the second row')
    ! integer H_q and M: exact result M^T H M
    hq = reshape([3, -1, 2, -1, 4, 0, 2, 0, -5], [3, 3])
    gq = [1.0_dp, -2.0_dp, 3.0_dp]
    call cartesian_transform(m, gq, hq, gr, hr)
    do a = 1, 3
      do b = 1, 3
        ex(a, b) = 0
        do i = 1, 3
          do j = 1, 3
            ex(a, b) = ex(a, b) + m(i, a)*hq(i, j)*m(j, b)
          end do
        end do
      end do
    end do
    call check(all(hr == ex), 'Jinv^T H_q Jinv on integers is exact')
    call check(all(gr == matmul(transpose(m), gq)), 'Jinv^T g_q on integers is exact')
    call check(all(hr == transpose(hr)), 'exact symmetric result')
  end subroutine test_transform

  function rotation(a, b, c) result(r)
    real(qp), intent(in) :: a, b, c
    real(qp) :: r(3, 3), rz(3, 3), ry(3, 3), rx(3, 3)
    rz = reshape([cos(a), sin(a), 0.0_qp, -sin(a), cos(a), 0.0_qp, 0.0_qp, 0.0_qp, 1.0_qp], [3, 3])
    ry = reshape([cos(b), 0.0_qp, -sin(b), 0.0_qp, 1.0_qp, 0.0_qp, sin(b), 0.0_qp, cos(b)], [3, 3])
    rx = reshape([1.0_qp, 0.0_qp, 0.0_qp, 0.0_qp, cos(c), sin(c), 0.0_qp, -sin(c), cos(c)], [3, 3])
    r = matmul(rz, matmul(ry, rx))
  end function rotation

  !> Row-major j_inv of R diag(s) R^T (rounded once from binary128).
  function rotated_jinv(s, r) result(j)
    real(qp), intent(in) :: s(3), r(3, 3)
    real(dp) :: j(9)
    real(qp) :: a(3, 3)
    integer :: i, k
    a = matmul(r, matmul(reshape([s(1), 0.0_qp, 0.0_qp, 0.0_qp, s(2), 0.0_qp, 0.0_qp, 0.0_qp, s(3)], &
                                 [3, 3]), transpose(r)))
    do i = 1, 3
      do k = 1, 3
        j(3*(i - 1) + k) = real(a(i, k), dp)
      end do
    end do
  end function rotated_jinv

  subroutine test_condition()
    real(dp) :: j(9), kappa, mm(3, 3)
    real(qp) :: sv(3), r(3, 3)
    integer :: verdict, k, i
    real(qp), parameter :: kappas(6) = [1.0_qp, 10.0_qp, 524.0_qp, 999.9_qp, 1000.1_qp, 1.0e4_qp]
    j = [1, 0, 0, 0, 1, 0, 0, 0, 1000]
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_ACCEPTED .and. kappa == 1000, 'diag(1,1,1000): accepted, kappa exactly 1000')
    j(9) = nearest(1000.0_dp, 1.0_dp)
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_TOO_LARGE, 'diag(1,1,1000+ulp) rejected')
    j = [1.0e-200_dp, 0.0_dp, 0.0_dp, 0.0_dp, 1.0_dp, 0.0_dp, 0.0_dp, 0.0_dp, 1.0_dp]
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_TOO_LARGE, 'graded column norms rejected by the precheck')
    r = rotation(0.4_qp, -1.2_qp, 2.1_qp)
    do k = 1, size(kappas)
      j = rotated_jinv([1.0_qp, 0.5_qp*(1 + kappas(k)), kappas(k)], r)
      do i = 1, 3
        mm(i, :) = j(3*i - 2:3*i)
      end do
      call ref_singular_values(mm, sv)
      call jinv_condition(j, verdict, kappa)
      if (kappas(k) <= 1000) then
        call check(verdict == COND_ACCEPTED, 'rotated kappa <= 1000 accepted')
      else
        call check(verdict == COND_TOO_LARGE, 'rotated kappa > 1000 rejected')
      end if
      if (kappas(k) < 2000) call check(abs(real(kappa, qp) - maxval(sv)/minval(sv)) <= &
                                       1.0e-12_qp*maxval(sv)/minval(sv), &
                                       'one-sided Jacobi condition number accurate to 1e-12')
      call jinv_condition(scale(j, -600), verdict, kappa)
      call check((verdict == COND_ACCEPTED) .eqv. (kappas(k) <= 1000), 'scale invariance 2^-600')
      call jinv_condition(j*1.0e200_dp, verdict, kappa)
      call check((verdict == COND_ACCEPTED) .eqv. (kappas(k) <= 1000), 'scale invariance 1e200')
    end do
    j = [1, 2, 3, 2, 4, 6, 0, 0, 1]
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_SINGULAR .or. verdict == COND_TOO_LARGE, 'rank-2 rejected')
    j = [1, 1, 1, 1, 1, 1, 1, 1, 1]
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_SINGULAR .or. verdict == COND_TOO_LARGE, 'rank-1 rejected')
    j = 0
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_SINGULAR, 'zero rejected as singular')
    j = [1.0_dp, 0.0_dp, 0.0_dp, 0.0_dp, 1.0_dp, 0.0_dp, 0.0_dp, 0.0_dp, qnan()]
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_NONFINITE, 'NaN rejected')
    j = rotated_jinv([1.0_qp, 2.0_qp, 1.0e17_qp], r)
    call jinv_condition(j, verdict, kappa)
    call check(verdict /= COND_ACCEPTED, 'kappa 1e17 rejected')
    j = [-1, 0, 0, 0, 0, 1, 0, 1, 0]
    call jinv_condition(j, verdict, kappa)
    call check(verdict == COND_ACCEPTED .and. kappa == 1, 'left-handed permutation, kappa 1')
  end subroutine test_condition

  !> Rigorous-bound validation: |lambda_k(computed) - lambda_k(exact)| <= bound
  !> for random stencils, cancellation-dominated stencils, graded low-density
  !> neighbours, skewed J inverses up to kappa ~ 1000 and extreme scales.
  subroutine test_bound_against_quad()
    real(dp) :: blk(-2:2, -2:2, -2:2), m(3, 3), sr, sm, base, amp, jj(9)
    real(dp) :: x0, y0, z0, width, e1, e2, e3
    real(qp) :: gr(3), hr(3, 3), lam(3), rdg, r(3, 3)
    type(point_result) :: res
    integer :: it, i, j, k, family, d
    real(dp) :: err, gerr, gn
    do it = 1, 24000
      family = mod(it, 8)
      ! J inverse
      select case (mod(it, 3))
      case (0)
        m = 0
        m(1, 1) = 1 + 9*rnd()
        m(2, 2) = 1 + 9*rnd()
        m(3, 3) = 1 + 9*rnd()
      case (1)
        do i = 1, 3
          do j = 1, 3
            m(i, j) = 4*rnd() - 2
          end do
          m(i, i) = m(i, i) + 4
        end do
      case default
        e1 = 6*rnd()
        e2 = 6*rnd()
        e3 = 6*rnd()
        r = rotation(real(e1, qp), real(e2, qp), real(e3, qp))
        e1 = 1 + 30*rnd()
        e2 = 1 + 900*rnd()
        jj = rotated_jinv([1.0_qp, real(e1, qp), real(e2, qp)], r)
        do i = 1, 3
          m(i, :) = jj(3*i - 2:3*i)
        end do
      end select
      ! density block
      base = 0.5_dp + rnd()
      amp = 0.5_dp
      if (family == 1) amp = 1.0e-9_dp
      if (family == 2) amp = 1.0e-14_dp
      x0 = 0.3_dp*(rnd() - 0.5_dp)
      y0 = 0.3_dp*(rnd() - 0.5_dp)
      z0 = 0.3_dp*(rnd() - 0.5_dp)
      width = 0.5_dp + 2*rnd()
      do k = -2, 2
        do j = -2, 2
          do i = -2, 2
            select case (family)
            case (3) ! smooth Gaussian sampled with h = 0.1
              blk(i, j, k) = exp(-width*((0.1_dp*i - x0)**2 + (0.1_dp*j - y0)**2 + &
                                         (0.1_dp*k - z0)**2))
            case (4) ! graded low-density neighbours 1e-12 .. 1
              blk(i, j, k) = 10.0_dp**(-12*rnd())
            case default
              blk(i, j, k) = base + amp*rnd()
            end select
          end do
        end do
      end do
      if (family == 4) blk(0, 0, 0) = 0.5_dp
      sr = 1
      sm = 1
      if (family == 5) then
        sr = 2.0_dp**(nint(600*rnd()) - 300)
        sm = 2.0_dp**(nint(400*rnd()) - 200)
      else if (family == 6) then ! deep underflow of H: floor regime
        sr = 2.0_dp**(-700)
        sm = 2.0_dp**(-180)
      else if (family == 7) then
        sr = 1.0e-200_dp*(1 + rnd())
        sm = 1.0e100_dp*(1 + rnd())
      end if
      blk = blk*sr
      m = m*sm
      call hook_point_eval(blk, m, JACOBI_MAX_ROTATIONS, res)
      call check(res%status == PT_OK, 'random point evaluates without numeric failure')
      if (res%status /= PT_OK) cycle
      call ref_point(blk, m, gr, hr, lam, rdg)
      ncases = ncases + 1
      do d = 1, 3
        err = real(abs(real(res%lambda(d), qp) - lam(d)), dp)
        call check(err <= res%bound, 'rigorous |lambda - exact discrete| <= bound')
        worst_ratio = max(worst_ratio, err/res%bound)
        sum_ratio = sum_ratio + err/res%bound
      end do
      call check(res%tau >= res%bound + TAU_ABS, 'tau includes the spec margins')
      ! Relative accuracy is meaningful only when |g| is not itself cancellation
      ! noise: require |g| > 1e-2 * (density scale) * sum|M|.
      gn = real(sqrt(sum(gr**2)), dp)
      if (family /= 6 .and. gn > 1.0e-2_dp*sr*sum(abs(m))) then
        gerr = real(sqrt(sum((real(res%grad, qp) - gr)**2)), dp)/gn
        worst_grad = max(worst_grad, gerr)
        worst_rdg = max(worst_rdg, real(abs(real(res%rdg, qp) - rdg)/rdg, dp))
      end if
      if (nfail > 40) return
    end do
    call check(worst_grad < 1.0e-12_dp, 'gradient matches binary128')
    call check(worst_rdg < 1.0e-12_dp, 'RDG matches binary128')
  end subroutine test_bound_against_quad

  subroutine test_rdg_extremes()
    real(dp) :: blk(-2:2, -2:2, -2:2), m(3, 3)
    type(point_result) :: res
    integer :: i, j, k
    m = 0
    m(1, 1) = 1
    m(2, 2) = 1
    m(3, 3) = 1
    blk = 1.0e300_dp
    call hook_point_eval(blk, m, 30, res)
    call check(res%status == PT_OK .and. res%rdg == 0 .and. res%lambda(2) == 0 .and. &
               res%uncertain .and. res%signed_rho == 0, 'constant 1e300 density: rdg 0, lambda2 0')
    do k = -2, 2
      do j = -2, 2
        do i = -2, 2
          blk(i, j, k) = 1.0e-300_dp*(1 + 0.1_dp*i)
        end do
      end do
    end do
    call hook_point_eval(blk, m, 30, res)
    call check(res%status == PT_OK .and. is_finite(res%rdg) .and. res%rdg > 0, &
               'rho ~ 1e-300: rho**(4/3) never underflows on its own')
    do k = -2, 2
      do j = -2, 2
        do i = -2, 2
          blk(i, j, k) = 1.0e200_dp*(1 + 0.1_dp*i)
        end do
      end do
    end do
    call hook_point_eval(blk, m, 30, res)
    call check(res%status == PT_OK .and. is_finite(res%rdg) .and. res%rdg > 0, &
               'rho ~ 1e200: rho**(4/3) never overflows on its own')
  end subroutine test_rdg_extremes

end program test_numerics
