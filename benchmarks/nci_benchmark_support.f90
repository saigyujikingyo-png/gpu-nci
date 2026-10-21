! Private, opt-in measurement protocol. No public BIND(C) timing ABI.
module nci_benchmark_support
  use, intrinsic :: iso_c_binding
  use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
  use nci_bench_types, only: nci_bench_record
  implicit none
  private
  public :: benchmark_report, benchmark_observe, benchmark_sync_results
  public :: benchmark_write_report, benchmark_mkdir, benchmark_ack
  integer, parameter :: max_slabs=96
  type :: slab_measurement
    integer(c_int64_t) :: start=0, planes=0, eval_start_ns=-1, eval_stop_ns=-1
    integer(c_int) :: abi_status=-1
    logical :: getter_ok=.false.
    logical :: sample_eligible=.false.
    type(nci_bench_record) :: record
  end type
  type :: benchmark_report
    integer :: expected_n=0, expected_threads=0, expected_backend=-1, count=0
    integer(c_int64_t) :: e2e_start_ns=-1
    real(c_double) :: e2e_seconds=-1, eval_seconds=0, kernel_seconds=0, device_seconds=0
    logical :: timing_valid=.true., complete=.false.
    type(slab_measurement) :: slabs(max_slabs)
  end type
  interface
    integer(c_int) function sync_results(path) bind(C,name='nci_benchmark_sync_results')
      import :: c_int,c_char
      character(c_char), intent(in) :: path(*)
    end function
    integer(c_int) function sync_report(path) bind(C,name='nci_benchmark_sync_report')
      import :: c_int,c_char
      character(c_char), intent(in) :: path(*)
    end function
    integer(c_int) function make_directory(path) bind(C,name='nci_benchmark_mkdir')
      import :: c_int,c_char
      character(c_char), intent(in) :: path(*)
    end function
    integer(c_int) function write_ack() bind(C,name='nci_benchmark_ack')
      import :: c_int
    end function
  end interface
