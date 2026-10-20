! SPDX-License-Identifier: MIT
!> C ABI v1 entry points of the CPU backend (include/nci_api.h).
!>
!> Every pointer argument arrives as TYPE(C_PTR) by value and is converted
!> with C_F_POINTER only after its nullability and declared length have been
!> validated.  No STOP, no external I/O; errbuf is written once, bounded and
!> NUL terminated.
module nci_capi
  use, intrinsic :: iso_c_binding
  use nci_kinds
  use nci_abi
  use nci_validate
  use nci_numerics, only: jinv_matrix, PT_NONFINITE_DERIVATIVE, PT_NONFINITE_TRANSFORM, &
                          PT_ASYMMETRIC, PT_EIGEN_NONCONVERGED, PT_EIGEN_RESIDUAL, &
                          PT_NONFINITE_RESULT
  use nci_kernel
  implicit none
  private

  public :: nci_context_create_v1, nci_eval_tile_f64_v1, nci_context_destroy_v1

  integer(c_int64_t), parameter :: CTX_MAGIC = int(z'4E43495F43505531', c_int64_t)
  integer(c_int64_t), parameter :: ERRBUF_EXTENT = MSG_CAP + 1

  !> Heap context: one validated copy of the options.  Nothing is shared
  !> between contexts.
  type, bind(C) :: cpu_context
    integer(c_int64_t) :: magic
    type(nci_options_v1) :: options
  end type cpu_context

