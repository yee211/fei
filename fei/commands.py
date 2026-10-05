"""Foreground commands with output spooling and process-tree ownership."""
import ctypes
import os
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4
from fei import config

def decode_output(raw):
    """Prefer UTF-8; fall back to Windows ANSI code page, keeping raw logs intact."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        if os.name == "nt":
            import locale
            encoding = locale.getpreferredencoding(False)
            if encoding.lower().replace("-", "") == "utf8":
                encoding = "cp" + str(ctypes.windll.kernel32.GetACP())
            return raw.decode(encoding, errors="replace")
        return raw.decode("utf-8", errors="replace")


class WindowsJob:
    def __init__(self, process):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended(); limits.BasicLimitInformation.LimitFlags = 0x2000
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            error = ctypes.get_last_error(); self.close(); raise ctypes.WinError(error)
    def terminate(self):
        if self.handle: self.kernel.TerminateJobObject(self.handle, 1)
    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle); self.handle = None


def run_command(argv, *, shell=False, cwd=None, env=None, timeout=120, progress=None):
    directory = config.WORKDIR / ".fei-results"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"command-{uuid4().hex}.log"
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(argv, shell=shell, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, start_new_session=os.name != "nt")
    job = None
    reader = None
    done = threading.Event()
    reader_error = []
    latest = [""]
    started = time.monotonic()
    def terminate():
        if job:
            job.terminate()
        elif os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    try:
        if os.name == "nt": job = WindowsJob(process)
        def drain():
            try:
                with path.open("wb") as output:
                    while True:
                        chunk = process.stdout.read1(4096)
                        if not chunk: break
                        output.write(chunk); output.flush()
                        latest[0] = decode_output(chunk)[-300:]
            except Exception as exc:
                reader_error.append(exc)
            finally:
                done.set()
        reader = threading.Thread(target=drain, daemon=True); reader.start()
        if progress: progress(f"命令已启动，PID={process.pid}；完整输出：{path}")
        last_notice = started
        while process.poll() is None:
            now = time.monotonic()
            if now - started >= timeout:
                raise subprocess.TimeoutExpired(argv, timeout)
            if reader_error: raise reader_error[0]
            if progress and now - last_notice >= 2:
                progress(f"命令运行 {now-started:.1f}s；最新输出：{latest[0] or '(暂无输出)'}")
                last_notice = now
            time.sleep(0.05)
        # This is a foreground command: do not leave background descendants alive.
        terminate()
        if not done.wait(5): raise RuntimeError("Output reader failed to close after process-tree cleanup")
        if reader_error: raise reader_error[0]
        output = decode_output(path.read_bytes())
        return subprocess.CompletedProcess(argv, process.returncode, stdout=output, stderr="")
    except BaseException as exc:
        terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        if reader: done.wait(5)
        if hasattr(exc, "add_note"): exc.add_note(f"Partial command output: {path}")
        if isinstance(exc, subprocess.TimeoutExpired):
            partial = decode_output(path.read_bytes()) if path.exists() else ""
            raise RuntimeError(f"Command timed out after {timeout}s; process tree stopped. Full output: {path}\n{partial[-4000:]}") from exc
        raise
    finally:
        if job: job.close()
        if process.stdout: process.stdout.close()
        if reader: reader.join(timeout=1)
