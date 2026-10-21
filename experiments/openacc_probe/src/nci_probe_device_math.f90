! SPDX-License-Identifier: MIT
!> Historical M3A candidate, retained for the failed purity-gate record.
!> NOT part of the current CMake targets or generated source bindings.
!> Importing these NVHPC LIBM interfaces produced NVFORTRAN-W-0473 because
!> scalbn/cbrt were not declared PURE. The selected implementation retains
!> the original pure bind(C) interfaces and adds !$acc routine seq instead.
module nci_probe_device_math
  use libm, only: c_scalbn => scalbn, c_cbrt => cbrt
  implicit none
  private
  public :: c_scalbn, c_cbrt
end module nci_probe_device_math
