! Test-only private bridge; never a source or export of a production DSO.
! Bounded synthetic ABI fixture, not a density model or performance sample.
module nci_benchmark_test_bridge
  use, intrinsic :: iso_c_binding
  use nci_abi
  use nci_capi, only: nci_context_create_v1, nci_context_destroy_v1, nci_eval_tile_f64_v1, nci_bench_get_timing
  use nci_bench_types, only: nci_bench_record
  implicit none
contains
  subroutine probe(backend,threads,n,results,records) bind(C,name='nci_test_timing_probe_v1')
    integer(c_int32_t), value :: backend,threads,n
    integer(c_int32_t), intent(out) :: results(10)
    type(nci_bench_record), intent(out) :: records(6)
    type(nci_options_v1), target :: options
    type(nci_tile_v1), target :: tile
    type(nci_tile_stats_v1), target :: stats
    type(c_ptr), target :: contexts(2)
    character(c_char), target :: error(1024)
    real(c_double), allocatable, target :: rho(:),rdg(:),lambda2(:),signedrho(:)
    integer(c_int8_t), allocatable, target :: flags(:)
    type(nci_bench_record) :: unchanged
    integer(c_int64_t) :: plane,nout,input_planes,p,ix,iy,iz
    real(c_double) :: x,y,z
    integer :: ios,i
    integer(c_int) :: status
    logical :: ok
    results=-1; contexts=c_null_ptr
    ! Records from failed early setup are explicitly not observed.
    do i=1,6
      records(i)%state=0; records(i)%timing_error=0; records(i)%observed_threads=0; records(i)%kernel_count=0
      records(i)%events_created=0; records(i)%events_destroyed=0; records(i)%async_queue=0; records(i)%reserved=0
      records(i)%stream_handle=0; records(i)%kernel_seconds=0; records(i)%device_seconds=0
    end do
    body: block
      if (n/=9.and.n/=384) exit body
      if (backend/=NCI_CPU.and.backend/=NCI_OPENACC) exit body
      if (threads/=1.and.threads/=4.and.threads/=8.and.threads/=16) exit body
      if (backend==NCI_OPENACC.and.threads/=1) exit body
      ! The largest-plane probe is a single GPU API slab, not a full-grid run.
      if (n==384.and.backend/=NCI_OPENACC) exit body
      plane=int(n,c_int64_t)*n; nout=4*plane
      input_planes=6
      if (n==384) input_planes=8
      allocate(rho(input_planes*plane),rdg(nout),lambda2(nout),signedrho(nout),flags(nout),stat=ios)
      if (ios/=0) exit body
      rho=0.5_c_double
      options%abi_version=1; options%struct_bytes=int(c_sizeof(options),c_int32_t)
      options%backend=backend; options%output_mode=NCI_FULL; options%omp_threads=threads; options%reserved=0
      options%rho_min=1.0e-8_c_double; options%negative_tolerance=0
      tile%abi_version=1; tile%struct_bytes=int(c_sizeof(tile),c_int32_t)
      tile%global_n=[int(n,c_int64_t),int(n,c_int64_t),int(n,c_int64_t)]
      tile%tile_start=0; tile%tile_count=[4_c_int64_t,int(n,c_int64_t),int(n,c_int64_t)]
      tile%input_origin=0; tile%input_shape=[6_c_int64_t,int(n,c_int64_t),int(n,c_int64_t)]
      tile%input_strides=[plane,int(n,c_int64_t),1_c_int64_t]
      tile%j_inv=[1.0_c_double,0.0_c_double,0.0_c_double,0.0_c_double,1.0_c_double, &
        0.0_c_double,0.0_c_double,0.0_c_double,1.0_c_double]
      tile%periodic=0; tile%reserved=0
      if (n==384) then
        ! Synthetic launch qualification only, not a stored-water worst bound.
        ! Interior B4 slab at global X=4..7; two halo planes on each side.
        tile%tile_start(1)=4; tile%input_origin(1)=2; tile%input_shape(1)=8
        ! Reuse pinned mixed quadratic v1 H, LINEAR and offset from
        ! tests/e2e/fixtures.py, sampled on a bounded dyadic coordinate grid.
        ! q=(global_index-192)/256, |q|<=3/4 on the entire 384^3 domain.
        ! rho >=4-(3/4)*(3/8)-(1/2)*(3/4)^2*(33/32)>3, so no clipping.
        ! H=[[-1/4,1/16,-1/32],[1/16,1/8,3/64],[-1/32,3/64,3/8]].
        tile%j_inv=256.0_c_double*tile%j_inv
        do ix=0,7
          x=real(2+ix-192,c_double)/256.0_c_double
          do iy=0,n-1
            y=real(iy-192,c_double)/256.0_c_double
            do iz=0,n-1
              z=real(iz-192,c_double)/256.0_c_double
              p=(ix*n+iy)*n+iz+1
              rho(p)=4.0_c_double+0.125_c_double*x-0.0625_c_double*y+0.1875_c_double*z+ &
                0.5_c_double*(-0.25_c_double*x*x+0.125_c_double*y*y+0.375_c_double*z*z)+ &
                0.0625_c_double*x*y-0.03125_c_double*x*z+0.046875_c_double*y*z
            end do
          end do
        end do
      end if
      tile%rho_capacity=input_planes*plane; tile%field_capacity=nout; tile%flags_capacity=nout
      tile%grad_capacity=0; tile%hess_capacity=0
      do i=1,2
        results(i+1)=nci_context_create_v1(c_loc(options),c_loc(contexts(i)),c_loc(error),size(error,kind=c_size_t))
        if (results(i+1)/=NCI_OK) exit body
      end do
      call nci_bench_get_timing(contexts(2),records(2),ok)
      if (.not.ok.or.records(2)%state/=0) exit body
      results(4)=evaluate_context(1)
      call nci_bench_get_timing(contexts(1),records(1),ok)
      if (results(4)/=NCI_OK.or..not.ok.or..not.valid_record(records(1),backend,threads)) exit body
      call nci_bench_get_timing(contexts(2),unchanged,ok)
      if (.not.ok.or.unchanged%state/=0) exit body
      if (n==384) then
        results(1)=0; exit body ! Exactly one largest-plane evaluation.
      end if
      results(5)=evaluate_context(2)
      call nci_bench_get_timing(contexts(2),records(3),ok)
      if (results(5)/=NCI_OK.or..not.ok.or..not.valid_record(records(3),backend,threads)) exit body
      call nci_bench_get_timing(contexts(1),unchanged,ok)
      if (.not.ok.or..not.same_record(unchanged,records(1))) exit body
      tile%reserved=1
      results(6)=evaluate_context(1)
      call nci_bench_get_timing(contexts(1),records(4),ok)
      if (results(6)/=NCI_INVALID_ARGUMENT.or..not.ok.or.records(4)%state/=0) exit body
      call nci_bench_get_timing(contexts(2),records(5),ok)
      if (.not.ok.or..not.same_record(records(5),records(3))) exit body
      tile%reserved=0
      results(7)=evaluate_context(1)
      call nci_bench_get_timing(contexts(1),records(6),ok)
      if (results(7)/=NCI_OK.or..not.ok.or..not.valid_record(records(6),backend,threads)) exit body
      results(1)=0
    end block body
    do i=1,2
      if (.not.c_associated(contexts(i))) cycle
      status=nci_context_destroy_v1(contexts(i),c_loc(error),size(error,kind=c_size_t))
      contexts(i)=c_null_ptr; results(i+7)=status
      if (status/=NCI_OK) results(1)=-1
    end do
    results(10)=0 ! Cleanup was attempted for each created handle; statuses remain above.
  contains
    integer(c_int) function evaluate_context(index) result(rc)
      integer, intent(in) :: index
      error=c_null_char
      rc=nci_eval_tile_f64_v1(contexts(index),c_loc(tile),c_loc(rho(1)),c_loc(rdg(1)),c_loc(signedrho(1)), &
        c_loc(lambda2(1)),c_null_ptr,c_null_ptr,c_loc(flags(1)),c_loc(stats),c_loc(error),size(error,kind=c_size_t))
    end function
  end subroutine

  logical function same_record(a,b) result(same)
    type(nci_bench_record), intent(in) :: a,b
    same=a%state==b%state.and.a%timing_error==b%timing_error.and.a%observed_threads==b%observed_threads.and. &
      a%kernel_count==b%kernel_count.and.a%events_created==b%events_created.and.a%events_destroyed==b%events_destroyed.and. &
      a%async_queue==b%async_queue.and.a%reserved==b%reserved.and.a%stream_handle==b%stream_handle.and. &
      transfer(a%kernel_seconds,0_c_int64_t)==transfer(b%kernel_seconds,0_c_int64_t).and. &
      transfer(a%device_seconds,0_c_int64_t)==transfer(b%device_seconds,0_c_int64_t)
  end function

  logical function valid_record(record,backend,threads) result(valid)
    use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
    type(nci_bench_record), intent(in) :: record
    integer(c_int32_t), intent(in) :: backend,threads
    valid=record%state==1.and.record%timing_error==0.and.record%reserved==0.and.record%kernel_count==1
    valid=valid.and.ieee_is_finite(record%kernel_seconds).and.ieee_is_finite(record%device_seconds)
    valid=valid.and.record%kernel_seconds>=0.and.record%device_seconds>=0
    if (backend==NCI_CPU) then
      valid=valid.and.record%observed_threads==threads.and.record%device_seconds==record%kernel_seconds
      valid=valid.and.record%events_created==0.and.record%events_destroyed==0
      valid=valid.and.record%async_queue==0.and.record%stream_handle==0
    else
      valid=valid.and.record%observed_threads==0.and.record%events_created==2.and.record%events_destroyed==2
      valid=valid.and.record%async_queue==1.and.record%stream_handle/=0.and.record%kernel_seconds<=0.5_c_double
    end if
  end function
end module