contains

  subroutine write_errbuf(errbuf, errbuf_len, msg)
    type(c_ptr), intent(in) :: errbuf
    integer(c_size_t), intent(in) :: errbuf_len
    type(message_t), intent(in) :: msg
    character(kind=c_char), pointer :: buf(:)
    integer(i64) :: cap, nchar, i
    if (.not. c_associated(errbuf)) return
    cap = int(errbuf_len, i64)          ! negative: size_t above 2**63-1
    if (cap == 0) return
    nchar = msg%n
    if (cap > 0) nchar = min(nchar, cap - 1)
    call c_f_pointer(errbuf, buf, [nchar + 1])
    do i = 1, nchar
      buf(i) = msg%text(i:i)
    end do
    buf(nchar + 1) = c_null_char
  end subroutine write_errbuf

  pure function address(p) result(a)
    type(c_ptr), intent(in) :: p
    integer(i64) :: a
    a = int(transfer(p, 0_c_intptr_t), i64)
  end function address

  function nci_context_create_v1(options, context, errbuf, errbuf_len) result(status) &
      bind(C, name='nci_context_create_v1')
    type(c_ptr), value :: options, context, errbuf
    integer(c_size_t), value :: errbuf_len
    integer(c_int) :: status
    type(c_ptr), pointer :: slot
    type(nci_options_v1), pointer :: optp
    type(nci_options_v1) :: opt
    type(cpu_context), pointer :: ctx
    type(message_t) :: msg
    integer :: ierr

    if (c_associated(context)) then
      call c_f_pointer(context, slot)
      slot = c_null_ptr
    end if
    status = NCI_INVALID_ARGUMENT
    if (.not. c_associated(errbuf) .and. errbuf_len /= 0) return

    body: block
      if (.not. abi_layout_ok()) then
        status = NCI_BACKEND_UNAVAILABLE
        call msg_set(msg, 'ABI v1 struct layout mismatch in this build')
        exit body
      end if
      if (.not. c_associated(context)) then
        call msg_set(msg, 'context (void **) is NULL')
        exit body
      end if
      if (.not. c_associated(options)) then
        call msg_set(msg, 'options is NULL')
        exit body
      end if
      call c_f_pointer(options, optp)
      opt = optp
      call check_options(opt, status, msg)
      if (status /= NCI_OK) exit body
      allocate (ctx, stat=ierr)
      if (ierr /= 0) then
        status = NCI_ALLOCATION_FAILURE
        call msg_set(msg, 'cannot allocate the CPU context')
        exit body
      end if
      ctx%magic = CTX_MAGIC
      ctx%options = opt
      slot = c_loc(ctx)
      status = NCI_OK
    end block body
    call write_errbuf(errbuf, errbuf_len, msg)
  end function nci_context_create_v1

  function nci_context_destroy_v1(context, errbuf, errbuf_len) result(status) &
      bind(C, name='nci_context_destroy_v1')
    type(c_ptr), value :: context, errbuf
    integer(c_size_t), value :: errbuf_len
    integer(c_int) :: status
    type(cpu_context), pointer :: ctx
    type(message_t) :: msg
    integer :: ierr

    status = NCI_INVALID_ARGUMENT
    if (.not. c_associated(errbuf) .and. errbuf_len /= 0) return
    body: block
      if (.not. c_associated(context)) then
        call msg_set(msg, 'context is NULL')
        exit body
      end if
      call c_f_pointer(context, ctx)
      if (ctx%magic /= CTX_MAGIC) then
        call msg_set(msg, 'context is not a live CPU context')
        exit body
      end if
      ctx%magic = 0
      deallocate (ctx, stat=ierr)
      if (ierr /= 0) then
        call msg_set(msg, 'context deallocation failed')
        exit body
      end if
      status = NCI_OK
    end block body
    call write_errbuf(errbuf, errbuf_len, msg)
  end function nci_context_destroy_v1

  function nci_eval_tile_f64_v1(context, tile, rho, rdg, signedrho, lambda2, grad, hess, &
                                flags, stats, errbuf, errbuf_len) result(status) &
      bind(C, name='nci_eval_tile_f64_v1')
    type(c_ptr), value :: context, tile, rho, rdg, signedrho, lambda2, grad, hess
    type(c_ptr), value :: flags, stats, errbuf
    integer(c_size_t), value :: errbuf_len
    integer(c_int) :: status

    type(cpu_context), pointer :: ctx
    type(nci_tile_v1), pointer :: tilep
    type(nci_tile_v1) :: t
    type(nci_options_v1) :: opt
    type(nci_tile_stats_v1), pointer :: st
    real(dp), pointer, contiguous :: rho_a(:), rdg_a(:), srho_a(:), lam_a(:)
    real(dp), pointer, contiguous :: grad_a(:, :), hess_a(:, :)
    real(dp), target :: no_grad(3, 0), no_hess(6, 0)
    integer(i8), pointer, contiguous :: flags_a(:)
    type(message_t) :: msg
    integer(i64) :: n, first_bad, n_negative, counts(0:7), p
    integer(i64) :: lo(9), ext(9)
    logical :: diagnostic, write_msg, periodic(3), is_write(9)
    real(dp) :: m(3, 3)
    integer :: kstatus, pstatus, nrot, i, j, nbuf

    status = NCI_INVALID_ARGUMENT
    if (.not. c_associated(errbuf) .and. errbuf_len /= 0) return
    write_msg = .true.

    body: block
      if (.not. abi_layout_ok()) then
        status = NCI_BACKEND_UNAVAILABLE
        call msg_set(msg, 'ABI v1 struct layout mismatch in this build')
        exit body
      end if
      if (.not. c_associated(context)) then
        call msg_set(msg, 'context is NULL')
        exit body
      end if
      call c_f_pointer(context, ctx)
      if (ctx%magic /= CTX_MAGIC) then
        call msg_set(msg, 'context is not a live CPU context')
        exit body
      end if
      opt = ctx%options
      diagnostic = opt%output_mode == NCI_DIAGNOSTIC

      if (.not. c_associated(tile)) then
        call msg_set(msg, 'tile is NULL')
        exit body
      end if
      call c_f_pointer(tile, tilep)
      t = tilep
      call check_tile_header(t, status, msg)
      if (status /= NCI_OK) exit body
      status = NCI_INVALID_ARGUMENT

      if (.not. c_associated(rho)) then
        call msg_set(msg, 'rho is NULL')
        exit body
      else if (.not. c_associated(rdg)) then
        call msg_set(msg, 'rdg is NULL')
        exit body
      else if (.not. c_associated(signedrho)) then
        call msg_set(msg, 'signedrho is NULL')
        exit body
      else if (.not. c_associated(lambda2)) then
        call msg_set(msg, 'lambda2 is NULL')
        exit body
      else if (.not. c_associated(flags)) then
        call msg_set(msg, 'flags is NULL')
        exit body
      else if (.not. c_associated(stats)) then
        call msg_set(msg, 'stats is NULL')
        exit body
      end if
      if (diagnostic) then
        if (.not. c_associated(grad) .or. .not. c_associated(hess)) then
          call msg_set(msg, 'NCI_DIAGNOSTIC requires non-NULL grad and hess')
          exit body
        end if
      else
        if (c_associated(grad) .or. c_associated(hess)) then
          call msg_set(msg, 'NCI_FULL requires NULL grad and hess')
          exit body
        end if
        if (t%grad_capacity /= 0 .or. t%hess_capacity /= 0) then
          call msg_set(msg, 'NCI_FULL requires zero grad_capacity and hess_capacity')
          exit body
        end if
      end if

      call check_tile_geometry(t, diagnostic, n, status, msg)
      if (status /= NCI_OK) exit body
      call check_jinv(t%j_inv, status, msg)
      if (status /= NCI_OK) exit body
      status = NCI_INVALID_ARGUMENT

      ! Written extents may not overlap each other, the density or errbuf.
      lo = 0
      ext = 0
      is_write = .true.
      lo(1) = address(rho);       ext(1) = 8*n;  is_write(1) = .false.
      lo(2) = address(rdg);       ext(2) = 8*n
      lo(3) = address(signedrho); ext(3) = 8*n
      lo(4) = address(lambda2);   ext(4) = 8*n
      lo(5) = address(flags);     ext(5) = n
      lo(6) = address(stats);     ext(6) = STATS_V1_BYTES
      nbuf = 6
      if (diagnostic) then
        lo(7) = address(grad); ext(7) = 24*n
        lo(8) = address(hess); ext(8) = 48*n
        nbuf = 8
      end if
      if (c_associated(errbuf)) then
        nbuf = nbuf + 1
        lo(nbuf) = address(errbuf)
        ext(nbuf) = int(errbuf_len, i64)
        if (ext(nbuf) < 0 .or. ext(nbuf) > ERRBUF_EXTENT) ext(nbuf) = ERRBUF_EXTENT
      end if
      do i = 1, nbuf
        do j = i + 1, nbuf
          if (.not. (is_write(i) .or. is_write(j))) cycle
          if (ranges_overlap(lo(i), ext(i), lo(j), ext(j))) then
            call msg_set(msg, 'buffers overlap: outputs must be distinct and must not alias rho')
            if (c_associated(errbuf) .and. (i == nbuf .or. j == nbuf)) write_msg = .false.
            exit body
          end if
        end do
      end do

      call c_f_pointer(rho, rho_a, [n])
      call preflight_density(n, rho_a, opt%negative_tolerance, int(opt%omp_threads), &
                             first_bad, n_negative)
      if (first_bad /= 0) then
        status = NCI_INVALID_INPUT
        call msg_set(msg, 'rho[')
        call msg_add_int(msg, first_bad - 1)
        if (.not. is_finite(rho_a(first_bad))) then
          call msg_add(msg, '] is NaN or Inf')
        else
          call msg_add(msg, '] is below -negative_tolerance')
        end if
        call msg_add(msg, '; input rejected before any output was written')
        exit body
      end if

      call c_f_pointer(rdg, rdg_a, [n])
      call c_f_pointer(signedrho, srho_a, [n])
      call c_f_pointer(lambda2, lam_a, [n])
      call c_f_pointer(flags, flags_a, [n])
      call c_f_pointer(stats, st)
      if (diagnostic) then
        call c_f_pointer(grad, grad_a, [3_i64, n])
        call c_f_pointer(hess, hess_a, [6_i64, n])
      else
        grad_a => no_grad
        hess_a => no_hess
      end if
      m = jinv_matrix(t%j_inv)
      periodic = t%periodic /= 0

      call evaluate_grid(t%global_n(1), t%global_n(2), t%global_n(3), periodic, m, rho_a, &
                         opt%rho_min, n_negative > 0, diagnostic, int(opt%omp_threads), &
                         rdg_a, srho_a, lam_a, grad_a, hess_a, flags_a, counts, kstatus)
      if (kstatus /= KERNEL_OK) then
        status = NCI_ALLOCATION_FAILURE
        call msg_set(msg, 'cannot allocate neighbour index tables; no output written')
        exit body
      end if

      st%total_points = n
      st%valid_points = counts(7)
      st%invalid_points = n - counts(7)
      st%numeric_failures = counts(4)
      st%bit_counts = counts(0:6)

      if (counts(4) > 0) then
        status = NCI_NUMERIC_FAILURE
        do p = 1, n
          if (btest(int(flags_a(p)), 4)) exit
        end do
        call diagnose_point(t%global_n(1), t%global_n(2), t%global_n(3), periodic, m, rho_a, &
                            opt%rho_min, p, pstatus, nrot)
        call msg_set(msg, 'numeric failure at ')
        call msg_add_int(msg, counts(4))
        call msg_add(msg, ' point(s); first at point ')
        call msg_add_int(msg, p - 1)
        select case (pstatus)
        case (PT_NONFINITE_DERIVATIVE)
          call msg_add(msg, ': non-finite index-space derivative')
        case (PT_NONFINITE_TRANSFORM)
          call msg_add(msg, ': non-finite Cartesian gradient/Hessian')
        case (PT_ASYMMETRIC)
          call msg_add(msg, ': transformed Hessian asymmetry above rounding bound')
        case (PT_EIGEN_NONCONVERGED)
          call msg_add(msg, ': Jacobi did not converge in 30 rotations')
        case (PT_EIGEN_RESIDUAL)
          call msg_add(msg, ': eigen residual/orthogonality check failed')
        case (PT_NONFINITE_RESULT)
          call msg_add(msg, ': non-finite eigenvalue or RDG')
        case default
          call msg_add(msg, ': unclassified')
        end select
      else if (counts(7) == 0) then
        status = NCI_INVALID_INPUT
        call msg_set(msg, 'no numerically valid point: every point carries a bit 0-3 flag')
      else
        status = NCI_OK
      end if
    end block body
    if (write_msg) call write_errbuf(errbuf, errbuf_len, msg)
  end function nci_eval_tile_f64_v1

end module nci_capi
