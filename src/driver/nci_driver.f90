program nci_driver
  use, intrinsic :: iso_c_binding, only: c_int
  use, intrinsic :: iso_fortran_env, only: error_unit
  use nci_driver_support
  implicit none
  integer :: exit_status
  interface
    subroutine process_exit(status) bind(C,name='exit')
      import :: c_int
      integer(c_int), value :: status
    end subroutine
  end interface
  if (command_argument_count()==1) then
    if (argument(1)=='--build-info') then
      exit_status=emit_build_info()
      call process_exit(int(exit_status,c_int))
    end if
  end if
  if (command_argument_count()/=3) then
    write(error_unit,'(a)') 'usage: nci_driver INPUT.cube SETTINGS.nml OUTPUT_DIRECTORY | --build-info'
    call process_exit(1_c_int)
  end if
  call execute_run(argument(1),argument(2),argument(3),exit_status)
  call process_exit(int(exit_status,c_int))
end program
