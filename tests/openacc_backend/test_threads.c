/* SPDX-License-Identifier: MIT */
/* Actual shared-library public ABI. Two contexts, six finite evaluations.
 * No serial candidate output supplies mathematical truth. */
#define _GNU_SOURCE
#include "nci_api.h"
#include <dlfcn.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <unistd.h>

extern void nci_test_runtime_host(void);
extern void nci_test_runtime_state(int32_t *kind,int32_t *number);
static int32_t host_kind,host_number;
static unsigned event_sequence;
static atomic_int abort_jobs;

static int is_restored(void) {
    int32_t kind,number;nci_test_runtime_state(&kind,&number);
    return kind==host_kind && number==host_number;
}

#define N 315
#define GUARD UINT64_C(0x5a17c0def00d4829)
typedef struct {
    void *context;
    int id, diagnostic, constant, bad, repeats;
    const char *phase;
    pthread_barrier_t *barrier;
    nci_tile_v1 tile;
    uint64_t storage[6][6*N+2];
    uint8_t flag_storage[N+128];
    struct { uint64_t before; nci_tile_stats_v1 value; uint64_t after; } stats;
    double rho[N], rho_before[N];
} job;

static double *field(job *j, int k) { return (double *)(j->storage[k]+1); }
static uint8_t *flags(job *j) { return j->flag_storage+64; }
static uint64_t bits(double x) { uint64_t u; memcpy(&u,&x,8); return u; }
static int close_to(double x,double y,double atol,double rtol) {
    return isfinite(x) && fabs(x-y)<=atol+rtol*fabs(y);
}
static int check(job *j,int status) {
    if (status!=NCI_OK || memcmp(j->rho,j->rho_before,sizeof j->rho)) return 1;
    const int lengths[6]={N,N,N,3*N,6*N,N};
    for (int k=0;k<5;k++) {
        if (!j->diagnostic && k>=3) continue;
        if(j->storage[k][0]!=GUARD || j->storage[k][lengths[k]+1]!=GUARD) return 2;
    }
    for(int k=0;k<64;k++)
        if(j->flag_storage[k]!=0xd7 || j->flag_storage[N+64+k]!=0xd7) return 3;
    if(j->stats.before!=GUARD || j->stats.after!=GUARD) return 4;
    int64_t counts[7]={0},valid=0;
    int ny=(int)j->tile.global_n[1],nz=(int)j->tile.global_n[2];
    for(int p=0;p<N;p++) {
        int x=p/(ny*nz),y=(p/nz)%ny,z=p%nz;
        int boundary=x<2 || x>=j->tile.global_n[0]-2 || y<2 || y>=ny-2 || z<2 || z>=nz-2;
        int want=boundary?NCI_BOUNDARY:(NCI_LAMBDA_SCI_UNCERTAIN | (j->constant?NCI_LAMBDA_NUM_UNCERTAIN:0));
        if(flags(j)[p]!=want) return 5;
        for(int b=0;b<7;b++) counts[b]+=(want>>b)&1;
        if(boundary) {
            for(int k=0;k<(j->diagnostic?5:3);k++) {
                int components=k==3?3:k==4?6:1;
                for(int c=0;c<components;c++)
                    if(bits(field(j,k)[components*p+c])!=UINT64_C(0x7ff8000000000000)) return 6;
            }
        } else {
            valid++;
            double gx=.125-.5*(x-2),gy=-.25-.25*(y-2),gz=.5+.75*(z-2);
            double rdg=j->constant?0:sqrt(gx*gx+gy*gy+gz*gz)/(2*cbrt(3*acos(-1.)*acos(-1.))*pow(j->rho[p],4./3.));
            if(!close_to(field(j,0)[p],rdg,1e-11,1e-9) ||
               !close_to(field(j,2)[p],j->constant?0:-.25,1e-12,1e-10)) return 7;
            if(field(j,1)[p]!=(j->constant?0:-j->rho[p])) return 8;
            if(j->diagnostic) {
                const double g[3]={gx,gy,gz},h[6]={-.5,-.25,.75,0,0,0};
                for(int c=0;c<3;c++) if(!close_to(field(j,3)[3*p+c],j->constant?0:g[c],1e-12,1e-10)) return 9;
                for(int c=0;c<6;c++) if(!close_to(field(j,4)[6*p+c],j->constant?0:h[c],1e-12,1e-10)) return 10;
            }
        }
    }
    nci_tile_stats_v1 *s=&j->stats.value;
    if(s->total_points!=N || s->valid_points!=valid || s->invalid_points!=N-valid || s->numeric_failures!=0) return 11;
    if(memcmp(s->bit_counts,counts,sizeof counts)) return 12;
    return 0;
}

