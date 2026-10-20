! SPDX-License-Identifier: MIT
!> M3A protocol version 1 on the host (docs/openacc-probe-contract.md).
!>
!> Standard input is a sequence of ASCII tokens separated by blanks, tabs, CR
!> or line ends; the line layout carries no meaning. Token order:
!>   M3A1 NS NR NP
!>   NS times: X_BITS SCALE_EXPONENT
!>   NR times: GX GY GZ RHO
!>   NP times: FLOOR_BITS MAX_ROT, 9 matrix tokens, 125 block tokens
!> Counts are canonical decimals in 0..128 and SCALE_EXPONENT a canonical
!> decimal in [-4096,4096] (no '+', no leading zero, no '-0'); MAX_ROT is 30
!> or 1. Each binary64 is exactly 16 hexadecimal digits (either case) of its
!> IEEE bits. Arrays are read in Fortran element order. A malformed,
!> out-of-range, truncated or excess token, any other byte, or more than 8 MiB
!> rejects the whole input (exit 2) before anything is written to standard
!> output. Output: upper-case hex, single blanks, one record per line.
module m3a_io
  use, intrinsic :: iso_fortran_env, only: input_unit, output_unit, error_unit, &
                                           int64, iostat_end, iostat_eor
  use nci_kinds, only: dp, i64, is_finite, all_finite
  use nci_numerics, only: point_result
  implicit none
  private
  public :: read_input, write_output, stop_with

  integer, parameter, public :: MAX_RECORDS = 128
  integer, parameter, public :: EXIT_INPUT_REJECTED = 2
  integer, parameter, public :: EXIT_NOT_TESTED = 3
  integer, parameter, public :: EXIT_NOT_ON_DEVICE = 4
  integer, parameter :: MAX_SCALE_EXPONENT = 4096
  integer(int64), parameter :: MAX_INPUT_BYTES = 8388608_int64
  integer, parameter :: TOKEN_LEN = 32
  character(len=*), parameter :: HEX = '0123456789ABCDEF'

  ! Reader state: the drivers read their input once, on the host, serially.
  character(len=256) :: chunk = ' '
  integer :: chunk_len = 0, chunk_pos = 0
  logical :: line_end_pending = .false., input_ended = .false.
  integer(int64) :: bytes_read = 0, tokens_read = 0

