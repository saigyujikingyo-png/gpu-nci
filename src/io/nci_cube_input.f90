! Original implementation. No third-party parser or numerical code is copied.
module nci_cube_input
  use, intrinsic :: iso_c_binding, only: c_double
  use, intrinsic :: iso_fortran_env, only: int64
  use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
  implicit none
  private
  integer, parameter, public :: cube_dp = c_double
  integer, parameter, public :: CUBE_OK=0, CUBE_IO_ERROR=1, CUBE_MISSING_TOKEN=2, &
    CUBE_EXTRA_TOKEN=3, CUBE_INVALID_INTEGER=4, CUBE_INVALID_REAL=5, &
    CUBE_NONFINITE=6, CUBE_UNSUPPORTED=7, CUBE_DIMENSION=8, CUBE_OVERFLOW=9, &
    CUBE_MEMORY_LIMIT=10, CUBE_ALLOCATION=11, CUBE_INVALID_ATOM=12, &
    CUBE_GRID_SINGULAR=13, CUBE_GRID_CONDITION=14, CUBE_INVALID_METADATA=15, &
    CUBE_UNSUPPORTED_UNIT=16, CUBE_INVALID_DENSITY=17, CUBE_TOKEN_TOO_LONG=18, &
    CUBE_GRID_RANGE=19
  integer, parameter :: block_size=8192, token_size=256

  type, public :: cube_status
    integer :: code=CUBE_OK
    integer(int64) :: line=0_int64
    character(len=256) :: message=''
  end type
  type, public :: cube_atom
    integer :: atomic_number=0
    real(cube_dp) :: charge=0.0_cube_dp
    real(cube_dp) :: position(3)=0.0_cube_dp
  end type
  type, public :: cube_read_limits
    ! Budget includes the density array, atom array and scanner block.
    integer(int64) :: max_bytes=268435456_int64
    integer(int64) :: max_points=33554432_int64
  end type
  type, public :: cube_grid
    integer(int64) :: natoms=0_int64, shape(3)=0_int64, npoints=0_int64
    real(cube_dp) :: origin(3)=0.0_cube_dp, j(3,3)=0.0_cube_dp
    real(cube_dp) :: j_inv(3,3)=0.0_cube_dp
    real(cube_dp) :: condition2=0.0_cube_dp, volume_element=0.0_cube_dp
    type(cube_atom), allocatable :: atoms(:)
    real(cube_dp), allocatable :: rho(:) ! Z fastest: ((ix*Ny)+iy)*Nz+iz+1
    logical :: structurally_valid=.false., metadata_validated=.false.
    ! This module cannot certify provenance, convergence, or physical accuracy.
    logical :: scientifically_certified=.false.
  end type
  type, public :: cube_metadata
    character(len=32) :: quantity='', spin_convention='', density_representation=''
    character(len=32) :: length_unit='', density_unit=''
    integer :: periodic(3)=-1 ! Explicit 0 (finite) or 1 (periodic), never guessed.
    character(len=24) :: endpoint_convention(3)=''
    real(cube_dp) :: negative_tolerance=0.0_cube_dp
  end type
  type :: cube_reader
    integer :: unit=0, cursor=1, filled=0
    integer(int64) :: file_bytes=0_int64, loaded=0_int64, line=1_int64
    character(len=block_size) :: block=''
  end type
  public :: read_cube, validate_cube_metadata, clear_cube

