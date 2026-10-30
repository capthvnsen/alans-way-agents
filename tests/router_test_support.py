"""Deadline-bound JSON frames from a subprocess's stdout pipe."""
import json
import os
import select
import time


def recv_json(proc, timeout=15, required=True):
    deadline = time.monotonic() + timeout
    pending = getattr(proc, "_rpc_stdout", b"")
    while b"\n" not in pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([proc.stdout], [], [], remaining)[0]:
            proc._rpc_stdout = pending
            if required:
                raise AssertionError(f"no complete JSON frame within {timeout}s ({len(pending)} bytes received)")
            return None
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            raise AssertionError(f"router stdout closed before a complete JSON frame ({len(pending)} bytes received)")
        pending += chunk
    line, proc._rpc_stdout = pending.split(b"\n", 1)
    return json.loads(line)
