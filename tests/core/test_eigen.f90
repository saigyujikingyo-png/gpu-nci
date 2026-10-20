! SPDX-License-Identifier: MIT
!> White-box tests of the scaled symmetric 3x3 Jacobi solver: independent
!> known roots, exact power-of-two scaling, degenerate/zero spectra, extreme
!> ratios, forced nonconvergence through the test hook, random graded and
!> clustered matrices against a binary128 reference, and validity of the
!> returned a-posteriori bound.
program test_eigen
  use nci_kinds
  use nci_numerics
  use nci_test_hooks
  use nci_ref_quad
  implicit none

  integer :: nfail, ncheck, max_rot_seen
  real(dp) :: worst_ratio, worst_rel
  integer(i64) :: seed

  nfail = 0
  ncheck = 0
  max_rot_seen = 0
  worst_ratio = 0
  worst_rel = 0
  seed = 20261020_i64

  call test_known_roots()
  call test_power_of_two_scaling()
  call test_decimal_and_subnormal_scaling()
  call test_extreme_ratios()
  call test_forced_nonconvergence()
  call test_random(40000)

  print '(a,i0,a,i0,a,i0)', 'test_eigen: ', ncheck, ' checks, ', nfail, &
    ' failures; max rotations seen = ', max_rot_seen
  print '(a,es10.3,a,f6.2,a)', 'test_eigen: max |err|/bound = ', worst_ratio, &
    ', max |err|/|A|_2 = ', worst_rel/EPS_MACH, ' eps'
  if (nfail /= 0) error stop 1

