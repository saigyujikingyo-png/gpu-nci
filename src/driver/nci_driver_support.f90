! Original thin adapter. Numerical work is only through the public C ABI.
module nci_driver_support
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: int64, error_unit, output_unit
  use, intrinsic :: ieee_arithmetic
  use nci_abi
  use nci_cube_input
  use nci_driver_build
  use nci_driver_backend
#ifdef NCI_BENCHMARK
  use nci_bench_types, only: nci_bench_record, nci_bench_clock_ns
  use nci_capi, only: nci_bench_get_timing
  use nci_benchmark_support, only: benchmark_report, benchmark_observe, benchmark_sync_results
#endif
  implicit none
  private
  public :: execute_run, emit_build_info, argument
  type :: field_streams
    integer :: unit(6)=0
    logical :: opened(6)=.false.
  end type
  type :: openacc_memory_plan
    ! The reader adds density, atoms and its 8192-byte scanner exactly once.
    integer(c_int64_t) :: reader_fixed_bytes=0, host_bytes=0, reader_atom_bytes=0
    integer(c_int64_t) :: device_array_bytes=0, host_fixed_common_bytes=0
    integer(c_int64_t) :: host_fixed_openacc_bytes=65536, device_static_bytes=288, launch_parameter_bytes=272
  end type
  interface
    function context_create(options, context, error, length) bind(C,name='nci_context_create_v1') result(rc)
      import :: c_ptr, c_size_t, c_int
      type(c_ptr), value :: options, context, error
      integer(c_size_t), value :: length
      integer(c_int) :: rc
    end function
    function evaluate(context,tile,rho,rdg,signedrho,lambda2,grad,hess,flags,stats,error,length) &
        bind(C,name='nci_eval_tile_f64_v1') result(rc)
      import :: c_ptr, c_size_t, c_int
      type(c_ptr), value :: context,tile,rho,rdg,signedrho,lambda2,grad,hess,flags,stats,error
      integer(c_size_t), value :: length
      integer(c_int) :: rc
    end function
    function context_destroy(context,error,length) bind(C,name='nci_context_destroy_v1') result(rc)
      import :: c_ptr, c_size_t, c_int
      type(c_ptr), value :: context,error
      integer(c_size_t), value :: length
      integer(c_int) :: rc
    end function
  end interface
  interface write_field
    module procedure write_scalar_field, write_diagnostic_field, write_flags
  end interface
