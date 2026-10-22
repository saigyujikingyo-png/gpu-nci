/* Linux-only private persistence and first-result acknowledgement helpers. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int durable_fd(int fd) {
    int rc;
    do { rc = fsync(fd); } while (rc < 0 && errno == EINTR);
    return rc == 0 ? 0 : errno;
}

static int sync_names(const char *path, const char *const *names, size_t count) {
    int dir = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    int failure = 0;
    size_t i;
    if (dir < 0) return errno;
    for (i = 0; i < count && !failure; ++i) {
        struct stat status;
        int fd = openat(dir, names[i], O_RDONLY | O_NOFOLLOW);
        if (fd < 0) { failure = errno; break; }
        if (fstat(fd, &status) < 0) failure = errno;
        else if (!S_ISREG(status.st_mode)) failure = EINVAL;
        if (!failure) failure = durable_fd(fd);
        if (close(fd) < 0 && !failure) failure = errno;
    }
    if (!failure) failure = durable_fd(dir);
    if (close(dir) < 0 && !failure) failure = errno;
    return failure;
}

int nci_benchmark_sync_results(const char *path) {
    static const char *const names[] = {
        "rdg.f64", "lambda2.f64", "signedrho.f64", "flags.u8", "native.json"
    };
    return sync_names(path, names, sizeof names / sizeof names[0]);
}

int nci_benchmark_sync_report(const char *path) {
    static const char *const names[] = {"timing.json"};
    return sync_names(path, names, 1);
}

int nci_benchmark_mkdir(const char *path) {
    char *parent;
    char *slash;
    int fd, failure;
    if (mkdir(path, 0700) < 0) return errno;
    /* Persist the new repetition directory's entry in its parent as well. */
    parent = strdup(path);
    if (!parent) return ENOMEM;
    slash = strrchr(parent, '/');
    if (!slash) { free(parent); return EINVAL; }
    if (slash == parent) slash[1] = '\0';
    else *slash = '\0';
    fd = open(parent, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    free(parent);
    if (fd < 0) return errno;
    failure = durable_fd(fd);
    if (close(fd) < 0 && !failure) failure = errno;
    return failure;
}

int nci_benchmark_ack(void) {
    static const char ack[] = "NCI_BENCHMARK_FIRST_RESULT_ACK_V1\n";
    size_t done = 0;
    while (done < sizeof ack - 1) {
        ssize_t count = write(STDOUT_FILENO, ack + done, sizeof ack - 1 - done);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return count == 0 ? EIO : errno;
        done += (size_t) count;
    }
    return 0;
}
