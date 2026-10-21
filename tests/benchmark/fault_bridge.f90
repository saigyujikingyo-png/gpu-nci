! Explicit test-only bounded fault fixture. Not a production DSO source/export.
module nci_benchmark_fault_bridge
  use, intrinsic :: iso_c_binding
  use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
  use nci_abi
  use nci_capi, only: nci_context_create_v1, nci_context_destroy_v1, nci_eval_tile_f64_v1, &
    nci_bench_get_timing, nci_bench_test_event_fault
  use nci_bench_types, only: nci_bench_record, nci_bench_reset
  use nci_benchmark_test_bridge, only: valid_record, same_record
  use nci_benchmark_support, only: benchmark_report, benchmark_observe
  implicit none
contains
  subroutine fault_probe(mode,results,records,bits,flags_raw,stats_raw) bind(C,name='nci_test_timing_fault_probe_v1')
    integer(c_int32_t), value :: mode
    integer(c_int32_t), intent(out) :: results(25)
    type(nci_bench_record), intent(out) :: records(7)
    integer(c_int64_t), intent(out) :: bits(972,6),stats_raw(11,6)
    integer(c_int8_t), intent(out) :: flags_raw(324,6)
    type(nci_options_v1), target :: options
    type(nci_tile_v1), target :: tile
    type(nci_tile_stats_v1), target :: stats
    type(benchmark_report) :: rejected_sample
    type(nci_bench_record) :: zero_record
    type(c_ptr), target :: contexts(2)
    character(c_char), target :: error(1024)
    real(c_double), target :: rho(486),rdg(324),lambda2(324),signedrho(324)
    integer(c_int8_t), target :: flags(324)
    integer(c_int64_t) :: rho_before(486)
    integer(c_int32_t), parameter :: expected_error(0:5)=[0,4,4,6,7,5],created(0:5)=[2,0,1,2,2,2]
    integer :: i
    integer(c_int) :: status
    logical :: ok
    results=-1; results(20)=0; bits=0; flags_raw=0; stats_raw=0; contexts=c_null_ptr
    do i=1,7
      call nci_bench_reset(records(i))
    end do
    call nci_bench_reset(zero_record)
    body: block
      if (mode<0.or.mode>5) exit body
      rho=0.5_c_double; rho_before=transfer(rho,rho_before)
      rdg=-123; lambda2=-124; signedrho=-125; flags=-1
      stats%total_points=-1; stats%valid_points=-1; stats%invalid_points=-1
      stats%numeric_failures=-1; stats%bit_counts=-1
      options%abi_version=1; options%struct_bytes=int(c_sizeof(options),c_int32_t)
      options%backend=NCI_OPENACC; options%output_mode=NCI_FULL; options%omp_threads=1; options%reserved=0
      options%rho_min=1.0e-8_c_double; options%negative_tolerance=0
      tile%abi_version=1; tile%struct_bytes=int(c_sizeof(tile),c_int32_t)
      tile%global_n=9; tile%tile_start=0; tile%tile_count=[4_c_int64_t,9_c_int64_t,9_c_int64_t]
      tile%input_origin=0; tile%input_shape=[6_c_int64_t,9_c_int64_t,9_c_int64_t]
      tile%input_strides=[81_c_int64_t,9_c_int64_t,1_c_int64_t]
      tile%j_inv=[1.0_c_double,0.0_c_double,0.0_c_double,0.0_c_double,1.0_c_double, &
        0.0_c_double,0.0_c_double,0.0_c_double,1.0_c_double]
      tile%periodic=0; tile%reserved=0
      tile%rho_capacity=486; tile%field_capacity=324; tile%flags_capacity=324
      tile%grad_capacity=0; tile%hess_capacity=0
      do i=1,2
        results(i+1)=nci_context_create_v1(c_loc(options),c_loc(contexts(i)),c_loc(error),size(error,kind=c_size_t))
        if (results(i+1)/=NCI_OK) exit body
      end do
      call evaluate_capture(1,1,1,results(6),ok)
      if (.not.ok.or.results(6)/=NCI_OK.or..not.valid_record(records(1),NCI_OPENACC,1_c_int32_t)) exit body
      if (mode==0) then
        ! Public errbuf guard precedes live-context entry: it must preserve the
        ! historical record. A failed ABI call is never a current timing sample.
        results(20)=results(20)+1
        results(21)=nci_eval_tile_f64_v1(contexts(1),c_loc(tile),c_loc(rho(1)),c_loc(rdg(1)),c_loc(signedrho(1)), &
          c_loc(lambda2(1)),c_null_ptr,c_null_ptr,c_loc(flags(1)),c_loc(stats),c_null_ptr,1_c_size_t)
        call nci_bench_get_timing(contexts(1),records(7),ok)
        call capture_outputs(6)
        results(22)=merge(0,1,ok.and.same_record(records(1),records(7)))
        results(23)=merge(0,1,snapshot_equal(6))
        results(24)=merge(1,0,results(21)==NCI_OK)
        results(15)=merge(0,1,all(transfer(rho,rho_before)==rho_before))
        if (results(21)/=NCI_INVALID_ARGUMENT.or.results(22)/=0.or.results(23)/=0.or. &
            results(24)/=0.or.results(15)/=0) exit body
        rejected_sample=benchmark_report()
        rejected_sample%expected_n=9; rejected_sample%expected_threads=1; rejected_sample%expected_backend=NCI_OPENACC
        call benchmark_observe(rejected_sample,0_c_int64_t,4_c_int64_t,results(21), &
          10_c_int64_t,20_c_int64_t,records(7),ok,.false.)
        results(25)=merge(0,1,.not.rejected_sample%timing_valid.and.rejected_sample%count==1.and. &
          .not.rejected_sample%slabs(1)%sample_eligible.and.rejected_sample%eval_seconds==0.and. &
          rejected_sample%kernel_seconds==0.and.rejected_sample%device_seconds==0)
        if (results(25)/=0) exit body
        call nci_bench_test_event_fault(contexts(1),1_c_int32_t,ok)
        results(4)=merge(0,1,ok)
        if (.not.ok) exit body
      end if
      call nci_bench_test_event_fault(contexts(1),mode,ok)
      results(5)=merge(0,1,ok)
      if (.not.ok) exit body
      ! Common descriptor refusal must not consume A's pending fault or write.
      tile%reserved=1
      call evaluate_capture(1,2,2,results(7),ok)
      tile%reserved=0
      results(14)=merge(0,1,all(bits(:,2)==bits(:,1)).and.all(flags_raw(:,2)==flags_raw(:,1)).and. &
        all(stats_raw(:,2)==stats_raw(:,1)))
      if (.not.ok.or.results(7)/=NCI_INVALID_ARGUMENT.or..not.same_record(records(2),zero_record).or. &
          results(14)/=0) exit body
      call evaluate_capture(2,3,3,results(8),ok)
      if (.not.ok.or.results(8)/=NCI_OK.or..not.valid_record(records(3),NCI_OPENACC,1_c_int32_t)) exit body
      results(13)=merge(0,1,snapshot_equal(3))
      if (results(13)/=0) exit body
      call evaluate_capture(1,4,4,results(9),ok)
      if (.not.ok.or.results(9)/=NCI_OK) exit body
      if (mode==0) then
        ok=valid_record(records(4),NCI_OPENACC,1_c_int32_t)
      else
        ok=records(4)%state==-1.and.records(4)%timing_error==expected_error(mode)
        ok=ok.and.records(4)%events_created==created(mode).and.records(4)%events_destroyed==created(mode)
        ok=ok.and.records(4)%kernel_count==1.and.records(4)%async_queue==1.and.records(4)%observed_threads==0
        ok=ok.and.records(4)%reserved==0.and.records(4)%kernel_seconds==0
        ok=ok.and.ieee_is_finite(records(4)%device_seconds).and.records(4)%device_seconds>=0
        if (mode==5) ok=ok.and.records(4)%stream_handle==0
        if (mode/=5) ok=ok.and.records(4)%stream_handle/=0
      end if
      results(18)=merge(0,1,ok)
      if (.not.ok) exit body
      results(13)=merge(0,1,snapshot_equal(4))
      if (results(13)/=0.or.results(15)/=0) exit body
      call nci_bench_get_timing(contexts(2),records(6),ok)
      results(16)=merge(0,1,ok)
      results(17)=merge(0,1,ok.and.same_record(records(3),records(6)))
      if (results(16)/=0.or.results(17)/=0) exit body
      ! Recovery is predeclared qualification, never a retry/formal sample.
      call evaluate_capture(1,5,5,results(10),ok)
      if (.not.ok.or.results(10)/=NCI_OK.or..not.valid_record(records(5),NCI_OPENACC,1_c_int32_t)) exit body
      results(19)=0
      call nci_bench_get_timing(contexts(2),records(6),ok)
      results(16)=merge(0,1,ok)
      results(17)=merge(0,1,ok.and.same_record(records(3),records(6)))
      if (results(16)/=0.or.results(17)/=0) exit body
      results(13)=0
      do i=2,5
        if (any(bits(:,i)/=bits(:,1)).or.any(flags_raw(:,i)/=flags_raw(:,1)).or. &
            any(stats_raw(:,i)/=stats_raw(:,1))) results(13)=1
      end do
      results(15)=merge(0,1,all(transfer(rho,rho_before)==rho_before))
      if (results(13)/=0.or.results(15)/=0) exit body
      results(1)=0
    end block body
    do i=1,2
      if (.not.c_associated(contexts(i))) cycle
      status=nci_context_destroy_v1(contexts(i),c_loc(error),size(error,kind=c_size_t))
      contexts(i)=c_null_ptr; results(i+10)=status
      if (status/=NCI_OK) results(1)=-1
    end do
  contains
    subroutine evaluate_capture(index,snapshot,record_slot,rc,query_ok)
      integer, intent(in) :: index,snapshot,record_slot
      integer(c_int32_t), intent(out) :: rc
      logical, intent(out) :: query_ok
      error=c_null_char
      results(20)=results(20)+1
      rc=nci_eval_tile_f64_v1(contexts(index),c_loc(tile),c_loc(rho(1)),c_loc(rdg(1)),c_loc(signedrho(1)), &
        c_loc(lambda2(1)),c_null_ptr,c_null_ptr,c_loc(flags(1)),c_loc(stats),c_loc(error),size(error,kind=c_size_t))
      call nci_bench_get_timing(contexts(index),records(record_slot),query_ok)
      results(16)=merge(0,1,query_ok)
      call capture_outputs(snapshot)
      results(15)=merge(0,1,all(transfer(rho,rho_before)==rho_before))
      query_ok=query_ok.and.results(15)==0
    end subroutine
    subroutine capture_outputs(snapshot)
      integer, intent(in) :: snapshot
      bits(1:324,snapshot)=transfer(rdg,bits(1:324,snapshot))
      bits(325:648,snapshot)=transfer(lambda2,bits(325:648,snapshot))
      bits(649:972,snapshot)=transfer(signedrho,bits(649:972,snapshot))
      flags_raw(:,snapshot)=flags; stats_raw(:,snapshot)=transfer(stats,stats_raw(:,snapshot))
    end subroutine
    logical function snapshot_equal(index) result(equal)
      integer, intent(in) :: index
      equal=all(bits(:,index)==bits(:,1)).and.all(flags_raw(:,index)==flags_raw(:,1)).and. &
        all(stats_raw(:,index)==stats_raw(:,1))
    end function
  end subroutine
end module