contains
  integer function benchmark_sync_results(directory) result(rc)
    character(*), intent(in) :: directory
    rc=sync_results(directory//c_null_char)
  end function

  integer function benchmark_mkdir(directory) result(rc)
    character(*), intent(in) :: directory
    rc=make_directory(directory//c_null_char)
  end function

  integer function benchmark_ack() result(rc)
    rc=write_ack()
  end function

  subroutine benchmark_observe(report,start,planes,abi_status,begin_ns,end_ns,record,getter_ok,sample_eligible)
    type(benchmark_report), intent(inout) :: report
    integer(c_int64_t), intent(in) :: start,planes,begin_ns,end_ns
    integer(c_int), intent(in) :: abi_status
    type(nci_bench_record), intent(in) :: record
    logical, intent(in) :: getter_ok,sample_eligible
    integer :: i
    logical :: valid
    if (report%count>=max_slabs) then
      report%timing_valid=.false.; return
    end if
    report%count=report%count+1; i=report%count
    report%slabs(i)%start=start; report%slabs(i)%planes=planes
    report%slabs(i)%abi_status=abi_status; report%slabs(i)%getter_ok=getter_ok
    report%slabs(i)%sample_eligible=sample_eligible
    report%slabs(i)%eval_start_ns=begin_ns; report%slabs(i)%eval_stop_ns=end_ns
    report%slabs(i)%record=record
    valid=sample_eligible.and.getter_ok.and.begin_ns>=0.and.end_ns>=begin_ns
    valid=valid.and.record%state==1.and.record%timing_error==0
    valid=valid.and.record%reserved==0
    valid=valid.and.ieee_is_finite(record%kernel_seconds).and.ieee_is_finite(record%device_seconds)
    valid=valid.and.record%kernel_seconds>=0.and.record%device_seconds>=0
    if (report%expected_backend==0) then
      valid=valid.and.record%observed_threads==report%expected_threads.and.record%kernel_count==1
      valid=valid.and.record%events_created==0.and.record%events_destroyed==0
      valid=valid.and.record%async_queue==0.and.record%stream_handle==0
      valid=valid.and.record%device_seconds==record%kernel_seconds
    else
      valid=valid.and.record%observed_threads==0.and.record%kernel_count==1
      valid=valid.and.record%events_created==2.and.record%events_destroyed==2
      valid=valid.and.record%async_queue==1.and.record%stream_handle/=0
      ! A long launch invalidates this sample and stops all later evaluations.
      valid=valid.and.record%kernel_seconds<=0.5_c_double
    end if
    report%timing_valid=report%timing_valid.and.valid
    if (.not.valid) return ! Preserve raw failure; never sum an ineligible/stale record.
    if (begin_ns>=0.and.end_ns>=begin_ns) &
      report%eval_seconds=report%eval_seconds+real(end_ns-begin_ns,c_double)*1.0e-9_c_double
    if (ieee_is_finite(record%kernel_seconds)) report%kernel_seconds=report%kernel_seconds+record%kernel_seconds
    if (ieee_is_finite(record%device_seconds)) report%device_seconds=report%device_seconds+record%device_seconds
  end subroutine

  function integer_text(value) result(text)
    integer(c_int64_t), intent(in) :: value
    character(:), allocatable :: text
    character(40) :: buffer
    write(buffer,'(i0)') value
    text=trim(buffer)
  end function

  function real_text(value) result(text)
    real(c_double), intent(in) :: value
    character(:), allocatable :: text
    character(40) :: buffer
    text='null'
    if (.not.ieee_is_finite(value)) return
    write(buffer,'(es25.17e3)') value
    text=trim(adjustl(buffer))
  end function

  function logical_text(value) result(text)
    logical, intent(in) :: value
    character(:), allocatable :: text
    text='false'
    if (value) text='true'
  end function

  subroutine benchmark_write_report(directory,label,report,ios)
    character(*), intent(in) :: directory,label
    type(benchmark_report), intent(in) :: report
    integer, intent(out) :: ios
    type(nci_bench_record) :: r
    character(:), allocatable :: text
    integer :: unit,close_ios,i
    ! The complete bounded slab buffer is emitted after Te2e, never inside it.
    open(newunit=unit,file=directory//'/timing.json',status='new',action='write',iostat=ios)
    if (ios/=0) return
    text='{"protocol_version":1,"label":"'//label//'","complete":'//logical_text(report%complete)// &
      ',"timing_valid":'//logical_text(report%timing_valid)//',"cache_state":"uncontrolled"'// &
      ',"timing_report_io":"excluded_from_te2e","te2e_seconds":'//real_text(report%e2e_seconds)// &
      ',"teval_seconds":'//real_text(report%eval_seconds)//',"kernel_seconds":'//real_text(report%kernel_seconds)// &
      ',"device_seconds":'//real_text(report%device_seconds)//',"slabs":['
    write(unit,'(a)',iostat=ios) text
    do i=1,report%count
      if (ios/=0) exit
      r=report%slabs(i)%record
      text='{"start":'//integer_text(report%slabs(i)%start)//',"planes":'//integer_text(report%slabs(i)%planes)// &
        ',"abi_status":'//integer_text(int(report%slabs(i)%abi_status,c_int64_t))// &
        ',"getter_ok":'//logical_text(report%slabs(i)%getter_ok)// &
        ',"sample_eligible":'//logical_text(report%slabs(i)%sample_eligible)// &
        ',"eval_start_ns":'//integer_text(report%slabs(i)%eval_start_ns)// &
        ',"eval_stop_ns":'//integer_text(report%slabs(i)%eval_stop_ns)// &
        ',"state":'//integer_text(int(r%state,c_int64_t))// &
        ',"timing_error":'//integer_text(int(r%timing_error,c_int64_t))// &
        ',"observed_threads":'//integer_text(int(r%observed_threads,c_int64_t))// &
        ',"kernel_count":'//integer_text(int(r%kernel_count,c_int64_t))// &
        ',"events_created":'//integer_text(int(r%events_created,c_int64_t))// &
        ',"events_destroyed":'//integer_text(int(r%events_destroyed,c_int64_t))// &
        ',"async_queue":'//integer_text(int(r%async_queue,c_int64_t))// &
        ',"reserved":'//integer_text(int(r%reserved,c_int64_t))// &
        ',"stream_handle":'//integer_text(r%stream_handle)// &
        ',"kernel_seconds":'//real_text(r%kernel_seconds)//',"device_seconds":'//real_text(r%device_seconds)//'}'
      if (i<report%count) text=text//','
      write(unit,'(a)',iostat=ios) text
    end do
    if (ios==0) write(unit,'(a)',iostat=ios) ']}'
    close(unit,iostat=close_ios)
    if (ios==0) ios=close_ios
    if (ios==0) ios=sync_report(directory//c_null_char)
  end subroutine
end module
