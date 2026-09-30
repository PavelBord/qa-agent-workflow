"""Bounded subprocess waiting with progress and process-group cleanup (POSIX)."""
import os
import signal
import subprocess
import time


class RunInterrupted(RuntimeError):
    pass


def stop_process(process):
    # Every caller starts a new session: descendants share this process group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return process.communicate()


def wait_for_process(process, timeout_seconds, label, progress_seconds=15):
    started = time.monotonic()
    try:
        while True:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(label, timeout_seconds)
            try:
                return process.communicate(timeout=min(progress_seconds, remaining))
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                if elapsed >= timeout_seconds:
                    raise
                print(f'{label}: ожидание {elapsed:.0f} с / {timeout_seconds} с', flush=True)
    except subprocess.TimeoutExpired as error:
        stop_process(process)
        raise RuntimeError(f'{label}: timeout {timeout_seconds} секунд; процесс и его дочерние процессы остановлены') from error
    except KeyboardInterrupt as error:
        stop_process(process)
        raise RunInterrupted(f'{label}: прерван пользователем (Ctrl+C); процессы остановлены') from error