contains
  subroutine clear_cube(grid)
    type(cube_grid), intent(inout) :: grid
    grid=cube_grid()
  end subroutine

  subroutine fail(status, code, message, line)
    type(cube_status), intent(inout) :: status
    integer, intent(in) :: code
    character(len=*), intent(in) :: message
    integer(int64), intent(in), optional :: line
    if (status%code/=CUBE_OK) return
    status%code=code
    status%message=message
    if (present(line)) status%line=line
  end subroutine

  subroutine peek(reader, ch, ended, status)
    type(cube_reader), intent(inout) :: reader
    character, intent(out) :: ch
    logical, intent(out) :: ended
    type(cube_status), intent(inout) :: status
    integer :: ios, count
    ch=' '; ended=.true.
    if (status%code/=CUBE_OK) return
    if (reader%cursor>reader%filled) then
      if (reader%loaded>=reader%file_bytes) return
      count=int(min(int(block_size,int64),reader%file_bytes-reader%loaded))
      read(reader%unit,iostat=ios) reader%block(1:count)
      if (ios/=0) then
        call fail(status,CUBE_IO_ERROR,'Failed while reading CUBE stream',reader%line)
        return
      end if
      reader%loaded=reader%loaded+int(count,int64)
      reader%filled=count; reader%cursor=1
    end if
    ch=reader%block(reader%cursor:reader%cursor)
    ended=.false.
  end subroutine

  subroutine take(reader, ch, ended, status)
    type(cube_reader), intent(inout) :: reader
    character, intent(out) :: ch
    logical, intent(out) :: ended
    type(cube_status), intent(inout) :: status
    character :: next
    logical :: last
    call peek(reader,ch,ended,status)
    if (ended) return
    reader%cursor=reader%cursor+1
    if (ch==achar(13)) then
      call peek(reader,next,last,status)
      if (.not.last) then
        if (next==achar(10)) reader%cursor=reader%cursor+1
      end if
      ch=achar(10)
    end if
    if (ch==achar(10)) reader%line=reader%line+1_int64
  end subroutine

  subroutine skip_comment(reader,status)
    type(cube_reader), intent(inout) :: reader
    type(cube_status), intent(inout) :: status
    character :: ch
    logical :: ended
    do
      call take(reader,ch,ended,status)
      if (status%code/=CUBE_OK) return
      if (ended) then
        call fail(status,CUBE_MISSING_TOKEN,'Missing one of the two comment records',reader%line)
        return
      end if
      if (ch==achar(10)) exit
    end do
  end subroutine

  subroutine token(reader,word,found,status,record_only)
    type(cube_reader), intent(inout) :: reader
    character(len=*), intent(out) :: word
    logical, intent(out) :: found
    type(cube_status), intent(inout) :: status
    logical, intent(in) :: record_only
    character :: ch
    logical :: ended
    integer :: n
    word=''; found=.false.; n=0
    do
      call peek(reader,ch,ended,status)
      if (ended.or.status%code/=CUBE_OK) return
      if (ch==' '.or.ch==achar(9)) then
        call take(reader,ch,ended,status)
      else if (ch==achar(10).or.ch==achar(13)) then
        call take(reader,ch,ended,status)
        if (record_only) return
      else
        exit
      end if
    end do
    do
      call peek(reader,ch,ended,status)
      if (ended.or.status%code/=CUBE_OK) exit
      if (ch==' '.or.ch==achar(9).or.ch==achar(10).or.ch==achar(13)) exit
      if (n>=len(word)) then
        call fail(status,CUBE_TOKEN_TOO_LONG,'Numeric token exceeds 256 characters',reader%line)
        return
      end if
      call take(reader,ch,ended,status)
      n=n+1; word(n:n)=ch
    end do
    found=(n>0)
  end subroutine

  subroutine need_token(reader,word,status,record_only)
    type(cube_reader), intent(inout) :: reader
    character(len=*), intent(out) :: word
    type(cube_status), intent(inout) :: status
    logical, intent(in) :: record_only
    logical :: found
    if (status%code/=CUBE_OK) then
      word=''; return
    end if
    call token(reader,word,found,status,record_only)
    if (.not.found) call fail(status,CUBE_MISSING_TOKEN,'Missing required numeric token',reader%line)
  end subroutine

  logical function digit(ch)
    character, intent(in) :: ch
    digit=(ch>='0'.and.ch<='9')
  end function

  subroutine integer_value(word,value,status,line)
    character(len=*), intent(in) :: word
    integer(int64), intent(out) :: value
    type(cube_status), intent(inout) :: status
    integer(int64), intent(in) :: line
    integer :: i,n,ios
    value=0_int64
    if (status%code/=CUBE_OK) return
    n=len_trim(word); i=1
    if (n>0) then
      if (word(1:1)=='+'.or.word(1:1)=='-') i=2
    end if
    if (i>n) then
      call fail(status,CUBE_INVALID_INTEGER,'Malformed integer token',line); return
    end if
    do while(i<=n)
      if (.not.digit(word(i:i))) then
        call fail(status,CUBE_INVALID_INTEGER,'Malformed integer token',line); return
      end if
      i=i+1
    end do
    read(word,*,iostat=ios) value
    if (ios/=0) call fail(status,CUBE_OVERFLOW,'Integer token exceeds int64 range',line)
  end subroutine

  subroutine real_value(word,value,status,line)
    character(len=*), intent(in) :: word
    real(cube_dp), intent(out) :: value
    type(cube_status), intent(inout) :: status
    integer(int64), intent(in) :: line
    character(len=len(word)) :: lowered
    integer :: i,n,nd,ios,code
    value=0.0_cube_dp
    if (status%code/=CUBE_OK) return
    n=len_trim(word); lowered=word
    do i=1,n
      code=iachar(lowered(i:i))
      if (code>=iachar('A').and.code<=iachar('Z')) lowered(i:i)=achar(code+32)
    end do
    i=1
    if (n>0) then
      if (lowered(1:1)=='+'.or.lowered(1:1)=='-') i=2
    end if
    if (lowered(i:)=='nan'.or.lowered(i:)=='inf'.or.lowered(i:)=='infinity') then
      call fail(status,CUBE_NONFINITE,'Nonfinite numeric token is not allowed',line); return
    end if
    nd=0
    do while(i<=n)
      if (.not.digit(word(i:i))) exit
      nd=nd+1; i=i+1
    end do
    if (i<=n) then
      if (word(i:i)=='.') then
        i=i+1
        do while(i<=n)
          if (.not.digit(word(i:i))) exit
          nd=nd+1; i=i+1
        end do
      end if
    end if
    if (nd==0) then
      call fail(status,CUBE_INVALID_REAL,'Malformed real token',line); return
    end if
    if (i<=n) then
      if (scan(word(i:i),'eEdD')>0) then
        i=i+1
        if (i<=n) then
          if (word(i:i)=='+'.or.word(i:i)=='-') i=i+1
        end if
        nd=0
        do while(i<=n)
          if (.not.digit(word(i:i))) exit
          nd=nd+1; i=i+1
        end do
        if (nd==0) i=-1
      end if
    end if
    if (i/=n+1) then
      call fail(status,CUBE_INVALID_REAL,'Malformed real token',line); return
    end if
    read(word,*,iostat=ios) value
    if (ios/=0) then
      call fail(status,CUBE_INVALID_REAL,'Real token is outside supported binary64 range',line)
    else if (.not.ieee_is_finite(value)) then
      call fail(status,CUBE_NONFINITE,'Nonfinite real value is not allowed',line)
    end if
  end subroutine

  subroutine get_integer(reader,value,status)
    type(cube_reader), intent(inout) :: reader
    integer(int64), intent(out) :: value
    type(cube_status), intent(inout) :: status
    character(len=token_size) :: word
    call need_token(reader,word,status,.true.)
    call integer_value(word,value,status,reader%line)
  end subroutine

  subroutine get_real(reader,value,status,record_only)
    type(cube_reader), intent(inout) :: reader
    real(cube_dp), intent(out) :: value
    type(cube_status), intent(inout) :: status
    logical, intent(in) :: record_only
    character(len=token_size) :: word
    call need_token(reader,word,status,record_only)
    call real_value(word,value,status,reader%line)
  end subroutine

  subroutine record_end(reader,status)
    type(cube_reader), intent(inout) :: reader
    type(cube_status), intent(inout) :: status
    character(len=token_size) :: word
    logical :: found
    if (status%code/=CUBE_OK) return
    call token(reader,word,found,status,.true.)
    if (found) call fail(status,CUBE_EXTRA_TOKEN,'Unexpected token in header/atom record',reader%line)
  end subroutine

  subroutine checked_product(a,b,result,status)
    integer(int64), intent(in) :: a,b
    integer(int64), intent(out) :: result
    type(cube_status), intent(inout) :: status
    result=0_int64
    if (status%code/=CUBE_OK) return
    if (a<0_int64.or.b<0_int64) then
      call fail(status,CUBE_OVERFLOW,'Negative allocation length'); return
    end if
    if (b>0_int64) then
      if (a>huge(a)/b) then
        call fail(status,CUBE_OVERFLOW,'Array count or byte product exceeds int64 range'); return
      end if
    end if
    result=a*b
  end subroutine

  subroutine check_budget(grid,limits,status)
    type(cube_grid), intent(inout) :: grid
    type(cube_read_limits), intent(in) :: limits
    type(cube_status), intent(inout) :: status
    type(cube_atom) :: atom_size_probe
    integer(int64) :: count,rho_bytes,atom_bytes,bytes
    integer :: axis
    count=1_int64
    do axis=1,3
      call checked_product(count,grid%shape(axis),bytes,status)
      if (status%code/=CUBE_OK) return
      count=bytes
    end do
    grid%npoints=count
    call checked_product(count,int(storage_size(0.0_cube_dp)/8,int64),rho_bytes,status)
    call checked_product(grid%natoms,int(storage_size(atom_size_probe)/8,int64),atom_bytes,status)
    if (status%code/=CUBE_OK) return
    if (rho_bytes>huge(bytes)-int(block_size,int64)) then
      call fail(status,CUBE_OVERFLOW,'Total allocation byte count overflows'); return
    end if
    bytes=rho_bytes+int(block_size,int64)
    if (atom_bytes>huge(bytes)-bytes) then
      call fail(status,CUBE_OVERFLOW,'Total allocation byte count overflows'); return
    end if
    bytes=bytes+atom_bytes
    if (count>limits%max_points.or.bytes>limits%max_bytes) &
      call fail(status,CUBE_MEMORY_LIMIT,'Declared grid/atoms exceed caller memory or point budget')
  end subroutine

  subroutine check_geometry(grid,status)
    type(cube_grid), intent(inout) :: grid
    type(cube_status), intent(inout) :: status
    real(cube_dp) :: a(3,3), b(3,3), col(3), scale, alpha,beta,gamma,tau,t,c,s
    real(cube_dp) :: norms(3), determinant, volume
    integer :: sweep,p,q
    logical :: changed
    scale=maxval(abs(grid%j))
    if (scale==0.0_cube_dp) then
      call fail(status,CUBE_GRID_SINGULAR,'Grid step matrix is singular'); return
    end if
    a=grid%j/scale; b=a
    ! One-sided Jacobi SVD avoids squaring the condition number in J^T J.
    do sweep=1,50
      changed=.false.
      do p=1,2
        do q=p+1,3
          alpha=dot_product(b(:,p),b(:,p)); beta=dot_product(b(:,q),b(:,q))
          gamma=dot_product(b(:,p),b(:,q))
          if (alpha==0.0_cube_dp.or.beta==0.0_cube_dp) cycle
          if (abs(gamma)<=16.0_cube_dp*epsilon(scale)*sqrt(alpha)*sqrt(beta)) cycle
          tau=(beta-alpha)/(2.0_cube_dp*gamma)
          if (abs(tau)>1.0e150_cube_dp) then
            t=0.5_cube_dp/tau
          else
            t=sign(1.0_cube_dp,tau)/(abs(tau)+sqrt(1.0_cube_dp+tau*tau))
          end if
          c=1.0_cube_dp/sqrt(1.0_cube_dp+t*t); s=c*t
          col=b(:,p); b(:,p)=c*col-s*b(:,q); b(:,q)=s*col+c*b(:,q)
          changed=.true.
        end do
      end do
      if (.not.changed) exit
    end do
    if (changed) then
      call fail(status,CUBE_GRID_RANGE,'Grid SVD did not converge in 50 sweeps'); return
    end if
    do p=1,3
      norms(p)=sqrt(dot_product(b(:,p),b(:,p)))
    end do
    if (minval(norms)==0.0_cube_dp) then
      call fail(status,CUBE_GRID_SINGULAR,'Grid step matrix is singular'); return
    end if
    ! Ratio comparison also rejects rank-deficient grids before forming inverse.
    if (minval(norms)<maxval(norms)/1000.0_cube_dp) then
      call fail(status,CUBE_GRID_CONDITION,'Grid condition number exceeds 1000'); return
    end if
    grid%condition2=maxval(norms)/minval(norms)
    grid%j_inv(1,:)=[a(2,2)*a(3,3)-a(2,3)*a(3,2), &
      a(1,3)*a(3,2)-a(1,2)*a(3,3),a(1,2)*a(2,3)-a(1,3)*a(2,2)]
    grid%j_inv(2,:)=[a(2,3)*a(3,1)-a(2,1)*a(3,3), &
      a(1,1)*a(3,3)-a(1,3)*a(3,1),a(1,3)*a(2,1)-a(1,1)*a(2,3)]
    grid%j_inv(3,:)=[a(2,1)*a(3,2)-a(2,2)*a(3,1), &
      a(1,2)*a(3,1)-a(1,1)*a(3,2),a(1,1)*a(2,2)-a(1,2)*a(2,1)]
    determinant=dot_product(a(1,:),grid%j_inv(:,1))
    if (determinant==0.0_cube_dp) then
      call fail(status,CUBE_GRID_SINGULAR,'Grid step matrix has zero determinant'); return
    end if
    grid%j_inv=(grid%j_inv/determinant)/scale
    if (.not.all(ieee_is_finite(grid%j_inv))) then
      call fail(status,CUBE_GRID_RANGE,'Grid inverse is outside binary64 range'); return
    end if
    volume=abs(determinant)
    do p=1,3
      if (scale>1.0_cube_dp) then
        if (volume>huge(scale)/scale) then
          call fail(status,CUBE_GRID_RANGE,'Grid voxel volume overflows binary64'); return
        end if
      end if
      volume=volume*scale
    end do
    if (.not.ieee_is_finite(volume).or.volume==0.0_cube_dp) then
      call fail(status,CUBE_GRID_RANGE,'Grid voxel volume is outside binary64 range'); return
    end if
    grid%volume_element=volume
  end subroutine

  subroutine read_cube(path,grid,status,limits)
    character(len=*), intent(in) :: path
    type(cube_grid), intent(out) :: grid
    type(cube_status), intent(out) :: status
    type(cube_read_limits), intent(in), optional :: limits
    type(cube_read_limits) :: active_limits
    type(cube_reader) :: reader
    integer :: ios, close_ios
    integer(int64) :: final_bytes
    status=cube_status(); active_limits=cube_read_limits()
    if (present(limits)) active_limits=limits
    if (active_limits%max_bytes<=0_int64.or.active_limits%max_points<=0_int64) then
      call fail(status,CUBE_MEMORY_LIMIT,'Caller byte and point budgets must be positive'); return
    end if
    open(newunit=reader%unit,file=path,status='old',action='read',access='stream',form='unformatted',iostat=ios)
    if (ios/=0) then
      call fail(status,CUBE_IO_ERROR,'Cannot open CUBE input for reading'); return
    end if
    inquire(unit=reader%unit,size=reader%file_bytes,iostat=ios)
    if (ios/=0.or.reader%file_bytes<0_int64) then
      call fail(status,CUBE_IO_ERROR,'Cannot determine CUBE input byte length')
    else
      call read_body(reader,grid,active_limits,status)
    end if
    if (status%code==CUBE_OK) then
      inquire(unit=reader%unit,size=final_bytes,iostat=ios)
      if (ios/=0) then
        call fail(status,CUBE_IO_ERROR,'Cannot recheck input length after parsing')
      else if (final_bytes/=reader%file_bytes) then
        call fail(status,CUBE_IO_ERROR,'Input byte length changed during parsing')
      end if
    end if
    close(reader%unit,iostat=close_ios)
    if (close_ios/=0) call fail(status,CUBE_IO_ERROR,'Failed closing CUBE input')
    if (status%code/=CUBE_OK) then
      call clear_cube(grid)
    else
      grid%structurally_valid=.true.
    end if
  end subroutine

  subroutine read_body(reader,grid,limits,status)
    type(cube_reader), intent(inout) :: reader
    type(cube_grid), intent(inout) :: grid
    type(cube_read_limits), intent(in) :: limits
    type(cube_status), intent(inout) :: status
    character(len=token_size) :: word
    logical :: found
    integer :: i,axis,ios
    integer(int64) :: nval,z,atom,point
    call skip_comment(reader,status); call skip_comment(reader,status)
    call get_integer(reader,grid%natoms,status)
    if (status%code/=CUBE_OK) return
    if (grid%natoms<0_int64) then
      call fail(status,CUBE_UNSUPPORTED,'Negative NATOMS/multi-orbital CUBE is unsupported',reader%line); return
    end if
    do i=1,3
      call get_real(reader,grid%origin(i),status,.true.)
    end do
    if (status%code/=CUBE_OK) return
    call token(reader,word,found,status,.true.)
    if (found) then
      call integer_value(word,nval,status,reader%line)
      if (status%code/=CUBE_OK) return
      if (nval/=1_int64) then
        call fail(status,CUBE_UNSUPPORTED,'Only one scalar field (NVAL=1) is supported',reader%line); return
      end if
      call record_end(reader,status)
    end if
    do axis=1,3
      call get_integer(reader,grid%shape(axis),status)
      if (status%code/=CUBE_OK) return
      if (grid%shape(axis)<0_int64) then
        call fail(status,CUBE_UNSUPPORTED,'Negative axis counts/unit extensions are unsupported',reader%line); return
      else if (grid%shape(axis)<5_int64) then
        call fail(status,CUBE_DIMENSION,'Each axis needs at least five independent samples',reader%line); return
      end if
      do i=1,3
        call get_real(reader,grid%j(i,axis),status,.true.)
      end do
      call record_end(reader,status)
    end do
    if (status%code/=CUBE_OK) return
    call check_budget(grid,limits,status)
    if (status%code/=CUBE_OK) return
    call check_geometry(grid,status)
    if (status%code/=CUBE_OK) return
    allocate(grid%atoms(grid%natoms),stat=ios)
    if (ios/=0) then
      call fail(status,CUBE_ALLOCATION,'Cannot allocate atom records'); return
    end if
    do atom=1_int64,grid%natoms
      call get_integer(reader,z,status)
      if (status%code/=CUBE_OK) return
      if (z<1_int64.or.z>118_int64) then
        call fail(status,CUBE_INVALID_ATOM,'Atomic number must be in 1..118; dummy atoms unsupported',reader%line); return
      end if
      grid%atoms(atom)%atomic_number=int(z)
      call get_real(reader,grid%atoms(atom)%charge,status,.true.)
      do i=1,3
        call get_real(reader,grid%atoms(atom)%position(i),status,.true.)
      end do
      call record_end(reader,status)
      if (status%code/=CUBE_OK) return
    end do
    allocate(grid%rho(grid%npoints),stat=ios)
    if (ios/=0) then
      call fail(status,CUBE_ALLOCATION,'Cannot allocate density samples'); return
    end if
    do point=1_int64,grid%npoints
      call get_real(reader,grid%rho(point),status,.false.)
      if (status%code/=CUBE_OK) return
    end do
    call token(reader,word,found,status,.false.)
    if (found) call fail(status,CUBE_EXTRA_TOKEN,'Extra token after Nx*Ny*Nz scalar samples',reader%line)
  end subroutine

  subroutine validate_cube_metadata(grid,metadata,status)
    type(cube_grid), intent(inout) :: grid
    type(cube_metadata), intent(in) :: metadata
    type(cube_status), intent(out) :: status
    integer :: axis
    status=cube_status(); grid%metadata_validated=.false.
    grid%scientifically_certified=.false.
    if (.not.grid%structurally_valid.or..not.allocated(grid%rho)) then
      call fail(status,CUBE_INVALID_METADATA,'Parse a structurally valid CUBE first'); return
    end if
    if (metadata%quantity/='electron_density'.or.metadata%spin_convention/='spin_summed') then
      call fail(status,CUBE_INVALID_METADATA,'Explicit spin-summed electron_density declaration required'); return
    end if
    select case(trim(metadata%density_representation))
    case('all_electron','valence','core_augmented','promolecular')
    case default
      call fail(status,CUBE_INVALID_METADATA,'Explicit supported density_representation required'); return
    end select
    if (metadata%length_unit/='bohr'.or.metadata%density_unit/='electron/bohr^3') then
      call fail(status,CUBE_UNSUPPORTED_UNIT,'Only explicit bohr and electron/bohr^3 are supported; no guessed conversion'); return
    end if
    do axis=1,3
      select case(metadata%periodic(axis))
      case(0)
        if (metadata%endpoint_convention(axis)/='finite_nodes') then
          call fail(status,CUBE_INVALID_METADATA,'Finite axes require finite_nodes endpoint declaration'); return
        end if
      case(1)
        if (metadata%endpoint_convention(axis)/='independent_samples') then
          call fail(status,CUBE_INVALID_METADATA,'Periodic axes require independent_samples; no endpoint removal'); return
        end if
      case default
        call fail(status,CUBE_INVALID_METADATA,'Every axis must explicitly declare periodic=0 or 1'); return
      end select
    end do
    if (.not.ieee_is_finite(metadata%negative_tolerance).or.metadata%negative_tolerance<0.0_cube_dp) then
      call fail(status,CUBE_INVALID_METADATA,'negative_tolerance must be finite and nonnegative'); return
    end if
    if (.not.all(ieee_is_finite(grid%rho))) then
      call fail(status,CUBE_NONFINITE,'Nonfinite sample found at metadata validation'); return
    end if
    if (any(grid%rho < -metadata%negative_tolerance)) then
      call fail(status,CUBE_INVALID_DENSITY,'Density below declared negative tolerance; original samples retained'); return
    end if
    grid%metadata_validated=.true.
  end subroutine
end module
