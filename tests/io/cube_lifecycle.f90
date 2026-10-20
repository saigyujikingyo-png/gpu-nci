program cube_lifecycle
  use nci_cube_input
  use, intrinsic :: iso_fortran_env, only: int64
  use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
  implicit none
  type(cube_grid) :: grid
  type(cube_metadata) :: metadata
  type(cube_status) :: status
  character(len=4096) :: path
  integer :: unit,checks=0
  call get_command_argument(1,path)
  open(newunit=unit,file=trim(path),status='replace',action='write')
  write(unit,'(a)') 'synthetic lifecycle fixture', '', '0 0 0 0', &
    '5 1 0 0', '5 0 1 0', '5 0 0 1'
  write(unit,'(125(f4.1,1x))') spread(1.0_cube_dp,1,125)
  close(unit)

  call validate_cube_metadata(grid,metadata,status)
  call check(status%code==CUBE_INVALID_METADATA,'unparsed grid metadata rejection')
  call read_cube(trim(path),grid,status)
  call check(status%code==CUBE_OK,'initial read')
  call check(grid%npoints==125_int64.and.allocated(grid%rho),'owned density after read')
  call check(.not.grid%metadata_validated.and..not.grid%scientifically_certified,'raw boundary')
  metadata%quantity='electron_density'; metadata%spin_convention='spin_summed'
  metadata%density_representation='all_electron'
  metadata%length_unit='bohr'; metadata%density_unit='electron/bohr^3'
  metadata%periodic=0; metadata%endpoint_convention='finite_nodes'
  call validate_cube_metadata(grid,metadata,status)
  call check(status%code==CUBE_OK.and.grid%metadata_validated,'valid metadata')
  call check(.not.grid%scientifically_certified,'not a scientific certificate')
  metadata%density_representation='unknown'
  call validate_cube_metadata(grid,metadata,status)
  call check(status%code==CUBE_INVALID_METADATA.and..not.grid%metadata_validated,'stale metadata flag reset')
  metadata%density_representation='valence'
  grid%rho(1)=ieee_value(0.0_cube_dp,ieee_quiet_nan)
  call validate_cube_metadata(grid,metadata,status)
  call check(status%code==CUBE_NONFINITE,'recheck mutable sample finite state')
  call check(ieee_is_nan(grid%rho(1)),'metadata failure preserves raw sample')
  call read_cube(trim(path),grid,status)
  call check(status%code==CUBE_OK.and.grid%rho(1)==1.0_cube_dp,'reread resets prior allocation')
  call read_cube(trim(path)//'.absent',grid,status)
  call check(status%code==CUBE_IO_ERROR,'subsequent I/O failure')
  call check(.not.allocated(grid%rho).and..not.allocated(grid%atoms),'failure clears previous allocations')
  call check(.not.grid%structurally_valid.and.grid%npoints==0_int64,'failure clears previous metadata')
  call read_cube(trim(path),grid,status)
  call check(status%code==CUBE_OK,'reuse after failure')
  call clear_cube(grid)
  call clear_cube(grid)
  call check(.not.allocated(grid%rho).and..not.grid%structurally_valid,'idempotent clear')
  write(*,'(a,i0)') 'Native Fortran lifecycle assertions passed: ',checks
contains
  subroutine check(condition,label)
    logical, intent(in) :: condition
    character(len=*), intent(in) :: label
    if (.not.condition) then
      write(*,'(a)') 'FAILED: '//label
      error stop 1
    end if
    checks=checks+1
  end subroutine
end program
