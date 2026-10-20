#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run one build-evidence command with a timeout and keep what it printed.

Usage: run_logged.py LOG_DIR TIMEOUT_SECONDS -- ARGV...

LOG_DIR must not exist yet (one directory per step). It receives command.json
(argv, cwd, UTC start stamp, timeout, exit status), stdout.txt and stderr.txt.
No shell is involved and no duration is recorded. On timeout the command's
own process group is killed and the exit status is 124. Intended for
configure/build/inspection steps, not for the probe executables.
"""
import datetime
import json
import os
import signal
import subprocess
import sys


def main():
    if len(sys.argv) < 5 or sys.argv[3] != "--":
        sys.exit(__doc__)
    log_dir, timeout, argv = sys.argv[1], float(sys.argv[2]), sys.argv[4:]
    os.makedirs(log_dir)
    record = {
        "argv": argv,
        "cwd": os.getcwd(),
        "started_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeout_seconds": timeout,
    }
    with open(os.path.join(log_dir, "stdout.txt"), "wb") as out, \
            open(os.path.join(log_dir, "stderr.txt"), "wb") as err:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                 start_new_session=True)
        try:
            status = child.wait(timeout=timeout)
            record["timed_out"] = False
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            status = 124
            record["timed_out"] = True
    record["exit_status"] = status
    with open(os.path.join(log_dir, "command.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"exit_status={status} timed_out={record['timed_out']} log_dir={log_dir}")
    sys.exit(status if 0 <= status < 256 else 1)


if __name__ == "__main__":
    main()
