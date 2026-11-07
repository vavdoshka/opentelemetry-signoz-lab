"""Streams this node's kernel log to stdout, so the node agent collects it like any pod log.

The OpenTelemetry collector can't read the kernel log itself: the journald
receiver needs journalctl, which its image doesn't have. This is the kernel's
own record of OOM kills, with the process and its container.

Reads /dev/kmsg from its end, so a restart doesn't replay old messages.
"""

import errno
import os

LEVELS = ["EMERG", "ALERT", "CRIT", "ERROR", "WARN", "NOTICE", "INFO", "DEBUG"]

fd = os.open("/dev/kmsg", os.O_RDONLY)
os.lseek(fd, 0, os.SEEK_END)
while True:
    try:
        record = os.read(fd, 8192).decode(errors="replace")
    except OSError as error:
        if error.errno == errno.EPIPE:
            continue  # Older messages were overwritten before they were read.
        raise
    # Each record is "priority,sequence,microseconds,flags;message".
    header, _, message = record.partition(";")
    level = LEVELS[int(header.split(",")[0]) & 7]
    print(f"{level} {message.splitlines()[0]}", flush=True)
