! Test executable, not a production CLI or scientific input certificate.
program cube_probe
  use nci_cube_input
  use, intrinsic :: iso_fortran_env, only: int64
  implicit none
  type(cube_grid) :: grid
  type(cube_status) :: status
  type(cube_read_limits) :: limits
  type(cube_metadata) :: metadata
  character(len=4096) :: path
  character(len=64) :: mode, argument
  integer :: i,ios
  call get_command_argument(1,path)
  call get_command_argument(2,mode)
  if (command_argument_count()>=3) then
    call get_command_argument(3,argument)
    read(argument,*,iostat=ios) limits%max_bytes
    if (ios/=0) error stop 'invalid test byte budget'
  end if
  if (command_argument_count()>=4) then
    call get_command_argument(4,argument)
    read(argument,*,iostat=ios) limits%max_points
    if (ios/=0) error stop 'invalid test point budget'
  end if
  if (command_argument_count()>=7) then
    call get_command_argument(5,argument)
    read(argument,*,iostat=ios) limits%reserve_bytes_per_point
    if (ios/=0) error stop 'invalid test per-point reservation'
    call get_command_argument(6,argument)
    read(argument,*,iostat=ios) limits%reserve_bytes_per_axis_node
    if (ios/=0) error stop 'invalid test per-axis-node reservation'
    call get_command_argument(7,argument)
    read(argument,*,iostat=ios) limits%reserve_fixed_bytes
    if (ios/=0) error stop 'invalid test fixed reservation'
  end if
  call read_cube(trim(path),grid,status,limits)
  write(*,'(a,1x,i0)') 'STATUS',status%code
  write(*,'(a,1x,i0)') 'LINE',status%line
  write(*,'(a,1x,a)') 'MESSAGE',trim(status%message)
  write(*,'(a,1x,l1,1x,l1)') 'ALLOCATED',allocated(grid%rho),allocated(grid%atoms)
  if (status%code/=CUBE_OK) then
    write(*,'(a,3(1x,l1))') 'FLAGS',grid%structurally_valid,grid%metadata_validated,grid%scientifically_certified
  else
    write(*,'(a,3(1x,i0))') 'SHAPE',grid%shape
    write(*,'(a,1x,i0)') 'NATOMS',grid%natoms
    write(*,'(a,1x,es24.16)') 'COND',grid%condition2
    write(*,'(a,1x,es24.16)') 'VOLUME',grid%volume_element
    write(*,'(a,3(1x,es24.16))') 'ORIGIN',grid%origin
    do i=1,3
      write(*,'(a,i0,3(1x,es24.16))') 'INVERSE',i,grid%j_inv(i,:)
    end do
    if (grid%natoms>0_int64) then
      write(*,'(a,1x,i0,4(1x,es24.16))') 'ATOM1',grid%atoms(1)%atomic_number, &
        grid%atoms(1)%charge,grid%atoms(1)%position
    end if
    if (grid%npoints<=1000_int64) write(*,'(a,*(1x,es24.16))') 'RHO',grid%rho
    if (trim(mode)/='none') then
      metadata%quantity='electron_density'; metadata%spin_convention='spin_summed'
      metadata%density_representation='all_electron'
      metadata%length_unit='bohr'; metadata%density_unit='electron/bohr^3'
      metadata%periodic=[0,1,0]
      metadata%endpoint_convention=['finite_nodes            ', &
        'independent_samples     ','finite_nodes            ']
      select case(trim(mode))
      case('valid')
      case('unknown')
        metadata=cube_metadata()
      case('angstrom')
        metadata%length_unit='angstrom'
      case('density_unit')
        metadata%density_unit='electron/angstrom^3'
      case('spin')
        metadata%spin_convention='spin_difference'
      case('orbital')
        metadata%quantity='orbital_amplitude'
      case('representation')
        metadata%density_representation='unknown'
      case('valence','core_augmented','promolecular')
        metadata%density_representation=trim(mode)
      case('periodic')
        metadata%periodic(2)=-1
      case('endpoint')
        metadata%endpoint_convention(2)='duplicated_endpoint'
      case('finite_endpoint')
        metadata%endpoint_convention(1)='independent_samples'
      case('negative_tolerance')
        metadata%negative_tolerance=1.0e-6_cube_dp
      case('bad_tolerance')
        metadata%negative_tolerance=-1.0_cube_dp
      case('nan_tolerance')
        block
          use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan
          metadata%negative_tolerance=ieee_value(0.0_cube_dp,ieee_quiet_nan)
        end block
      case default
        error stop 'unknown test metadata mode'
      end select
      call validate_cube_metadata(grid,metadata,status)
      write(*,'(a,1x,i0)') 'META_STATUS',status%code
      write(*,'(a,1x,a)') 'META_MESSAGE',trim(status%message)
      write(*,'(a,1x,es24.16)') 'FIRST_AFTER_METADATA',grid%rho(1)
    end if
    write(*,'(a,3(1x,l1))') 'FLAGS',grid%structurally_valid,grid%metadata_validated,grid%scientifically_certified
    call clear_cube(grid)
    write(*,'(a,1x,l1,1x,l1)') 'CLEARED',allocated(grid%rho),grid%structurally_valid
  end if
end program
