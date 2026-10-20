! SPDX-License-Identifier: MIT
!> Test-only quad-precision (binary128) reference.  Inputs are the exact
!> binary64 samples and J inverse; the stencil uses exact integer weights, so
!> the result approximates the exact discrete quantities to ~1e-33 relative.
!> Eigenvalues come from a cyclic-by-row Jacobi run to 1e-32 relative
!> (deliberately a different ordering and stopping rule from production).
module nci_ref_quad
  implicit none
  private
  integer, parameter, public :: qp = selected_real_kind(30)
  integer, parameter :: dp = kind(1.0d0)
  public :: ref_point, ref_eig3, ref_singular_values

contains

  subroutine ref_point(blk, m, gr, hr, lam, rdg)
    real(dp), intent(in) :: blk(-2:2, -2:2, -2:2), m(3, 3)
    real(qp), intent(out) :: gr(3), hr(3, 3), lam(3), rdg
    real(qp), parameter :: c(-2:2) = [1.0_qp, -8.0_qp, 0.0_qp, 8.0_qp, -1.0_qp]
    real(qp), parameter :: w(-2:2) = [-1.0_qp, 16.0_qp, -30.0_qp, 16.0_qp, -1.0_qp]
    real(qp) :: b(-2:2, -2:2, -2:2), gq(3), hq(3, 3), mq(3, 3), pi, cst
    integer :: p, t

    b = real(blk, qp)
    mq = real(m, qp)
    gq = 0
    hq = 0
    do t = -2, 2
      gq(1) = gq(1) + c(t)*b(t, 0, 0)
      gq(2) = gq(2) + c(t)*b(0, t, 0)
      gq(3) = gq(3) + c(t)*b(0, 0, t)
      hq(1, 1) = hq(1, 1) + w(t)*b(t, 0, 0)
      hq(2, 2) = hq(2, 2) + w(t)*b(0, t, 0)
      hq(3, 3) = hq(3, 3) + w(t)*b(0, 0, t)
      do p = -2, 2
        hq(1, 2) = hq(1, 2) + c(p)*c(t)*b(p, t, 0)
        hq(1, 3) = hq(1, 3) + c(p)*c(t)*b(p, 0, t)
        hq(2, 3) = hq(2, 3) + c(p)*c(t)*b(0, p, t)
      end do
    end do
    gq = gq/12
    hq(1, 1) = hq(1, 1)/12
    hq(2, 2) = hq(2, 2)/12
    hq(3, 3) = hq(3, 3)/12
    hq(1, 2) = hq(1, 2)/144
    hq(1, 3) = hq(1, 3)/144
    hq(2, 3) = hq(2, 3)/144
    hq(2, 1) = hq(1, 2)
    hq(3, 1) = hq(1, 3)
    hq(3, 2) = hq(2, 3)
    gr = matmul(transpose(mq), gq)
    hr = matmul(transpose(mq), matmul(hq, mq))
    hr = 0.5_qp*(hr + transpose(hr))
    call ref_eig3(hr, lam)
    pi = 4*atan(1.0_qp)
    cst = 2*(3*pi*pi)**(1.0_qp/3)
    rdg = sqrt(sum(gr**2))/(cst*b(0, 0, 0)**(4.0_qp/3))
  end subroutine ref_point

  subroutine ref_eig3(a_in, lam)
    real(qp), intent(in) :: a_in(3, 3)
    real(qp), intent(out) :: lam(3)
    real(qp) :: a(3, 3), theta, t, c, s, tau, app, aqq, apq, arp, arq, off, nrm, tmp
    integer :: sweep, p, q, r

    a = a_in
    nrm = sqrt(sum(a**2))
    do sweep = 1, 100
      off = sqrt(2*(a(1, 2)**2 + a(1, 3)**2 + a(2, 3)**2))
      if (off <= 1.0e-32_qp*nrm .or. off == 0) exit
      do p = 1, 2
        do q = p + 1, 3
          apq = a(p, q)
          if (apq == 0) cycle
          app = a(p, p)
          aqq = a(q, q)
          theta = (aqq - app)/(2*apq)
          t = sign(1.0_qp, theta)/(abs(theta) + sqrt(theta*theta + 1))
          c = 1/sqrt(t*t + 1)
          s = t*c
          tau = s/(1 + c)
          a(p, p) = app - t*apq
          a(q, q) = aqq + t*apq
          a(p, q) = 0
          a(q, p) = 0
          do r = 1, 3
            if (r == p .or. r == q) cycle
            arp = a(r, p)
            arq = a(r, q)
            a(r, p) = arp - s*(arq + tau*arp)
            a(r, q) = arq + s*(arp - tau*arq)
            a(p, r) = a(r, p)
            a(q, r) = a(r, q)
          end do
        end do
      end do
    end do
    lam = [a(1, 1), a(2, 2), a(3, 3)]
    do p = 1, 2
      do q = p + 1, 3
        if (lam(q) < lam(p)) then
          tmp = lam(p); lam(p) = lam(q); lam(q) = tmp
        end if
      end do
    end do
  end subroutine ref_eig3

  !> Singular values of a 3x3 matrix as square roots of eig(M^T M) in quad:
  !> squaring is harmless at 1e-33 working precision for kappa <= 1e8.
  subroutine ref_singular_values(m, sv)
    real(dp), intent(in) :: m(3, 3)
    real(qp), intent(out) :: sv(3)
    real(qp) :: mq(3, 3), lam(3)
    mq = real(m, qp)
    call ref_eig3(matmul(transpose(mq), mq), lam)
    sv = sqrt(max(lam, 0.0_qp))
  end subroutine ref_singular_values

end module nci_ref_quad
