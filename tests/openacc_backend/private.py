"""Frozen hook schema and an independent ownership state machine."""
import ctypes as ct
import numpy as np

VALUE_NAMES = ('schema_version call_ordinal planned_host planned_device peak_host peak_device '
    'final_host final_device peak_maps final_maps acquisition_attempts backend_status output_points '
    'kernels upload_count upload_bytes download_count download_bytes first_failure_global_index '
    'first_failure_status first_failure_nrot verified_markers broken event_count').split()


class Bridge:
    def __init__(self, library):
        self.configure_raw = library.nci_test_configure_v1
        self.configure_raw.argtypes = [ct.c_void_p,ct.c_int32,ct.c_int32,ct.POINTER(ct.c_int32)]
        self.configure_raw.restype = None
        self.observe_raw = library.nci_test_observe_v1
        self.observe_raw.argtypes = [ct.c_void_p,ct.POINTER(ct.c_int64),ct.POINTER(ct.c_int64),
                                    ct.POINTER(ct.c_int32),ct.POINTER(ct.c_int32)]
        self.observe_raw.restype = None

    def configure(self, recorder, handle, failure=0, corruption=0):
        rc=ct.c_int32(-999)
        self.configure_raw(handle,failure,corruption,ct.byref(rc))
        recorder.retain('private-configure',f'configure/{failure}/{corruption}',rc.value,'',
                        context_token=None if handle is None else handle.value)
        return rc.value

    def observe(self, recorder, handle):
        values, events = (ct.c_int64*24)(), (ct.c_int64*(6*256))()
        count, rc=ct.c_int32(-999),ct.c_int32(-999)
        self.observe_raw(handle,values,events,ct.byref(count),ct.byref(rc))
        # Fortran events(:,k): six adjacent values for each event.
        rows=np.ctypeslib.as_array(events).reshape(256,6).copy()
        snapshot=dict(values=list(values), events=rows.tolist(), n_events=count.value)
        recorder.retain('private-observe','observe',rc.value,'',observation=snapshot,
                        context_token=None if handle is None else handle.value)
        assert 0 <= count.value <= 256
        assert np.all(rows[count.value:] == 0), 'unused hook events must be zero'
        return rc.value, dict(zip(VALUE_NAMES,values)), rows[:count.value].tolist(), snapshot


def array_sizes(case):
    b,ny,nz=map(int,case.tile.tile_count)
    nin=int(np.prod(case.tile.input_shape,dtype=object))
    nout=b*ny*nz
    d=int(case.grad is not None)
    return {1:8*nin,2:40*b,3:40*ny,4:40*nz,5:(24+72*d)*nout,
            6:nout,7:4*nout,8:4*nout,9:4*nout}


def validate_ledger(values, rows, sizes, expected_status, failure=0):
    """Derive totals/lifetimes from actions; never trusts reported aggregate peaks."""
    assert set(values)==set(VALUE_NAMES) and all(type(v) is int for v in values.values())
    assert values['schema_version']==1
    assert values['event_count']==len(rows)<=256
    assert values['planned_host']==values['planned_device']==sum(sizes.values())
    assert values['backend_status']==expected_status
    assert values['broken']==0
    assert values['output_points']==sizes[6]
    assert all(type(size) is int and 0<size<=2147483647 for size in sizes.values())
    if expected_status != 4:
        assert (values['first_failure_global_index'],values['first_failure_status'],
                values['first_failure_nrot'])==(-1,0,0)
    else:
        assert values['first_failure_global_index']>=0
        assert 1<=values['first_failure_status']<=6 and 0<=values['first_failure_nrot']<=30
    host,device,mapped,moved=set(),set(),set(),set()
    peak_h=peak_d=peak_m=0
    uploads=[]; downloads=[]; kernels=0; acquired=[];freed_h=[];freed_d=[]
    for seq,row in enumerate(rows,1):
        assert len(row)==6 and all(type(v) is int for v in row)
        number,action,buffer,size,lh,ld=map(int,row)
        assert number==seq
        assert 1<=action<=11
        if action==5:
            assert buffer==size==0
            assert mapped==set(sizes), 'kernel before all mappings'
            assert set(uploads)==set(sizes), 'kernel before all input/poison uploads'
            kernels+=1
        else:
            assert buffer in sizes and size==sizes[buffer]
            if action==1:
                assert buffer not in host
                host.add(buffer); acquired.append(('h',buffer))
            elif action==2:
                assert buffer in host and buffer not in device
                device.add(buffer); acquired.append(('d',buffer))
                assert seq < len(rows) and rows[seq][1:3]==[3,buffer], 'map immediately after matching allocation'
            elif action==3:
                assert buffer in host & device and buffer not in mapped
                mapped.add(buffer)
            elif action==4:
                assert buffer in mapped and kernels==0
                uploads.append(buffer)
            elif action==6:
                assert buffer in mapped and kernels==1
                assert buffer in (5,6,7,8,9)
                downloads.append(buffer)
            elif action==7:
                assert buffer in mapped and buffer in host & device
                mapped.remove(buffer)
            elif action==8:
                assert buffer in device and buffer not in mapped
                device.remove(buffer)
                freed_d.append(buffer)
            elif action==9:
                assert buffer in host and buffer not in mapped|device|moved
                host.remove(buffer)
                freed_h.append(buffer)
            elif action==10:
                assert buffer in (5,6) and buffer in host and buffer not in mapped|device|moved
                assert not device|mapped and host <= {5,6}, 'move before precommit cleanup'
                moved.add(buffer)
            elif action==11:
                assert buffer in moved & host
                moved.remove(buffer); host.remove(buffer)
        expected_h=sum(sizes[x] for x in host)
        expected_d=sum(sizes[x] for x in device)
        assert lh==expected_h and ld==expected_d
        peak_h=max(peak_h,lh); peak_d=max(peak_d,ld); peak_m=max(peak_m,len(mapped))
    assert not host|device|mapped|moved
    assert values['final_host']==values['final_device']==values['final_maps']==0
    assert (values['peak_host'],values['peak_device'],values['peak_maps'])==(peak_h,peak_d,peak_m)
    assert values['kernels']==kernels
    assert values['upload_count']==len(uploads)
    assert values['download_count']==len(downloads)
    assert values['upload_bytes']==sum(sizes[x] for x in uploads)
    assert values['download_bytes']==sum(sizes[x] for x in downloads)
    wanted=[('h',x) for x in range(1,10)]+[('d',x) for x in range(1,10)]
    if failure:
        assert acquired==wanted[:failure-1]
        assert values['acquisition_attempts']==failure
        assert kernels==0 and not downloads
        assert values['verified_markers']==0
        assert freed_d==[buffer for side,buffer in reversed(acquired) if side=='d']
        assert freed_h==[buffer for side,buffer in reversed(acquired) if side=='h']
    else:
        assert acquired==wanted
        assert values['acquisition_attempts']==18 and kernels==1
        assert sorted(uploads)==list(range(1,10))
        assert sorted(downloads)==list(range(5,10))
        if expected_status in (0,3,4):assert values['verified_markers']==sizes[6]
    return values
