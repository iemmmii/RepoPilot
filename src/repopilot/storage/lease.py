import os
from pathlib import Path

from repopilot.domain.errors import RepoPilotError


class RunLease:
    """Kernel-owned lock. Its stable file is never unlinked while writers may contend."""

    def __init__(self, root: Path):
        path = root / ".run.lock"
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise RepoPilotError("unsafe_lock_path", "Run lock must not be a link.")
        self.stream = path.open("a+b")
        try:
            if self.stream.tell() == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            raise RepoPilotError(
                "run_locked", "Another writer holds this Run; no lock was stolen."
            ) from error

    def close(self):
        # Closing releases the OS lock, including on abnormal process termination.
        self.stream.close()
