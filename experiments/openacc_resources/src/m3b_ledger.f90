! SPDX-License-Identifier: MIT
!> M3B0 bounded resource-event ledger (docs/openacc-resource-contract.md).
!>
!> Each workspace instance owns one fixed-capacity ledger; nothing here is
!> shared between instances. Recording never allocates, performs no I/O and
!> never stops. An event beyond the capacity is not stored but counted as
!> dropped, and that count is never reset, so a reader can reject an
!> incomplete ledger. Only the developer harness formats and writes events.
!> Every procedure is RECURSIVE so that its locals are automatic.
module m3b_ledger
  use, intrinsic :: iso_fortran_env, only: int64
  implicit none
  private
  public :: resource_event, event_ledger
  public :: ledger_record, ledger_count, ledger_event, ledger_clear, ledger_dropped
  public :: buffer_name, action_name

  !> Events kept between two drains. A prepare records at most 19 events and
  !> a release 12; the harness drains after each of them.
  integer, parameter, public :: LEDGER_CAPACITY = 64

  !> The three buffers of a workspace, in acquisition order.
  integer, parameter, public :: BUF_IN = 1, BUF_OUT = 2, BUF_MARK = 3, BUFFERS = 3

  !> Actions of the frozen M3B0_RESOURCE grammar.
  integer, parameter, public :: ACT_H_ALLOC = 1, ACT_H_FAIL = 2, ACT_D_ALLOC = 3, &
    ACT_D_FAIL = 4, ACT_MAP = 5, ACT_PRESENT = 6, ACT_UNMAP = 7, ACT_D_FREE = 8, ACT_H_FREE = 9

  !> One resource operation: workspace label, prepare generation, buffer,
  !> action, the buffer's tracked bytes and the result (0 success, 5
  !> allocation failure, or the actual PRESENT query result as 1 or 0).
  type :: resource_event
    character(len=1) :: workspace = ' '
    integer :: generation = 0
    integer :: buffer = 0
    integer :: action = 0
    integer(int64) :: bytes = 0
    integer :: result = 0
  end type resource_event

  type :: event_ledger
    private
    type(resource_event) :: events(LEDGER_CAPACITY)
    integer :: count = 0
    integer :: dropped = 0
  end type event_ledger

contains

  recursive subroutine ledger_record(ledger, event)
    type(event_ledger), intent(inout) :: ledger
    type(resource_event), intent(in) :: event
    if (ledger%count < LEDGER_CAPACITY) then
      ledger%count = ledger%count + 1
      ledger%events(ledger%count) = event
    else
      ledger%dropped = ledger%dropped + 1
    end if
  end subroutine ledger_record

  recursive pure function ledger_count(ledger) result(count)
    type(event_ledger), intent(in) :: ledger
    integer :: count
    count = ledger%count
  end function ledger_count

  !> Stored event k, 1 <= k <= ledger_count(ledger), in recorded order.
  recursive pure function ledger_event(ledger, k) result(event)
    type(event_ledger), intent(in) :: ledger
    integer, intent(in) :: k
    type(resource_event) :: event
    event = ledger%events(k)
  end function ledger_event

  !> Forgets the stored events once they were drained; dropped is kept.
  recursive subroutine ledger_clear(ledger)
    type(event_ledger), intent(inout) :: ledger
    ledger%count = 0
  end subroutine ledger_clear

  recursive pure function ledger_dropped(ledger) result(dropped)
    type(event_ledger), intent(in) :: ledger
    integer :: dropped
    dropped = ledger%dropped
  end function ledger_dropped

  !> Grammar name of a buffer; '?' for an unknown code.
  recursive pure function buffer_name(buffer) result(name)
    integer, intent(in) :: buffer
    character(len=4) :: name
    select case (buffer)
    case (BUF_IN)
      name = 'IN'
    case (BUF_OUT)
      name = 'OUT'
    case (BUF_MARK)
      name = 'MARK'
    case default
      name = '?'
    end select
  end function buffer_name

  !> Grammar name of an action; '?' for an unknown code.
  recursive pure function action_name(action) result(name)
    integer, intent(in) :: action
    character(len=7) :: name
    select case (action)
    case (ACT_H_ALLOC)
      name = 'H_ALLOC'
    case (ACT_H_FAIL)
      name = 'H_FAIL'
    case (ACT_D_ALLOC)
      name = 'D_ALLOC'
    case (ACT_D_FAIL)
      name = 'D_FAIL'
    case (ACT_MAP)
      name = 'MAP'
    case (ACT_PRESENT)
      name = 'PRESENT'
    case (ACT_UNMAP)
      name = 'UNMAP'
    case (ACT_D_FREE)
      name = 'D_FREE'
    case (ACT_H_FREE)
      name = 'H_FREE'
    case default
      name = '?'
    end select
  end function action_name

end module m3b_ledger