contains
  function argument(index) result(value)
    integer, intent(in) :: index
    character(:), allocatable :: value
    integer :: length, ios
    call get_command_argument(index,length=length,status=ios)
    if (ios/=0) then
      value=''; return
    end if
    allocate(character(length)::value,stat=ios)
    if (ios/=0) then
      value=''; return
    end if
    call get_command_argument(index,value=value,status=ios)
    if (ios/=0) value=''
  end function

  function json_string(text) result(value)
    character(*), intent(in) :: text
    character(:), allocatable :: value
    character(6) :: escape
    integer :: i, code
    value='"'
    do i=1,len(text)
      code=iachar(text(i:i))
      select case(code)
      case(34,92)
        value=value//achar(92)//text(i:i)
      case(0:31)
        write(escape,'(a,z4.4)') achar(92)//'u',code
        value=value//escape
      case default
        value=value//text(i:i)
      end select
    end do
    value=value//'"'
  end function

  function decimal(value) result(text)
    integer(c_int64_t), intent(in) :: value
    character(:), allocatable :: text
    character(32) :: buffer
    write(buffer,'(i0)') value
    text=trim(buffer)
  end function

  function c_message(error) result(text)
    character(c_char), intent(in) :: error(:)
    character(:), allocatable :: text
    integer :: i
    text=''
    do i=1,size(error)
      if (error(i)==c_null_char) exit
      text=text//error(i)
    end do
  end function

  integer function emit_build_info() result(rc)
    integer :: ios
    rc=1
    write(output_unit,'(a)',iostat=ios) '{"protocol_version":1,"source_revision":'//json_string(build_revision())// &
      ',"compiler_id":'//json_string(build_compiler_id())// &
      ',"compiler_version":'//json_string(build_compiler_version())// &
      ',"build_type":'//json_string(build_type())//',"fp_policy":'//json_string(build_fp_policy())// &
      ',"backend_library":'//json_string(build_backend_library())// &
      ',"supported_backends":'//build_supported_backends()//'}'
    if (ios/=0) return
    flush(output_unit,iostat=ios)
    if (ios==0) rc=0
  end function

  logical function supported_representation()
    integer(c_int8_t) :: bytes(4)
    supported_representation=.false.
    if (storage_size(0.0_c_double)/=64.or.storage_size(0_c_int8_t)/=8) return
    if (radix(0.0_c_double)/=2.or.digits(0.0_c_double)/=53) return
    if (.not.ieee_support_datatype(0.0_c_double)) return
    bytes=transfer(1_c_int32_t,bytes)
    if (any(bytes/=[1_c_int8_t,0_c_int8_t,0_c_int8_t,0_c_int8_t])) return
    supported_representation=.true.
  end function

  subroutine native_receipt(directory,stage,message,complete,abi_status,npoints,stats,stats_ready,backend,plan,ios)
    character(*), intent(in) :: directory,stage,message
    logical, intent(in) :: complete,stats_ready
    integer, intent(in) :: abi_status,backend
    integer(c_int64_t), intent(in) :: npoints
    type(nci_tile_stats_v1), intent(in) :: stats
    type(openacc_memory_plan), intent(in) :: plan
    integer, intent(out) :: ios
    integer :: unit, close_ios, i
    character(:), allocatable :: text, state, abi
    state='failed'
    if (complete) state='completed'
    abi='null'
    if (abi_status>=0) abi=decimal(int(abi_status,c_int64_t))
    text='{"protocol_version":1,"state":'//json_string(state)//',"stage":'//json_string(stage)// &
      ',"message":'//json_string(message)//',"abi_status":'//abi//',"npoints":'//decimal(npoints)//',"stats":'
    if (stats_ready) then
      text=text//'{"total":'//decimal(stats%total_points)//',"valid":'//decimal(stats%valid_points)// &
        ',"invalid":'//decimal(stats%invalid_points)//',"numeric_failures":'//decimal(stats%numeric_failures)// &
        ',"bit_counts":['
      do i=1,7
        if (i>1) text=text//','
        text=text//decimal(stats%bit_counts(i))
      end do
      text=text//']}'
    else
      text=text//'null'
    end if
    if (complete.and.backend==NCI_OPENACC) then
      text=text//',"backend":"openacc","memory_plan":{"host_bytes":'//decimal(plan%host_bytes)// &
        ',"reader_atom_bytes":'//decimal(plan%reader_atom_bytes)// &
        ',"device_array_bytes":'//decimal(plan%device_array_bytes)// &
        ',"host_fixed_common_bytes":'//decimal(plan%host_fixed_common_bytes)// &
        ',"host_fixed_openacc_bytes":'//decimal(plan%host_fixed_openacc_bytes)// &
        ',"device_static_bytes":'//decimal(plan%device_static_bytes)// &
        ',"launch_parameter_bytes":'//decimal(plan%launch_parameter_bytes)//'}'
    end if
    text=text//'}'
    open(newunit=unit,file=directory//'/native.json',status='new',action='write',iostat=ios)
    if (ios/=0) return
    write(unit,'(a)',iostat=ios) text
    close(unit,iostat=close_ios)
    if (ios==0) ios=close_ios
  end subroutine

  subroutine open_streams(streams,directory,diagnostic,ios)
    type(field_streams), intent(inout) :: streams
    character(*), intent(in) :: directory
    logical, intent(in) :: diagnostic
    integer, intent(out) :: ios
    character(16), parameter :: names(6)=[character(16) :: &
      'rdg.f64','lambda2.f64','signedrho.f64','flags.u8','grad.f64','hess.f64']
    integer :: i,count
    count=4
    if (diagnostic) count=6
    ios=0
    do i=1,count
      open(newunit=streams%unit(i),file=directory//'/'//trim(names(i)),status='new', &
        access='stream',form='unformatted',action='write',iostat=ios)
      if (ios/=0) return
      streams%opened(i)=.true.
    end do
  end subroutine

  subroutine close_streams(streams,ios)
    type(field_streams), intent(inout) :: streams
    integer, intent(out) :: ios
    integer :: i,close_ios
    ios=0
    do i=1,6
      if (.not.streams%opened(i)) cycle
      close(streams%unit(i),iostat=close_ios)
      streams%opened(i)=.false.
      if (ios==0) ios=close_ios
    end do
  end subroutine

  subroutine write_scalar_field(unit,values,ios)
    integer, intent(in) :: unit
    real(c_double), intent(in) :: values(:)
    integer, intent(out) :: ios
    integer(c_int64_t) :: first,last,used
    integer(c_int8_t) :: bytes(4096)
    ios=0
    ! One-byte stream elements cannot be endian-converted by compiler runtime
    ! overrides. The host representation was checked before evaluation.
    do first=1,size(values,kind=c_int64_t),512_c_int64_t
      last=min(first+511_c_int64_t,size(values,kind=c_int64_t))
      used=8*(last-first+1)
      bytes(:used)=transfer(values(first:last),bytes,int(used))
      write(unit,iostat=ios) bytes(:used)
      if (ios/=0) exit
    end do
  end subroutine

  subroutine write_diagnostic_field(unit,values,ios)
    integer, intent(in) :: unit
    real(c_double), intent(in) :: values(:,:)
    integer, intent(out) :: ios
    integer(c_int64_t) :: first,last,used,chunk
    integer(c_int8_t) :: bytes(4096)
    ios=0
    chunk=4096_c_int64_t/(8*size(values,1,kind=c_int64_t))
    do first=1,size(values,2,kind=c_int64_t),chunk
      last=min(first+chunk-1,size(values,2,kind=c_int64_t))
      used=8*size(values,1,kind=c_int64_t)*(last-first+1)
      bytes(:used)=transfer(values(:,first:last),bytes,int(used))
      write(unit,iostat=ios) bytes(:used)
      if (ios/=0) exit
    end do
  end subroutine

  subroutine write_flags(unit,values,ios)
    integer, intent(in) :: unit
    integer(c_int8_t), intent(in) :: values(:)
    integer, intent(out) :: ios
    write(unit,iostat=ios) values
  end subroutine

  function checked_product(values,ok) result(value)
    integer(c_int64_t), intent(in) :: values(:)
    logical, intent(out) :: ok
    integer(c_int64_t) :: value
    integer :: i
    ok=.false.; value=1
    do i=1,size(values)
      if (values(i)<0) return
      if (value/=0) then
        if (values(i)>huge(value)/value) return
      end if
      value=value*values(i)
    end do
    ok=.true.
  end function

  function checked_sum(values,ok) result(value)
    integer(c_int64_t), intent(in) :: values(:)
    logical, intent(out) :: ok
    integer(c_int64_t) :: value
    integer :: i
    ok=.false.; value=0
    do i=1,size(values)
      if (values(i)<0) return
      if (values(i)>huge(value)-value) return
      value=value+values(i)
    end do
    ok=.true.
  end function

  subroutine openacc_tile_bytes(shape,plane,start,width,full_grid,periodic_x,diagnostic,bytes,ok)
    integer(c_int64_t), intent(in) :: shape(3),plane,start,width
    logical, intent(in) :: full_grid,periodic_x,diagnostic
    integer(c_int64_t), intent(out) :: bytes(9)
    logical, intent(out) :: ok
    integer(c_int64_t) :: input_width,nin,nout,field_bytes
    bytes=0; ok=.false.
    if (full_grid) then
      input_width=shape(1) ! A full grid has no caller halo, even when periodic.
    else if (periodic_x) then
      input_width=checked_sum([width,4_c_int64_t],ok)
      if (.not.ok) return
    else
      input_width=checked_sum([width,min(2_c_int64_t,start), &
        min(2_c_int64_t,shape(1)-start-width)],ok)
      if (.not.ok) return
    end if
    nin=checked_product([input_width,plane],ok)
    if (.not.ok) return
    nout=checked_product([width,plane],ok)
    if (.not.ok) return
    bytes(1)=checked_product([8_c_int64_t,nin],ok)
    if (.not.ok) return
    bytes(2)=checked_product([40_c_int64_t,width],ok)
    if (.not.ok) return
    bytes(3)=checked_product([40_c_int64_t,shape(2)],ok)
    if (.not.ok) return
    bytes(4)=checked_product([40_c_int64_t,shape(3)],ok)
    if (.not.ok) return
    field_bytes=24
    if (diagnostic) field_bytes=96
    bytes(5)=checked_product([field_bytes,nout],ok)
    if (.not.ok) return
    bytes(6)=nout
    bytes(7)=checked_product([4_c_int64_t,nout],ok)
    if (.not.ok) return
    bytes(8:9)=bytes(7)
  end subroutine

  subroutine plan_openacc_memory(shape,periodic_x,layout_mode,bmax,diagnostic,omp_threads,plan,ok,message)
    integer(c_int64_t), intent(in) :: shape(3),bmax
    integer, intent(in) :: periodic_x,layout_mode,omp_threads
    logical, intent(in) :: diagnostic
    type(openacc_memory_plan), intent(out) :: plan
    logical, intent(out) :: ok
    character(:), allocatable, intent(out) :: message
    integer(c_int64_t) :: starts(4),widths(4),objects(9),plane,global_points,full_tiles,tail,left_halo_tile
    integer(c_int64_t) :: tile_bytes,retained_width,slab_bytes,output_count,output_bytes,q,thread_bytes,density_bytes
    integer :: candidates,i
    plan=openacc_memory_plan(); ok=.false.
    message='OpenACC reservation arithmetic exceeds int64'
    plane=checked_product(shape(2:3),ok)
    if (.not.ok) return
    global_points=checked_product(shape,ok)
    if (.not.ok) return
    starts=0; widths=bmax; candidates=1
    if (layout_mode==1) then
      full_tiles=shape(1)/bmax; tail=mod(shape(1),bmax)
      ! ceil(2/B) is 2 for B=1, otherwise 1; no addition to B can overflow.
      left_halo_tile=1
      if (bmax==1) left_halo_tile=2
      starts(2)=checked_product([min(left_halo_tile,full_tiles-1),bmax],ok)
      if (.not.ok) return
      starts(3)=checked_product([full_tiles-1,bmax],ok)
      if (.not.ok) return
      candidates=3
      if (tail/=0) then
        starts(4)=checked_product([full_tiles,bmax],ok)
        if (.not.ok) return
        widths(4)=tail; candidates=4
      end if
    end if
    ! At most four canonical tiles. Only finite-X halo lengths vary among
    ! full-width tiles; the first complete left halo reaches their maximum.
    do i=1,candidates
      if (i>1) then
        if (any(starts(:i-1)==starts(i))) cycle
      end if
      call openacc_tile_bytes(shape,plane,starts(i),widths(i),layout_mode==0,periodic_x==1, &
        diagnostic,objects,ok)
      if (.not.ok) return
      if (any(objects>int(huge(0_c_int32_t),c_int64_t))) then
        message='OpenACC mapped object exceeds INT32_MAX bytes'; ok=.false.; return
      end if
      tile_bytes=checked_sum(objects,ok)
      if (.not.ok) return
      plan%device_array_bytes=max(plan%device_array_bytes,tile_bytes)
    end do
    slab_bytes=0
    if (layout_mode==1) then
      ! Keep the caller allocation B+4, including finite boundary slabs whose
      ! actual input is shorter. Backend arrays above use the actual input.
      retained_width=checked_sum([bmax,4_c_int64_t],ok)
      if (.not.ok) return
      slab_bytes=checked_product([8_c_int64_t,retained_width,plane],ok)
      if (.not.ok) return
    end if
    output_count=checked_product([bmax,plane],ok)
    if (.not.ok) return
    q=25
    if (diagnostic) q=97
    output_bytes=checked_product([q,output_count],ok)
    if (.not.ok) return
    thread_bytes=checked_product([4096_c_int64_t,int(omp_threads,c_int64_t)],ok)
    if (.not.ok) return
    plan%host_fixed_common_bytes=checked_sum([65536_c_int64_t,thread_bytes],ok)
    if (.not.ok) return
    plan%reader_fixed_bytes=checked_sum([output_bytes,slab_bytes,plan%device_array_bytes, &
      plan%host_fixed_common_bytes,plan%host_fixed_openacc_bytes],ok)
    if (.not.ok) return
    density_bytes=checked_product([8_c_int64_t,global_points],ok)
    if (.not.ok) return
    ! This is the atom-free lower bound until the checked reader returns.
    plan%host_bytes=checked_sum([density_bytes,8192_c_int64_t,plan%reader_fixed_bytes],ok)
  end subroutine

  subroutine reset_stats(stats)
    type(nci_tile_stats_v1), intent(out) :: stats
    stats%total_points=0; stats%valid_points=0; stats%invalid_points=0
    stats%numeric_failures=0; stats%bit_counts=0
  end subroutine

  logical function completed_stats(stats,count)
    type(nci_tile_stats_v1), intent(in) :: stats
    integer(c_int64_t), intent(in) :: count
    completed_stats=.false.
    if (stats%total_points/=count) return
    if (stats%valid_points<0.or.stats%valid_points>count) return
    if (stats%invalid_points/=count-stats%valid_points) return
    if (any(stats%bit_counts<0).or.any(stats%bit_counts>count)) return
    if (stats%numeric_failures/=stats%bit_counts(5)) return
    if (any(stats%bit_counts(1:5)>stats%invalid_points)) return
    if (sum(stats%bit_counts(1:5))<stats%invalid_points) return
    if (stats%bit_counts(6)>stats%valid_points.or.stats%bit_counts(7)/=stats%valid_points) return
    completed_stats=.true.
  end function

  logical function completed_invalid_slab(stats,flags)
    type(nci_tile_stats_v1), intent(in) :: stats
    integer(c_int8_t), intent(in) :: flags(:)
    integer(c_int64_t) :: counts(7),p
    integer :: bit
    completed_invalid_slab=.false.; counts=0
    if (stats%valid_points/=0.or.stats%numeric_failures/=0) return
    do p=1,size(flags,kind=c_int64_t)
      if (iand(int(flags(p)),31)==0.or.btest(flags(p),4)) return
      do bit=0,6
        if (btest(flags(p),bit)) counts(bit+1)=counts(bit+1)+1
      end do
    end do
    if (any(counts/=stats%bit_counts)) return
    completed_invalid_slab=.true.
  end function

  logical function aggregate_stats(total,current,global_count) result(ok)
    type(nci_tile_stats_v1), intent(inout) :: total
    type(nci_tile_stats_v1), intent(in) :: current
    integer(c_int64_t), intent(in) :: global_count
    type(nci_tile_stats_v1) :: candidate
    logical :: arithmetic_ok
    candidate=total; ok=.false.
    candidate%total_points=checked_sum([total%total_points,current%total_points],arithmetic_ok)
    if (.not.arithmetic_ok.or.candidate%total_points>global_count) return
    candidate%valid_points=checked_sum([total%valid_points,current%valid_points],arithmetic_ok)
    if (.not.arithmetic_ok) return
    candidate%invalid_points=checked_sum([total%invalid_points,current%invalid_points],arithmetic_ok)
    if (.not.arithmetic_ok) return
    candidate%numeric_failures=checked_sum([total%numeric_failures,current%numeric_failures],arithmetic_ok)
    if (.not.arithmetic_ok) return
    if (any(current%bit_counts>global_count-total%bit_counts)) return
    candidate%bit_counts=total%bit_counts+current%bit_counts
    total=candidate; ok=.true.
  end function

  subroutine execute_run(input_path,settings_path,directory,exit_status &
#ifdef NCI_BENCHMARK
      ,benchmark &
#endif
      )
    character(*), intent(in) :: input_path,settings_path,directory
    integer, intent(out) :: exit_status
#ifdef NCI_BENCHMARK
    type(benchmark_report), optional, intent(inout) :: benchmark
    type(nci_bench_record) :: sample
    integer(c_int64_t) :: eval_start,eval_stop,e2e_stop
    logical :: timing_ok
#endif
    integer :: protocol_version, periodic(3), output_mode, omp_threads,layout_mode,backend
    integer(int64) :: shape(3), memory_budget_bytes, max_points,slab_planes
    real(c_double) :: origin(3),step_vectors(3,3),rho_min,negative_tolerance
    character(128) :: endpoint_convention(3),quantity,spin_convention,density_representation,length_unit,density_unit
    namelist /nci_run/ protocol_version,shape,origin,step_vectors,periodic,endpoint_convention, &
      quantity,spin_convention,density_representation,length_unit,density_unit,output_mode, &
      rho_min,negative_tolerance,omp_threads,memory_budget_bytes,max_points,layout_mode,slab_planes,backend
    type(cube_grid), target :: grid
    type(cube_read_limits) :: limits
    type(cube_metadata) :: metadata
    type(cube_status) :: reader_status
    type(cube_atom) :: atom_size_probe
    type(openacc_memory_plan) :: plan
    type(nci_options_v1), target :: options
    type(nci_tile_v1), target :: tile
    type(nci_tile_stats_v1), target :: stats
    type(nci_tile_stats_v1) :: total_stats
    type(field_streams) :: streams
    type(c_ptr), target :: context
    type(c_ptr) :: grad_ptr,hess_ptr,rho_ptr
    real(c_double), allocatable, target :: rdg(:),signedrho(:),lambda2(:),grad(:,:),hess(:,:)
    real(c_double), allocatable, target :: slab_rho(:)
    integer(c_int8_t), allocatable, target :: flags(:)
    character(c_char), target :: error(1024)
    integer(c_int) :: rc,cleanup_rc
    integer(c_int64_t) :: npoints,declared_points,plane,bmax,max_input,max_output,q,table_bytes
    integer(c_int64_t) :: halo_planes,input_bytes,output_bytes,axis_nodes,s,b,lo,hi,nin,nout,k,gx
    integer :: ios,close_ios,unit,i,a,abi_status
    character(1024) :: io_message,line
    character(:), allocatable :: stage,message
    logical :: complete,stats_ready,arithmetic_ok,computed,continuable
    protocol_version=-1; shape=-1_int64; periodic=-1; output_mode=-1; omp_threads=-1
    memory_budget_bytes=-1_int64; max_points=-1_int64
    layout_mode=0; slab_planes=0_int64; backend=NCI_CPU
    origin=ieee_value(0.0_c_double,ieee_quiet_nan); step_vectors=origin(1)
    rho_min=origin(1); negative_tolerance=origin(1)
    endpoint_convention=''; quantity=''; spin_convention=''; density_representation=''; length_unit=''; density_unit=''
    context=c_null_ptr; grad_ptr=c_null_ptr; hess_ptr=c_null_ptr; rho_ptr=c_null_ptr
    call reset_stats(stats); call reset_stats(total_stats)
    npoints=0; complete=.false.; stats_ready=.false.; abi_status=-1
    stage='settings'; message='Invalid worker settings'; exit_status=1
    io_message=''
    body: block
      open(newunit=unit,file=settings_path,status='old',action='read',iostat=ios,iomsg=io_message)
      if (ios/=0) then
        message='Cannot open namelist: '//trim(io_message); exit body
      end if
      read(unit,nml=nci_run,iostat=ios,iomsg=io_message)
      if (ios==0) then
        do
          read(unit,'(a)',iostat=ios) line
          if (ios/=0) exit
          if (len_trim(line)>0) then
            ios=1; io_message='Unexpected content after nci_run'; exit
          end if
        end do
        if (ios<0) ios=0
      end if
      close(unit,iostat=close_ios)
      if (ios==0) ios=close_ios
      if (ios/=0) then
        message='Invalid namelist: '//trim(io_message); exit body
      end if
      ! Capability checks precede CUBE input, allocation and context creation.
      select case(backend)
      case(NCI_CPU)
      case(NCI_OPENACC)
        if (.not.build_has_openacc) then
          message='Worker does not support the OpenACC backend'; exit body
        end if
      case default
        message='Unsupported worker backend selector'; exit body
      end select
      if (protocol_version/=1.or.any(shape<5).or.memory_budget_bytes<1.or.max_points<1) exit body
      if (output_mode/=0.and.output_mode/=1) exit body
      if (layout_mode/=0.and.layout_mode/=1) exit body
      if (layout_mode==0) then
        if (slab_planes/=0) exit body
      else
        if (slab_planes<1.or.slab_planes>shape(1)) exit body
      end if
      if (omp_threads<1.or.omp_threads>16) exit body
#ifdef NCI_BENCHMARK
      if (present(benchmark)) then
        stage='benchmark_settings'; message='Settings differ from the frozen benchmark configuration'
        if (any(shape/=benchmark%expected_n).or.omp_threads/=benchmark%expected_threads) exit body
        if (backend/=benchmark%expected_backend.or.output_mode/=0.or.layout_mode/=1.or.slab_planes/=4) exit body
        if (any(periodic/=0).or.rho_min/=1.0e-8_c_double.or.negative_tolerance/=0.0_c_double) exit body
        if (backend==NCI_OPENACC.and.omp_threads/=1) exit body
      end if
#endif
      if (.not.all(ieee_is_finite(origin)).or..not.all(ieee_is_finite(step_vectors))) exit body
      if (.not.ieee_is_finite(rho_min).or..not.ieee_is_finite(negative_tolerance)) exit body
      if (rho_min<=0.or.negative_tolerance<0) exit body
      declared_points=1_c_int64_t
      do i=1,3
        if (declared_points>huge(declared_points)/shape(i)) then
          message='Declared shape product exceeds int64'; exit body
        end if
        declared_points=declared_points*shape(i)
      end do
      if (declared_points>max_points) then
        message='Declared shape exceeds max_points'; exit body
      end if
      if (declared_points>huge(declared_points)/48_int64) then
        message='Global ABI byte extent exceeds int64'; exit body
      end if
      stage='representation'
      if (.not.supported_representation()) then
        message='Little-endian IEEE binary64 and 8-bit flags required'; exit body
      end if
      stage='input'
      limits%max_bytes=memory_budget_bytes; limits%max_points=max_points
      limits%reserve_bytes_per_point=25_int64
      if (output_mode==1) limits%reserve_bytes_per_point=97_int64
      limits%reserve_bytes_per_axis_node=40_int64
      limits%reserve_fixed_bytes=65536_int64+4096_int64*omp_threads
      q=limits%reserve_bytes_per_point
      plane=checked_product(shape(2:3),arithmetic_ok)
      if (.not.arithmetic_ok) exit body
      bmax=shape(1); max_output=declared_points; max_input=0
      if (layout_mode==1) then
        stage='memory'; message='Slab reservation arithmetic exceeds int64'
        bmax=slab_planes
        halo_planes=checked_sum([bmax,4_int64],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        max_input=checked_product([halo_planes,plane],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        max_output=checked_product([bmax,plane],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        input_bytes=checked_product([8_int64,max_input],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        output_bytes=checked_product([q,max_output],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        axis_nodes=checked_sum([bmax,shape(2),shape(3)],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        table_bytes=checked_product([40_int64,axis_nodes],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        limits%reserve_fixed_bytes=checked_sum([input_bytes,output_bytes,table_bytes, &
          limits%reserve_fixed_bytes],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        limits%reserve_bytes_per_point=0; limits%reserve_bytes_per_axis_node=0
      end if
      if (backend==NCI_OPENACC) then
        stage='memory'
        if (any(periodic<0).or.any(periodic>1)) then
          message='Invalid OpenACC periodic settings'; exit body
        end if
        call plan_openacc_memory(shape,periodic(1),layout_mode,bmax,output_mode==1,omp_threads,plan,arithmetic_ok,message)
        if (.not.arithmetic_ok) exit body
        if (plan%host_bytes>memory_budget_bytes) then
          message='OpenACC host reservation exceeds memory budget'; exit body
        end if
        limits%reserve_fixed_bytes=plan%reader_fixed_bytes
        limits%reserve_bytes_per_point=0; limits%reserve_bytes_per_axis_node=0
      end if
      stage='input'
#ifdef NCI_BENCHMARK
      if (present(benchmark)) then
        benchmark%e2e_start_ns=nci_bench_clock_ns()
        if (benchmark%e2e_start_ns<0) then
          stage='timing'; message='Monotonic clock failed before input open'; exit body
        end if
      end if
#endif
      call read_cube(input_path,grid,reader_status,limits)
      if (reader_status%code/=CUBE_OK) then
        message='CUBE code '//decimal(int(reader_status%code,c_int64_t))//': '//trim(reader_status%message)
        if (reader_status%code==CUBE_MEMORY_LIMIT.or.reader_status%code==CUBE_ALLOCATION) stage='memory'
        if (reader_status%code==CUBE_IO_ERROR) stage='io'
        exit body
      end if
      stage='geometry'
      if (any(grid%shape/=shape).or.any(grid%origin/=origin).or.any(grid%j/=step_vectors)) then
        message='CUBE geometry differs from parsed binary64 declarations'; exit body
      end if
      if (backend==NCI_OPENACC) then
        stage='memory'; message='OpenACC atom reservation exceeds int64 or memory budget'
        plan%reader_atom_bytes=checked_product([grid%natoms,int(storage_size(atom_size_probe)/8,c_int64_t)],arithmetic_ok)
        if (.not.arithmetic_ok) exit body
        plan%host_bytes=checked_sum([plan%host_bytes,plan%reader_atom_bytes],arithmetic_ok)
        if (.not.arithmetic_ok.or.plan%host_bytes>memory_budget_bytes) exit body
      end if
      stage='metadata'
      message='Unsupported or missing metadata declaration'
      ! Check strings before narrowing them to the reader's fixed field lengths.
      if (quantity/='electron_density'.or.spin_convention/='spin_summed') exit body
      if (length_unit/='bohr'.or.density_unit/='electron/bohr^3') exit body
      select case(trim(density_representation))
      case('all_electron','valence','core_augmented','promolecular')
      case default
        exit body
      end select
      do i=1,3
        select case(periodic(i))
        case(0)
          if (endpoint_convention(i)/='finite_nodes') exit body
        case(1)
          if (endpoint_convention(i)/='independent_samples') exit body
        case default
          exit body
        end select
      end do
      metadata%quantity=quantity; metadata%spin_convention=spin_convention
      metadata%density_representation=density_representation; metadata%length_unit=length_unit
      metadata%density_unit=density_unit; metadata%periodic=periodic
      metadata%endpoint_convention=endpoint_convention; metadata%negative_tolerance=negative_tolerance
      call validate_cube_metadata(grid,metadata,reader_status)
      if (reader_status%code/=CUBE_OK) then
        message=trim(reader_status%message); exit body
      end if
      npoints=grid%npoints
      stage='memory'; message='Cannot allocate output arrays'
      allocate(rdg(max_output),signedrho(max_output),lambda2(max_output),flags(max_output),stat=ios)
      if (ios/=0) exit body
      if (layout_mode==1) then
        allocate(slab_rho(max_input),stat=ios)
        if (ios/=0) exit body
      end if
      if (output_mode==1) then
        allocate(grad(3,max_output),hess(6,max_output),stat=ios)
        if (ios/=0) exit body
        grad_ptr=c_loc(grad(1,1)); hess_ptr=c_loc(hess(1,1))
      end if
      options%abi_version=NCI_ABI_VERSION; options%struct_bytes=int(c_sizeof(options),c_int32_t)
      options%backend=int(backend,c_int32_t); options%output_mode=output_mode; options%omp_threads=omp_threads
      options%reserved=0; options%rho_min=rho_min; options%negative_tolerance=negative_tolerance
      tile%abi_version=NCI_ABI_VERSION; tile%struct_bytes=int(c_sizeof(tile),c_int32_t)
      tile%global_n=shape; tile%tile_start=0; tile%tile_count=shape
      tile%input_origin=0; tile%input_shape=shape
      tile%input_strides=[shape(2)*shape(3),shape(3),1_int64]
      do i=1,3
        do a=1,3
          tile%j_inv(3*(i-1)+a)=grid%j_inv(i,a)
        end do
      end do
      tile%periodic=periodic; tile%reserved=0
      tile%rho_capacity=npoints; tile%field_capacity=max_output; tile%flags_capacity=max_output
      tile%grad_capacity=0; tile%hess_capacity=0
      if (output_mode==1) then
        tile%grad_capacity=3*max_output; tile%hess_capacity=6*max_output
      end if
      stage='abi_create'; error=c_null_char
      rc=context_create(c_loc(options),c_loc(context),c_loc(error),size(error,kind=c_size_t))
      abi_status=rc
      if (rc/=NCI_OK) then
        message=c_message(error); exit body
      end if
      s=0
      do while(s<shape(1))
        b=min(bmax,shape(1)-s); nout=b*plane
        rho_ptr=c_loc(grid%rho(1))
        if (layout_mode==1) then
          if (periodic(1)==1) then
            lo=s-2; hi=s+b+2
          else
            lo=max(0_int64,s-2)
            hi=shape(1)
            if (s+b<shape(1)-2) hi=s+b+2
          end if
          nin=(hi-lo)*plane
          do k=0,hi-lo-1
            gx=lo+k
            if (periodic(1)==1) gx=modulo(gx,shape(1))
            slab_rho(k*plane+1:(k+1)*plane)=grid%rho(gx*plane+1:(gx+1)*plane)
          end do
          rho_ptr=c_loc(slab_rho(1))
          tile%tile_start=[s,0_int64,0_int64]; tile%tile_count=[b,shape(2),shape(3)]
          tile%input_origin=[lo,0_int64,0_int64]; tile%input_shape=[hi-lo,shape(2),shape(3)]
          tile%rho_capacity=nin
        end if
        ! Reset every call: stale completed stats must never disguise a later
        ! preflight rejection. The whole original rho was already validated.
        call reset_stats(stats)
        stage='numerics'; error=c_null_char
#ifdef NCI_BENCHMARK
        if (present(benchmark)) then
          eval_start=nci_bench_clock_ns()
          if (eval_start<0) then
            stage='timing'; message='Monotonic clock failed before evaluate'; exit body
          end if
        end if
#endif
        rc=evaluate(context,c_loc(tile),rho_ptr,c_loc(rdg(1)),c_loc(signedrho(1)), &
          c_loc(lambda2(1)),grad_ptr,hess_ptr,c_loc(flags(1)),c_loc(stats),c_loc(error),size(error,kind=c_size_t))
#ifdef NCI_BENCHMARK
        if (present(benchmark)) eval_stop=nci_bench_clock_ns()
#endif
        abi_status=rc; message=c_message(error)
        computed=completed_stats(stats,nout)
        continuable=.false.
        if (computed) then
          select case(rc)
          case(NCI_OK)
            computed=(stats%valid_points>0.and.stats%numeric_failures==0)
          case(NCI_INVALID_INPUT)
            computed=completed_invalid_slab(stats,flags(:nout))
            continuable=computed
          case(NCI_NUMERIC_FAILURE)
            computed=(stats%numeric_failures>0)
          case default
            computed=.false.
          end select
        end if
#ifdef NCI_BENCHMARK
        if (present(benchmark)) then
          ! Getter is outside Teval. A historical valid record cannot make an
          ! unsuccessful ABI call eligible; status3 requires the original
          ! completed_invalid_slab proof above, not a status-only whitelist.
          call nci_bench_get_timing(context,sample,timing_ok)
          call benchmark_observe(benchmark,s,b,rc,eval_start,eval_stop,sample,timing_ok, &
            computed.and.(rc==NCI_OK.or.continuable))
          if (.not.benchmark%timing_valid) then
            stage='timing'; message='Ineligible ABI sample, private timing, actual team or launch bound failed'; exit body
          end if
        end if
#endif
        if (.not.computed) then
          if (rc==NCI_OK) message='ABI returned inconsistent completed statistics'
          exit body
        end if
        if (.not.aggregate_stats(total_stats,stats,npoints)) then
          message='Aggregate statistics exceed global extent'; exit body
        end if
        stats_ready=.true.
        if (.not.any(streams%opened)) call open_streams(streams,directory,output_mode==1,ios)
        if (ios==0) call write_field(streams%unit(1),rdg(:nout),ios)
        if (ios==0) call write_field(streams%unit(2),lambda2(:nout),ios)
        if (ios==0) call write_field(streams%unit(3),signedrho(:nout),ios)
        if (ios==0) call write_field(streams%unit(4),flags(:nout),ios)
        if (output_mode==1) then
          if (ios==0) call write_field(streams%unit(5),grad(:,:nout),ios)
          if (ios==0) call write_field(streams%unit(6),hess(:,:nout),ios)
        end if
        if (ios/=0) then
          if (rc==NCI_OK.or.continuable) then
            stage='io'; message='Cannot exclusively create/write raw field stream'
          else
            message=message//'; raw output IO also failed'
          end if
          exit body
        end if
        if (rc/=NCI_OK.and..not.continuable) exit body
        s=s+b
      end do
      if (total_stats%total_points/=npoints) then
        message='Incomplete global computation'; exit body
      end if
      if (total_stats%valid_points==0) then
        abi_status=NCI_INVALID_INPUT; message='No numerically valid point in global output'; exit body
      end if
      abi_status=NCI_OK
      complete=.true.; stage='complete'; message='Numerical completion; scientific uncertainty unknown'
    end block body
    call close_streams(streams,ios)
    if (ios/=0) then
      if (complete) then
        stage='io'; message='Cannot close raw field stream'
      else
        message=message//'; raw stream close also failed'
      end if
      complete=.false.
    end if
    if (c_associated(context)) then
      error=c_null_char
      cleanup_rc=context_destroy(context,c_loc(error),size(error,kind=c_size_t))
      context=c_null_ptr
      if (cleanup_rc/=NCI_OK) then
        if (complete) then
          stage='cleanup'; message='Context cleanup failed: '//c_message(error)
        else
          message=message//'; context cleanup also failed: '//c_message(error)
        end if
        complete=.false.
      end if
    end if
    call native_receipt(directory,stage,message,complete,abi_status,npoints,total_stats,stats_ready,backend,plan,ios)
    if (ios/=0) then
      write(error_unit,'(a)') 'native receipt IO failed; original status: '//stage//': '//message
      complete=.false.
    end if
#ifdef NCI_BENCHMARK
    if (present(benchmark)) then
      ! Include release of native reader/field storage in the measured workflow.
      if (allocated(rdg)) deallocate(rdg)
      if (allocated(signedrho)) deallocate(signedrho)
      if (allocated(lambda2)) deallocate(lambda2)
      if (allocated(flags)) deallocate(flags)
      if (allocated(grad)) deallocate(grad)
      if (allocated(hess)) deallocate(hess)
      if (allocated(slab_rho)) deallocate(slab_rho)
      if (allocated(grid%rho)) deallocate(grid%rho)
      if (allocated(grid%atoms)) deallocate(grid%atoms)
      ! Native metadata and every FULL field have closed; context cleanup above
      ! is complete. Persist all five files and their directory equally on CPU
      ! and GPU, before the Te2e stop timestamp or any first-result ACK.
      if (complete) then
        ios=benchmark_sync_results(directory)
        if (ios/=0) then
          complete=.false.; stage='persistence'; message='Result file or directory fsync failed'
        end if
      end if
      e2e_stop=nci_bench_clock_ns()
      if (benchmark%e2e_start_ns<0.or.e2e_stop<benchmark%e2e_start_ns) then
        complete=.false.; stage='timing'; message='Invalid end-to-end monotonic clock'
      else
        benchmark%e2e_seconds=real(e2e_stop-benchmark%e2e_start_ns,c_double)*1.0e-9_c_double
      end if
      benchmark%complete=complete
    end if
#endif
    if (complete) then
      exit_status=0
    else
      write(error_unit,'(a)') stage//': '//message
    end if
  end subroutine
end module