contains

  subroutine check(cond, what)
    logical, intent(in) :: cond
    character(len=*), intent(in) :: what
    ncheck = ncheck + 1
    if (.not. cond) then
      nfail = nfail + 1
      print '(2a)', 'FAIL: ', what
    end if
  end subroutine check

  function rnd() result(x)
    real(dp) :: x
    seed = seed*6364136223846793005_i64 + 1442695040888963407_i64
    x = real(ishft(seed, -11), dp)*2.0_dp**(-53)
  end function rnd

  function h6_of(a) result(h)
    real(dp), intent(in) :: a(3, 3)
    real(dp) :: h(6)
    h = [a(1, 1), a(2, 2), a(3, 3), a(1, 2), a(1, 3), a(2, 3)]
  end function h6_of

  !> Run the production solver and verify info, ordering, rotation cap,
  !> |lam - exact| <= bound (+abs_slack) and the accuracy target.
  subroutine verify(a, exact, what, abs_slack)
    real(dp), intent(in) :: a(3, 3)
    real(qp), intent(in) :: exact(3)
    character(len=*), intent(in) :: what
    real(dp), intent(in), optional :: abs_slack
    real(dp) :: lam(3), bound, amax, err, slack
    integer :: nrot, info, k
    slack = 0
    if (present(abs_slack)) slack = abs_slack
    call eig3_jacobi(h6_of(a), JACOBI_MAX_ROTATIONS, lam, bound, nrot, info)
    call check(info == EIG_OK, what//': info')
    if (info /= EIG_OK) return
    max_rot_seen = max(max_rot_seen, nrot)
    call check(nrot <= JACOBI_MAX_ROTATIONS, what//': rotation cap')
    call check(lam(1) <= lam(2) .and. lam(2) <= lam(3), what//': ascending order')
    ! |A|_2 = max |exact eigenvalue|.  The frozen stopping rule leaves an
    ! off-diagonal of up to 64 eps max|a_ij| <= 64 eps |A|_2 (Weyl), plus
    ! rounding of <= 10 rotations: target 80 eps |A|_2 in absolute terms.
    amax = real(maxval(abs(exact)), dp)
    do k = 1, 3
      err = real(abs(real(lam(k), qp) - exact(k)), dp)
      call check(err <= bound + slack, what//': |lambda - exact| <= bound')
      if (bound > 0) worst_ratio = max(worst_ratio, err/bound)
      if (amax > 0) then
        call check(err <= 80*EPS_MACH*amax + slack, what//': accuracy 80 eps |A|_2')
        if (.not. (err <= 80*EPS_MACH*amax + slack)) then
          print '(a,i0,a,i0,a,3es24.16)', '  k=', k, ' nrot=', nrot, ' lam=', lam
          print '(a,3es24.16)', '  exact=', real(exact, dp)
          print '(a,6es24.16)', '  h6=', h6_of(a)
        end if
        worst_rel = max(worst_rel, err/amax)
      end if
    end do
    if (amax > 0) call check(bound <= 1.0e-13_dp*amax + slack, what//': bound is sharp')
  end subroutine verify

  function pdp(d) result(a)
    !> P diag(d) P^T with the integer orthogonal-up-to-3 matrix P; exact.
    real(dp), intent(in) :: d(3)
    real(dp) :: a(3, 3)
    real(dp), parameter :: p(3, 3) = reshape([1, 2, 2, 2, 1, -2, 2, -2, 1], [3, 3])
    integer :: i, j, k
    do i = 1, 3
      do j = 1, 3
        a(i, j) = 0
        do k = 1, 3
          a(i, j) = a(i, j) + p(i, k)*d(k)*p(j, k)
        end do
      end do
    end do
  end function pdp

  subroutine test_known_roots()
    real(dp) :: a(3, 3)
    real(qp) :: r2
    r2 = sqrt(2.0_qp)
    a = reshape([2, 1, 1, 1, 2, 1, 1, 1, 2], [3, 3])
    call verify(a, [1.0_qp, 1.0_qp, 4.0_qp], 'ones+I (1,1,4)')
    a = reshape([7, -2, 0, -2, 6, -2, 0, -2, 5], [3, 3])
    call verify(a, [3.0_qp, 6.0_qp, 9.0_qp], 'tridiagonal (3,6,9)')
    a = reshape([2, -1, 0, -1, 2, -1, 0, -1, 2], [3, 3])
    call verify(a, [2 - r2, 2.0_qp, 2 + r2], 'laplacian (2-sqrt2,2,2+sqrt2)')
    a = pdp([-1.0_dp, 2.0_dp, 3.0_dp])
    call verify(a, [-9.0_qp, 18.0_qp, 27.0_qp], 'P diag P^T (-9,18,27)')
    a = pdp([1.0_dp, 1.0_dp, 2.0_dp])
    call verify(a, [9.0_qp, 9.0_qp, 18.0_qp], 'P diag P^T double root')
    a = pdp([-2.0_dp, -2.0_dp, -2.0_dp])
    call verify(a, [-18.0_qp, -18.0_qp, -18.0_qp], 'P diag P^T triple root')
    a = reshape([1, 2, 2, 2, 1, 2, 2, 2, 1], [3, 3])
    call verify(a, [-1.0_qp, -1.0_qp, 5.0_qp], 'all-twos (-1,-1,5)')
    a = reshape([0, 1, 0, 1, 0, 0, 0, 0, 0], [3, 3])
    call verify(a, [-1.0_qp, 0.0_qp, 1.0_qp], 'pure off-diagonal (-1,0,1)')
    a = 0
    a(1, 1) = -3
    a(3, 3) = 3
    call verify(a, [-3.0_qp, 0.0_qp, 3.0_qp], 'diag(-3,0,3)')
    a = 0
    call verify(a, [0.0_qp, 0.0_qp, 0.0_qp], 'zero matrix')
    a = 0
    a(1, 1) = 5
    a(2, 2) = 5
    a(3, 3) = 5
    call verify(a, [5.0_qp, 5.0_qp, 5.0_qp], '5 I')
    block
      real(dp) :: lam(3), bound
      integer :: nrot, info
      call eig3_jacobi([0.0_dp, 0.0_dp, 0.0_dp, 0.0_dp, 0.0_dp, 0.0_dp], 30, lam, bound, nrot, info)
      call check(info == EIG_OK .and. nrot == 0 .and. all(lam == 0) .and. bound == 0, &
                 'zero matrix handled separately')
      call eig3_jacobi([3.0_dp, -1.0_dp, 2.0_dp, 0.0_dp, 0.0_dp, 0.0_dp], 30, lam, bound, nrot, info)
      call check(nrot == 0 .and. lam(1) == -1 .and. lam(2) == 2 .and. lam(3) == 3, &
                 'diagonal: no rotation, exact sorted diagonal')
    end block
  end subroutine test_known_roots

  subroutine test_power_of_two_scaling()
    real(dp) :: a(3, 3), lam0(3), b0, lam(3), b
    integer :: nrot, info, k, ks(6), im
    ks = [-1000, -500, -60, 60, 500, 1000]
    do im = 1, 3
      select case (im)
      case (1)
        a = reshape([2, 1, 1, 1, 2, 1, 1, 1, 2], [3, 3])
      case (2)
        a = pdp([-1.0_dp, 2.0_dp, 3.0_dp])
      case default
        a = reshape([4.0_dp, -0.5_dp, 0.25_dp, -0.5_dp, -3.0_dp, 1.5_dp, &
                     0.25_dp, 1.5_dp, 0.125_dp], [3, 3])
      end select
      call eig3_jacobi(h6_of(a), 30, lam0, b0, nrot, info)
      do k = 1, size(ks)
        call eig3_jacobi(h6_of(scale(a, ks(k))), 30, lam, b, nrot, info)
        call check(info == EIG_OK .and. all(lam == scale(lam0, ks(k))) .and. b == scale(b0, ks(k)), &
                   'exact 2**k scale invariance of eigenvalues and bound')
      end do
    end do
  end subroutine test_power_of_two_scaling

  subroutine test_decimal_and_subnormal_scaling()
    real(dp) :: a(3, 3), s
    real(dp), parameter :: scales(5) = [1.0e-300_dp, 1.0e-150_dp, 1.0e150_dp, 1.0e300_dp, 3.7_dp]
    real(qp) :: ex(3)
    integer :: k
    a = pdp([-1.0_dp, 2.0_dp, 3.0_dp])
    do k = 1, size(scales)
      s = scales(k)
      ! The scaled matrix is rounded; its exact eigenvalues come from binary128.
      call ref_eig3(real(a*s, qp), ex)
      call verify(a*s, ex, 'decimal scaling')
    end do
    ! Entries that are exact subnormals: final rescaling may round by 2**-1074.
    a = reshape([2, 1, 1, 1, 2, 1, 1, 1, 2], [3, 3])
    call verify(scale(a, -1070), [scale(1.0_qp, -1070), scale(1.0_qp, -1070), scale(4.0_qp, -1070)], &
                'subnormal entries', abs_slack=2.0_dp**(-1074))
  end subroutine test_decimal_and_subnormal_scaling

  subroutine test_extreme_ratios()
    real(dp) :: a(3, 3)
    real(qp) :: ex(3)
    integer :: k
    real(dp), parameter :: tiny_off(4) = [1.0e-300_dp, 1.0e-170_dp, 2.0_dp**(-1074), 1.0e-20_dp]
    do k = 1, size(tiny_off)
      a = 0
      a(1, 1) = 1
      a(2, 2) = 2
      a(3, 3) = 3
      a(1, 2) = tiny_off(k); a(2, 1) = a(1, 2)
      a(2, 3) = tiny_off(k); a(3, 2) = a(2, 3)
      call ref_eig3(real(a, qp), ex)
      call verify(a, ex, 'tiny off-diagonal, separated diagonal')
      ! nearly equal diagonal: rotation angle near pi/4 with tiny a_pq
      a(2, 2) = 1
      a(1, 1) = nearest(1.0_dp, 1.0_dp)
      call ref_eig3(real(a, qp), ex)
      call verify(a, ex, 'tiny off-diagonal, equal diagonal')
    end do
    a = 0
    a(1, 2) = 1
    a(2, 1) = 1
    a(1, 1) = 1.0e-30_dp
    a(2, 2) = -1.0e-30_dp
    call ref_eig3(real(a, qp), ex)
    call verify(a, ex, 'dominant off-diagonal')
    a = reshape([1.0e300_dp, 1.0e-300_dp, 1.0_dp, 1.0e-300_dp, -1.0e300_dp, 1.0e10_dp, &
                 1.0_dp, 1.0e10_dp, 5.0e299_dp], [3, 3])
    call ref_eig3(real(a, qp), ex)
    call verify(a, ex, '1e300 dynamic range')
    a = reshape([1.0e-300_dp, 1.0e-300_dp, 1.0e-300_dp, 1.0e-300_dp, 1.0e-300_dp, 1.0e-300_dp, &
                 1.0e-300_dp, 1.0e-300_dp, 1.0e-300_dp], [3, 3])
    call ref_eig3(real(a, qp), ex)
    call verify(a, ex, 'rank-one tiny matrix')
  end subroutine test_extreme_ratios

  subroutine test_forced_nonconvergence()
    real(dp) :: lam(3), bound
    integer :: nrot, info
    real(dp), parameter :: ones(6) = [2.0_dp, 2.0_dp, 2.0_dp, 1.0_dp, 1.0_dp, 1.0_dp]
    call hook_eig3(ones, 1, lam, bound, nrot, info)
    call check(info == EIG_NONCONVERGED .and. nrot == 1, 'max_rotations=1 on [[2,1,1],[1,2,1],[1,1,2]]')
    call check(all(lam /= lam) .and. bound /= bound, 'nonconverged: NaN, no pseudo-normal values')
    call hook_eig3(ones, 0, lam, bound, nrot, info)
    call check(info == EIG_NONCONVERGED .and. nrot == 0, 'max_rotations=0')
    call hook_eig3(ones, 30, lam, bound, nrot, info)
    call check(info == EIG_OK .and. nrot <= 30, 'same matrix converges with 30')
    call hook_eig3([1.0_dp, 2.0_dp, 3.0_dp, 0.0_dp, 0.0_dp, 0.0_dp], 0, lam, bound, nrot, info)
    call check(info == EIG_OK, 'diagonal input needs no rotation even with cap 0')
    block
      real(dp) :: blk(-2:2, -2:2, -2:2), m(3, 3)
      type(point_result) :: res
      integer :: i, j, k
      do k = -2, 2
        do j = -2, 2
          do i = -2, 2
            blk(i, j, k) = 2.0_dp + 0.1_dp*i*j + 0.05_dp*j*k + 0.07_dp*i*k + 0.01_dp*i*i
          end do
        end do
      end do
      m = 0
      m(1, 1) = 2
      m(2, 2) = 2
      m(3, 3) = 2
      call hook_point_eval(blk, m, 1, res)
      call check(res%status == PT_EIGEN_NONCONVERGED, 'point-level forced nonconvergence')
      call hook_point_eval(blk, m, JACOBI_MAX_ROTATIONS, res)
      call check(res%status == PT_OK, 'same point converges with the production cap')
    end block
  end subroutine test_forced_nonconvergence

  subroutine test_random(n)
    integer, intent(in) :: n
    real(dp) :: a(3, 3), d(3), q(3, 3)
    real(qp) :: ex(3)
    integer :: it, i, j, kind_
    real(dp) :: g(3)
    do it = 1, n
      kind_ = mod(it, 4)
      select case (kind_)
      case (0) ! dense uniform
        do j = 1, 3
          do i = j, 3
            a(i, j) = 2*rnd() - 1
            a(j, i) = a(i, j)
          end do
        end do
      case (1) ! graded D A D with D = diag(2**k), |k| <= 30
        do i = 1, 3
          g(i) = 2.0_dp**(nint(60*rnd()) - 30)
        end do
        do j = 1, 3
          do i = j, 3
            a(i, j) = (2*rnd() - 1)*g(i)*g(j)
            a(j, i) = a(i, j)
          end do
        end do
      case (2) ! clustered spectrum via a random rotation
        d(1) = 1.0_dp
        d(2) = 1.0_dp + 1.0e-10_dp*rnd()
        d(3) = -0.5_dp + 1.0e-12_dp*rnd()
        q = random_rotation()
        a = matmul(q, matmul(diag3(d), transpose(q)))
        a = 0.5_dp*(a + transpose(a))
      case default ! nearly singular / near-zero middle eigenvalue
        d(1) = -1.0_dp
        d(2) = 1.0e-14_dp*(2*rnd() - 1)
        d(3) = 1.0_dp + rnd()
        q = random_rotation()
        a = matmul(q, matmul(diag3(d), transpose(q)))
        a = 0.5_dp*(a + transpose(a))
      end select
      call ref_eig3(real(a, qp), ex)
      call verify(a, ex, 'random symmetric family '//achar(iachar('0') + kind_))
      if (nfail > 20) return
    end do
  end subroutine test_random

  function diag3(d) result(a)
    real(dp), intent(in) :: d(3)
    real(dp) :: a(3, 3)
    a = 0
    a(1, 1) = d(1)
    a(2, 2) = d(2)
    a(3, 3) = d(3)
  end function diag3

  function random_rotation() result(q)
    real(dp) :: q(3, 3), u(3), w(3), nrm
    integer :: k
    ! Gram-Schmidt on random vectors; orthogonal to ~1e-16 (exactness is not needed:
    ! the reference eigenvalues are computed from the rounded matrix itself).
    do k = 1, 3
      u(1) = 2*rnd() - 1
      u(2) = 2*rnd() - 1
      u(3) = 2*rnd() - 1
      if (k > 1) u = u - dot_product(u, q(:, 1))*q(:, 1)
      if (k > 2) u = u - dot_product(u, q(:, 2))*q(:, 2)
      nrm = sqrt(sum(u**2))
      w = u/nrm
      q(:, k) = w
    end do
  end function random_rotation

end program test_eigen
