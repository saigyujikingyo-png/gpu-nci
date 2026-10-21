! Test fixture only: no context creation, allocation or field evaluation.
! Link the production object set to reach the existing private size helper;
! no symbol is added to the production libraries or worker.
program compiled_sizes
  use, intrinsic :: iso_c_binding
  use, intrinsic :: iso_fortran_env, only: output_unit, error_unit
  use nci_acc_backend, only: acc_fixed_storage, ACC_FIXED_STORAGE_ITEMS
  use nci_abi, only: nci_options_v1
  use nci_cube_input, only: cube_atom
  implicit none
  ! Mirror the source-bound private wrapper solely to check its compiled
  ! interoperable layout. It is already covered by F_common, not F_acc.
  type, bind(C) :: context_size_probe
    integer(c_int64_t) :: magic
    type(nci_options_v1) :: options
    type(c_ptr) :: backend
  end type
  type(context_size_probe) :: context
  type(cube_atom) :: atom
  integer(c_int64_t) :: sizes(ACC_FIXED_STORAGE_ITEMS),atom_bytes
  integer :: ios
  call acc_fixed_storage(sizes)
  atom_bytes=int(storage_size(atom)/8,c_int64_t)
  if (any(sizes<=0).or.atom_bytes<=0.or.c_sizeof(context)<=0) then
    write(error_unit,'(a)') 'Invalid compiled storage size'
    stop 1
  end if
  ! 272 aligned launch bytes and 288 static host bytes must also be verified
  ! against the actual compiler metadata by the frozen execution package.
  ! The contained ledger/descriptors are deliberately not added a second time.
  if (sizes(1)>65536_c_int64_t-272_c_int64_t-288_c_int64_t.or. &
      sizes(2)>sizes(1).or.sizes(3)>sizes(1).or.sizes(4)>272_c_int64_t.or. &
      c_sizeof(context)>65536_c_int64_t) then
    write(error_unit,'(a)') 'Compiled storage exceeds the worker fixed allowance'
    stop 1
  end if
  write(output_unit,'(a,i0,a,i0,a,i0,a,i0,a,i0,a,i0,a)',iostat=ios) &
    '{"workspace_bytes":',sizes(1),',"contained_ledger_bytes":',sizes(2), &
    ',"contained_descriptor_bytes":',sizes(3),',"explicit_launch_scalar_bytes":',sizes(4), &
    ',"context_wrapper_bytes":',c_sizeof(context),',"reader_atom_size_bytes":',atom_bytes,'}'
  if (ios/=0) stop 1
  flush(output_unit,iostat=ios)
  if (ios/=0) stop 1
end program