static void emit(job *j,int repeat,int status,const char *error) {
    flockfile(stdout);
    printf("{\"kind\":\"call\",\"phase\":\"%s\",\"job\":%d,\"repeat\":%d,\"thread\":%ld,\"status\":%d,\"check\":%d,\"diagnostic\":%d,\"shape\":[%lld,%lld,%lld],\"fields\":[",
           j->phase,j->id,repeat,(long)syscall(SYS_gettid),status,j->bad,j->diagnostic,
           (long long)j->tile.global_n[0],(long long)j->tile.global_n[1],(long long)j->tile.global_n[2]);
    for(int k=0;k<(j->diagnostic?5:3);k++) {
        int length=(k==3?3:k==4?6:1)*N;
        printf("%s\"",k?",":"");
        for(int p=0;p<length;p++) printf("%016llx",(unsigned long long)bits(field(j,k)[p]));
        printf("\"");
    }
    printf("],\"flags\":\"");
    for(int p=0;p<N;p++) printf("%02x",flags(j)[p]);
    printf("\",\"stats\":[%lld,%lld,%lld,%lld",(long long)j->stats.value.total_points,
        (long long)j->stats.value.valid_points,(long long)j->stats.value.invalid_points,
        (long long)j->stats.value.numeric_failures);
    for(int b=0;b<7;b++) printf(",%lld",(long long)j->stats.value.bit_counts[b]);
    printf("]}\n");
    fflush(stdout); funlockfile(stdout);
    if(status!=NCI_OK) fprintf(stderr,"thread public ABI failed: status %d, %s\n",status,error);
}

static void event(job *j,int repeat,const char *kind) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC,&now);
    flockfile(stdout);
    printf("{\"kind\":\"%s\",\"sequence\":%u,\"phase\":\"%s\",\"job\":%d,\"repeat\":%d,\"thread\":%ld,\"monotonic_ns\":%llu}\n",
           kind,++event_sequence,j->phase,j->id,repeat,
           (long)syscall(SYS_gettid),
           (unsigned long long)now.tv_sec*UINT64_C(1000000000)+(unsigned long long)now.tv_nsec);
    fflush(stdout);funlockfile(stdout);
}

static void *worker(void *arg) {
    job *j=arg;
    nci_test_runtime_host();
    if(!is_restored()) {j->bad=22;return NULL;}
    for(int r=0;r<j->repeats;r++) {
        char error[512]={0};
        const int lengths[5]={N,N,N,3*N,6*N};
        for(int k=0;k<5;k++) {
            memset(j->storage[k],0xa5,sizeof j->storage[k]);
            j->storage[k][0]=j->storage[k][lengths[k]+1]=GUARD;
        }
        memset(j->flag_storage,0xd7,sizeof j->flag_storage);
        memset(flags(j),0xa5,N);
        memset(&j->stats.value,0x3c,sizeof j->stats.value);
        j->stats.before=j->stats.after=GUARD;
        nci_tile_v1 before=j->tile;
        if(j->barrier) {
            event(j,r,"ready");
            int rc=pthread_barrier_wait(j->barrier);
            if(rc && rc!=PTHREAD_BARRIER_SERIAL_THREAD) { j->bad=20; return NULL; }
        }
        event(j,r,"begin");
        int status=nci_eval_tile_f64_v1(j->context,&j->tile,j->rho,field(j,0),field(j,1),field(j,2),
            j->diagnostic?field(j,3):NULL,j->diagnostic?field(j,4):NULL,flags(j),&j->stats.value,error,sizeof error);
        event(j,r,"end");
        j->bad=check(j,status);
        if(!is_restored()) j->bad=23;
        if(memcmp(&before,&j->tile,sizeof before)) j->bad=21;
        emit(j,r,status,error);
        if(j->bad) atomic_store(&abort_jobs,1);
        if(j->barrier) {
            int rc=pthread_barrier_wait(j->barrier);
            if(rc && rc!=PTHREAD_BARRIER_SERIAL_THREAD) { j->bad=20; return NULL; }
        }
        if(atomic_load(&abort_jobs)) break;
    }
    return NULL;
}