contains

  !> Reads and checks the complete input; array extents are the record counts.
  subroutine read_input(x, scale_exponent, gradient, rho, floor_abs, max_rot, m, blk)
    real(dp), allocatable, intent(out) :: x(:), gradient(:, :), rho(:), floor_abs(:)
    real(dp), allocatable, intent(out) :: m(:, :, :), blk(:, :, :, :)
    integer, allocatable, intent(out) :: scale_exponent(:), max_rot(:)
    character(len=TOKEN_LEN) :: token
    integer :: n, ns, nr, np, i, a, b, ix, iy, iz

    call required_token(token, n)
    if (n /= 4 .or. token(1:4) /= 'M3A1') call reject('input does not begin with M3A1')
    ns = read_integer(0, MAX_RECORDS, 'NS')
    nr = read_integer(0, MAX_RECORDS, 'NR')
    np = read_integer(0, MAX_RECORDS, 'NP')
    allocate(x(ns), scale_exponent(ns), gradient(3, nr), rho(nr), floor_abs(np), max_rot(np), &
             m(3, 3, np), blk(-2:2, -2:2, -2:2, np))

    do i = 1, ns
      x(i) = read_bits()
      scale_exponent(i) = read_integer(-MAX_SCALE_EXPONENT, MAX_SCALE_EXPONENT, 'SCALE_EXPONENT')
    end do
    do i = 1, nr
      do a = 1, 3
        gradient(a, i) = read_bits()
      end do
      rho(i) = read_bits()
      if (.not. (all_finite(3, gradient(:, i)) .and. is_finite(rho(i)))) &
        call reject('RDG record needs a finite gradient and finite rho')
      if (.not. (rho(i) > 0.0_dp)) call reject('RDG record needs rho > 0')
    end do
    do i = 1, np
      floor_abs(i) = read_bits()
      max_rot(i) = read_integer(1, 30, 'MAX_ROT')
      if (max_rot(i) /= 30 .and. max_rot(i) /= 1) call reject('MAX_ROT must be 30 or 1')
      do b = 1, 3
        do a = 1, 3
          m(a, b, i) = read_bits()
        end do
      end do
      do iz = -2, 2
        do iy = -2, 2
          do ix = -2, 2
            blk(ix, iy, iz, i) = read_bits()
          end do
        end do
      end do
    end do

    call next_token(token, n)
    if (n /= 0) call reject('excess input after the last record')
  end subroutine read_input

  !> Writes the complete M3A1 output; DEVICE flags are written as given.
  subroutine write_output(s_device, s_finite, s_exponent, s_fraction, s_scaled, s_cbrt, &
                          r_device, r_rdg, p_device, p_result)
    logical, intent(in) :: s_device(:), s_finite(:), r_device(:), p_device(:)
    integer, intent(in) :: s_exponent(:)
    real(dp), intent(in) :: s_fraction(:), s_scaled(:), s_cbrt(:), r_rdg(:)
    type(point_result), intent(in) :: p_result(:)
    character(len=512) :: line
    real(dp) :: values(16)
    integer :: n, i, k

    write(output_unit, '(a)') 'M3A1'
    do i = 1, size(s_device)
      n = 0
      call put(line, n, 'S')
      call put(line, n, int_text(i))
      call put(line, n, flag_text(s_device(i)))
      call put(line, n, flag_text(s_finite(i)))
      call put(line, n, int_text(s_exponent(i)))
      call put(line, n, bits_text(s_fraction(i)))
      call put(line, n, bits_text(s_scaled(i)))
      call put(line, n, bits_text(s_cbrt(i)))
      write(output_unit, '(a)') line(1:n)
    end do
    do i = 1, size(r_device)
      n = 0
      call put(line, n, 'R')
      call put(line, n, int_text(i))
      call put(line, n, flag_text(r_device(i)))
      call put(line, n, bits_text(r_rdg(i)))
      write(output_unit, '(a)') line(1:n)
    end do
    do i = 1, size(p_device)
      n = 0
      call put(line, n, 'P')
      call put(line, n, int_text(i))
      call put(line, n, flag_text(p_device(i)))
      call put(line, n, int_text(p_result(i)%status))
      call put(line, n, flag_text(p_result(i)%uncertain))
      write(output_unit, '(a)') line(1:n)
      values = [p_result(i)%grad, p_result(i)%hess, p_result(i)%lambda, p_result(i)%rdg, &
                p_result(i)%signed_rho, p_result(i)%bound, p_result(i)%tau]
      n = 0
      do k = 1, 16
        call put(line, n, bits_text(values(k)))
      end do
      write(output_unit, '(a)') line(1:n)
    end do
    n = 0
    call put(line, n, 'END')
    call put(line, n, int_text(size(s_device)))
    call put(line, n, int_text(size(r_device)))
    call put(line, n, int_text(size(p_device)))
    write(output_unit, '(a)') line(1:n)
    flush(output_unit)
  end subroutine write_output

  !> Diagnostic on standard error, then error termination with exit code 2, 3 or 4.
  subroutine stop_with(code, message)
    integer, intent(in) :: code
    character(len=*), intent(in) :: message
    flush(output_unit)
    write(error_unit, '(2a)') 'M3A1 ', message
    flush(error_unit)
    select case (code)
    case (EXIT_INPUT_REJECTED)
      error stop 2
    case (EXIT_NOT_TESTED)
      error stop 3
    case default
      error stop 4
    end select
  end subroutine stop_with

  subroutine reject(what)
    character(len=*), intent(in) :: what
    character(len=24) :: count
    write(count, '(i0)') tokens_read
    call stop_with(EXIT_INPUT_REJECTED, 'INPUT_REJECTED: '//what//' (tokens read: '//trim(count)//')')
  end subroutine reject

  !> Canonical decimal integer in [lo, hi].
  function read_integer(lo, hi, what) result(value)
    integer, intent(in) :: lo, hi
    character(len=*), intent(in) :: what
    integer :: value
    character(len=TOKEN_LEN) :: token
    integer :: n, first, k, digit
    logical :: negative
    call required_token(token, n)
    negative = token(1:1) == '-'
    first = merge(2, 1, negative)
    if (n < first .or. n - first + 1 > 4) call reject('malformed '//what)
    if (token(first:first) == '0' .and. (n > first .or. negative)) call reject('malformed '//what)
    value = 0
    do k = first, n
      digit = index('0123456789', token(k:k)) - 1
      if (digit < 0) call reject('malformed '//what)
      value = 10*value + digit
    end do
    if (negative) value = -value
    if (value < lo .or. value > hi) call reject(what//' out of range')
  end function read_integer

  !> Exactly 16 hexadecimal digits holding the IEEE binary64 bit pattern.
  function read_bits() result(x)
    real(dp) :: x
    character(len=TOKEN_LEN) :: token
    integer :: n, k, digit
    integer(i64) :: bits
    call required_token(token, n)
    if (n /= 16) call reject('binary64 token is not 16 hexadecimal digits')
    bits = 0_i64
    do k = 1, 16
      digit = index(HEX, token(k:k)) - 1
      if (digit < 0) digit = index('0123456789abcdef', token(k:k)) - 1
      if (digit < 0) call reject('binary64 token is not 16 hexadecimal digits')
      bits = ior(shiftl(bits, 4), int(digit, i64))
    end do
    x = transfer(bits, 0.0_dp)
  end function read_bits

  subroutine required_token(token, n)
    character(len=TOKEN_LEN), intent(out) :: token
    integer, intent(out) :: n
    call next_token(token, n)
    if (n == 0) call reject('truncated input')
  end subroutine required_token

  !> Next token; n = 0 at the end of the input.
  subroutine next_token(token, n)
    character(len=TOKEN_LEN), intent(out) :: token
    integer, intent(out) :: n
    character :: c
    logical :: ended
    token = ' '
    n = 0
    do
      call next_char(c, ended)
      if (ended) return
      if (c /= ' ') exit
    end do
    tokens_read = tokens_read + 1
    do
      if (n == TOKEN_LEN) call reject('token longer than 32 characters')
      n = n + 1
      token(n:n) = c
      call next_char(c, ended)
      if (ended .or. c == ' ') exit
    end do
  end subroutine next_token

  !> Next input character. Every separator (blank, tab, CR, line end) is
  !> returned as ' '; ended is set once the input is exhausted.
  subroutine next_char(c, ended)
    character, intent(out) :: c
    logical, intent(out) :: ended
    integer :: ios, code
    ended = .false.
    c = ' '
    do
      if (chunk_pos < chunk_len) then
        chunk_pos = chunk_pos + 1
        c = chunk(chunk_pos:chunk_pos)
        code = ichar(c)
        if (code == 9 .or. code == 13) then
          c = ' '
        else if (code < 32 .or. code > 126) then
          call reject('byte outside printable ASCII')
        end if
        return
      end if
      if (line_end_pending) then
        line_end_pending = .false.
        return
      end if
      if (input_ended) then
        ended = .true.
        return
      end if
      chunk_len = 0
      chunk_pos = 0
      read(input_unit, '(a)', advance='no', size=chunk_len, iostat=ios) chunk
      if (ios == iostat_eor) then
        line_end_pending = .true.
        bytes_read = bytes_read + 1
      else if (ios == iostat_end) then
        input_ended = .true.
      else if (ios /= 0) then
        call reject('read error on standard input')
      end if
      bytes_read = bytes_read + chunk_len
      if (bytes_read > MAX_INPUT_BYTES) call reject('input larger than 8 MiB')
    end do
  end subroutine next_char

  function int_text(value) result(text)
    integer, intent(in) :: value
    character(len=:), allocatable :: text
    character(len=16) :: buffer
    write(buffer, '(i0)') value
    text = trim(buffer)
  end function int_text

  function flag_text(flag) result(text)
    logical, intent(in) :: flag
    character(len=1) :: text
    text = merge('1', '0', flag)
  end function flag_text

  !> The 64 IEEE bits of x as 16 upper-case hexadecimal digits.
  function bits_text(x) result(text)
    real(dp), intent(in) :: x
    character(len=16) :: text
    integer(i64) :: bits
    integer :: k, nibble
    bits = transfer(x, 0_i64)
    do k = 16, 1, -1
      nibble = int(iand(bits, 15_i64))
      text(k:k) = HEX(nibble + 1:nibble + 1)
      bits = shiftr(bits, 4)
    end do
  end function bits_text

  subroutine put(line, n, text)
    character(len=*), intent(inout) :: line
    integer, intent(inout) :: n
    character(len=*), intent(in) :: text
    if (n > 0) then
      n = n + 1
      line(n:n) = ' '
    end if
    line(n + 1:n + len(text)) = text
    n = n + len(text)
  end subroutine put

end module m3a_io
