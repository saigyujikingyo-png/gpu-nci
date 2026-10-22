program nci_benchmark
  use, intrinsic :: iso_c_binding, only: c_int
  use, intrinsic :: iso_fortran_env, only: error_unit
  use nci_driver_support, only: argument, execute_run, emit_build_info
  use nci_benchmark_support
  implicit none
  type(benchmark_report) :: report
  integer :: n,threads,backend,rc,ios,i
  logical :: qualification
  character(:), allocatable :: directory,label,text
  character(24), parameter :: labels(10)=[character(24) :: &
    'fresh_process_first_run','warmup1','warmup2','formal1','formal2','formal3','formal4','formal5','formal6','formal7']
  interface
    subroutine process_exit(status) bind(C,name='exit')
      import :: c_int
      integer(c_int), value :: status
    end subroutine
  end interface
  if (command_argument_count()==1) then
    if (argument(1)=='--build-info') then
      rc=emit_build_info(); call process_exit(int(rc,c_int))
    end if
  end if
  qualification=.false.
  if (command_argument_count()==7) qualification=argument(7)=='--qualification'
  if (command_argument_count()/=6.and..not.qualification) &
    call fail('usage: benchmark INPUT SETTINGS NEW_CONFIG_DIR N THREADS BACKEND [--qualification]')
  text=argument(4); read(text,*,iostat=ios) n
  if (ios/=0) call fail('Invalid grid size')
  if (qualification) then
    if (n<5.or.n>384) call fail('Qualification grid is outside the bounded range')
  else
    if (n/=128.and.n/=256.and.n/=384) call fail('Grid is outside the fixed matrix')
  end if
  text=argument(5); read(text,*,iostat=ios) threads
  if (ios/=0) call fail('Invalid thread count')
  text=argument(6); read(text,*,iostat=ios) backend
  if (ios/=0) call fail('Invalid backend')
  if (backend==0) then
    if (threads/=1.and.threads/=4.and.threads/=8.and.threads/=16) call fail('CPU team is outside the matrix')
  else if (backend==1) then
    if (threads/=1) call fail('GPU host team must be one')
  else
    call fail('Backend is outside the matrix')
  end if
  ! The parent exclusively created NEW_CONFIG_DIR. Each complete workflow has
  ! a new density reader, context and FULL field streams, using the same paths.
  do i=1,10
    report=benchmark_report()
    report%expected_n=n; report%expected_threads=threads; report%expected_backend=backend
    label=trim(labels(i)); directory=argument(3)//'/'//label
    if (benchmark_mkdir(directory)/=0) call fail('Cannot exclusively create repetition directory')
    call execute_run(argument(1),argument(2),directory,rc,report)
    call benchmark_write_report(directory,label,report,ios)
    if (ios/=0) call fail('Cannot persist timing report; no further calls')
    if (rc/=0.or..not.report%complete.or..not.report%timing_valid) call fail('Incomplete benchmark; no further calls')
    if (report%count/=(n+3)/4) call fail('Incomplete slab record sequence')
    if (i==1) then
      if (benchmark_ack()/=0) call fail('Cannot send durable first-result ACK')
    end if
  end do
  call process_exit(0_c_int)
contains
  subroutine fail(message)
    character(*), intent(in) :: message
    write(error_unit,'(a)') message
    call process_exit(1_c_int)
  end subroutine
end program