static int prepare(job *j,int id) {
    memset(j,0,sizeof *j);
    j->id=id;j->diagnostic=id==0;j->constant=id==1;j->repeats=2;j->phase="concurrent";
    nci_options_v1 options={1,sizeof options,NCI_OPENACC,j->diagnostic?NCI_DIAGNOSTIC:NCI_FULL,1,0,1e-8,0};
    nci_tile_v1 *t=&j->tile;
    t->abi_version=1;t->struct_bytes=sizeof *t;
    t->global_n[0]=id?7:5;t->global_n[1]=id?5:7;t->global_n[2]=9;
    for(int k=0;k<3;k++) t->tile_count[k]=t->input_shape[k]=t->global_n[k];
    t->input_strides[0]=t->global_n[1]*9;t->input_strides[1]=9;t->input_strides[2]=1;
    t->j_inv[0]=t->j_inv[4]=t->j_inv[8]=1;
    t->rho_capacity=t->field_capacity=t->flags_capacity=N;
    t->grad_capacity=j->diagnostic?3*N:0;t->hess_capacity=j->diagnostic?6*N:0;
    for(int p=0;p<N;p++) {
        double x=p/(t->global_n[1]*9)-2,y=(p/9)%t->global_n[1]-2,z=p%9-2;
        j->rho[p]=j->constant?.125:20+.125*x-.25*y+.5*z+(-.5*x*x-.25*y*y+.75*z*z)/2;
    }
    memcpy(j->rho_before,j->rho,sizeof j->rho);
    char error[512]={0};
    int status=nci_context_create_v1(&options,&j->context,error,sizeof error);
    if(!is_restored()) return 1;
    if(status!=NCI_OK || !j->context) fprintf(stderr,"create failed %d: %s\n",status,error);
    return status==NCI_OK && j->context?0:1;
}

int main(int argc,char **argv) {
    if(argc==2 && strcmp(argv[1],"--describe")==0) {
        puts("{\"state\":\"PREPARED_NOT_EXECUTED\",\"evaluations\":6,\"max_live_contexts\":2}");return 0;
    }
    if(argc!=1) return 2;
    nci_test_runtime_host();nci_test_runtime_state(&host_kind,&host_number);
    Dl_info info;
    if(!dladdr((void *)nci_context_create_v1,&info) || !info.dli_fname) return 2;
    printf("{\"kind\":\"library\",\"path\":\"%s\",\"main_thread\":%ld,\"evaluations\":6}\n",info.dli_fname,(long)syscall(SYS_gettid));
    static job a,b;
    if(prepare(&a,0)) return 1;
    if(prepare(&b,1)) { nci_context_destroy_v1(a.context,NULL,0);return 1; }
    pthread_barrier_t barrier;
    if(pthread_barrier_init(&barrier,NULL,2)) return 1;
    a.barrier=b.barrier=&barrier;
    pthread_t ta,tb;
    if(pthread_create(&ta,NULL,worker,&a)) return 1;
    if(pthread_create(&tb,NULL,worker,&b)) return 1;
    pthread_join(ta,NULL);pthread_join(tb,NULL);pthread_barrier_destroy(&barrier);
    if(a.bad || b.bad) return 1;
    a.barrier=NULL;a.repeats=1;a.phase="migration-new-thread";
    if(pthread_create(&ta,NULL,worker,&a)) return 1;
    pthread_join(ta,NULL);
    if(a.bad) return 1;
    a.phase="migration-main-thread";worker(&a);
    if(a.bad) return 1;
    int sa=nci_context_destroy_v1(a.context,NULL,0);
    if(sa!=NCI_OK || !is_restored()) return 1;
    int sb=nci_context_destroy_v1(b.context,NULL,0);
    if(sb!=NCI_OK || !is_restored()) return 1;
    puts("{\"kind\":\"end\",\"evaluations\":6,\"live_contexts\":0}");
    return 0;
}
