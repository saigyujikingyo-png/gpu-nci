! SPDX-License-Identifier: MIT
!> M3A device driver (docs/openacc-probe-contract.md): the same records as
!> m3a_host, evaluated by the device-adapted production source inside OpenACC
!> compute regions on an explicitly selected NVIDIA device.
!>
!> * No host fallback: without an NVIDIA device the result is NOT_TESTED
!>   (exit 3) and nothing is written to standard output.
!> * DEVICE is acc_on_device(acc_device_nvidia) evaluated in the loop
!>   iteration that performs the record's calculation. Any DEVICE = 0 makes
!>   the exit status 4 after the output has been written.
!> * Device results are copied back and written unchanged; the host never
!>   recomputes or replaces them. All input/output happens on the host.
!> * No OpenACC error callback is installed: a fatal runtime error terminates
!>   the process with a nonzero status (errors are not contained).
program m3a_device
  use, intrinsic :: iso_fortran_env, only: error_unit
  use openacc
  use nci_kinds, only: dp
  use nci_numerics, only: point_result
  use m3a_records, only: scalar_record, rdg_record, point_record
  use m3a_io, only: read_input, write_output, stop_with, EXIT_NOT_TESTED, EXIT_NOT_ON_DEVICE
  implicit none
  real(dp), allocatable :: x(:), gradient(:, :), rho(:), floor_abs(:), m(:, :, :), blk(:, :, :, :)
  integer, allocatable :: scale_exponent(:), max_rot(:), s_exponent(:)
  logical, allocatable :: s_device(:), s_finite(:), r_device(:), p_device(:)
  real(dp), allocatable :: s_fraction(:), s_scaled(:), s_cbrt(:), r_rdg(:)
  type(point_result), allocatable :: p_result(:)
  integer :: ns, nr, np, i

  call read_input(x, scale_exponent, gradient, rho, floor_abs, max_rot, m, blk)
  ns = size(x)
  nr = size(rho)
  np = size(floor_abs)
  allocate(s_device(ns), s_finite(ns), s_exponent(ns), s_fraction(ns), s_scaled(ns), s_cbrt(ns))
  allocate(r_device(nr), r_rdg(nr), p_device(np), p_result(np))
  call select_nvidia_device()

  if (ns > 0) then
    !$acc parallel loop copyin(x, scale_exponent) &
    !$acc   copyout(s_device, s_finite, s_exponent, s_fraction, s_scaled, s_cbrt)
    do i = 1, ns
      s_device(i) = acc_on_device(acc_device_nvidia)
      call scalar_record(x(i), scale_exponent(i), s_finite(i), s_exponent(i), s_fraction(i), &
                         s_scaled(i), s_cbrt(i))
    end do
  end if
  if (nr > 0) then
    !$acc parallel loop copyin(gradient, rho) copyout(r_device, r_rdg)
    do i = 1, nr
      r_device(i) = acc_on_device(acc_device_nvidia)
      call rdg_record(gradient(:, i), rho(i), r_rdg(i))
    end do
  end if
  if (np > 0) then
    !$acc parallel loop copyin(blk, m, floor_abs, max_rot) copyout(p_device, p_result)
    do i = 1, np
      p_device(i) = acc_on_device(acc_device_nvidia)
      call point_record(blk(:, :, :, i), m(:, :, i), floor_abs(i), max_rot(i), p_result(i))
    end do
  end if

  call write_output(s_device, s_finite, s_exponent, s_fraction, s_scaled, s_cbrt, &
                    r_device, r_rdg, p_device, p_result)
  if (.not. (all(s_device) .and. all(r_device) .and. all(p_device))) &
    call stop_with(EXIT_NOT_ON_DEVICE, 'NOT_ON_DEVICE: a record reported DEVICE = 0')

contains

  !> Explicit NVIDIA selection of device 0; its identity goes to standard error.
  subroutine select_nvidia_device()
    integer :: count
    character(len=256) :: name, vendor, driver
    count = acc_get_num_devices(acc_device_nvidia)
    if (count < 1) call stop_with(EXIT_NOT_TESTED, &
      'NOT_TESTED: acc_get_num_devices(acc_device_nvidia) < 1; no host fallback is used')
    call acc_set_device_type(acc_device_nvidia)
    call acc_set_device_num(0, acc_device_nvidia)
    call acc_init(acc_device_nvidia)
    name = ' '
    vendor = ' '
    driver = ' '
    call acc_get_property_string(0, acc_device_nvidia, acc_property_name, name)
    call acc_get_property_string(0, acc_device_nvidia, acc_property_vendor, vendor)
    call acc_get_property_string(0, acc_device_nvidia, acc_property_driver, driver)
    write(error_unit, '(a,i0,a,i0,7a)') 'M3A1 DEVICE nvidia_devices=', count, ' selected=', &
      acc_get_device_num(acc_device_nvidia), ' name="', trim(name), '" vendor="', trim(vendor), &
      '" driver="', trim(driver), '"'
    flush(error_unit)
  end subroutine select_nvidia_device

end program m3a_device
