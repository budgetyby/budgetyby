"""
BudgetBy 24/7 Local Daemon Runner.
Includes Windows Keep-Awake flag and watchdog auto-restart.
"""
import sys
import os
import time
import signal
import subprocess
import logging
import ctypes
import psutil

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "bot_runner.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)
import io
if sys.platform == "win32" and sys.stdout and hasattr(sys.stdout, "buffer"):
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    console = logging.StreamHandler(utf8_stdout)
else:
    console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger("").addHandler(console)

def prevent_windows_sleep():
    """
    Prevents Windows from entering sleep/hibernation while the bot is active.
    ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
    Display is allowed to turn off to save energy.
    """
    if sys.platform == "win32":
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            logging.info("🔋 Windows Keep-Awake state active (System will not sleep while running).")
        except Exception as e:
            logging.warning(f"Could not set Windows execution state: {e}")


def cleanup_orphaned_instances():
    """
    Kills any duplicate or orphaned budgetby processes to guarantee
    that exactly ONE bot instance runs at any time (prevents Telegram 409 Conflict,
    SQLite session locks, and Port 5000 bind errors).
    """
    current_pid = os.getpid()
    killed = 0
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if p.info['pid'] == current_pid:
                continue
            cmd_args = p.info.get('cmdline') or []
            if not cmd_args:
                continue
            is_daemon = any(arg.endswith("run_local_daemon.py") for arg in cmd_args[:2])
            is_bot = any("budgetby.main" in arg for arg in cmd_args)
            if (is_bot or is_daemon) and p.info['pid'] != current_pid and p.info['pid'] != os.getppid():
                logging.warning(f"🧹 Terminating old/duplicate instance (PID {p.info['pid']})...")
                p.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if killed > 0:
        logging.info(f"✨ Cleaned up {killed} duplicate process(es). Waiting 2s for OS release...")
        time.sleep(2)


def terminate_process(proc: subprocess.Popen, timeout: int = 8):
    """
    Gracefully terminate the subprocess: SIGTERM first, then SIGKILL after timeout.
    Also kills the entire process tree on Windows to prevent zombie child procs.
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    except Exception as e:
        logging.warning(f"Error during process termination: {e}")


def main():
    logging.info("🚀 Starting BudgetBy Local Daemon Service...")
    prevent_windows_sleep()

    # Pre-boot: Kill any leftover duplicate instances
    cleanup_orphaned_instances()

    python_exe = sys.executable
    cmd = [python_exe, "-u", "-m", "budgetby.main"]
    proc = None

    while True:
        try:
            # Ensure no stray process before launching
            cleanup_orphaned_instances()

            logging.info(f"▶️ Launching BudgetBy Engine: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )

            for line in proc.stdout:
                line_str = line.strip()
                if line_str:
                    logging.info(f"[Bot] {line_str}")
                    try:
                        sys.stdout.flush()
                    except Exception:
                        pass

            proc.wait()
            ret_code = proc.returncode

            if ret_code == 0:
                logging.info("✅ BudgetBy stopped cleanly (code 0). Restarting in 5 seconds...")
            else:
                logging.warning(f"⚠️ BudgetBy process exited with code {ret_code}. Auto-restarting...")

            logging.info("⏳ Waiting 5 seconds before restart...")
            time.sleep(5)

        except KeyboardInterrupt:
            logging.info("🛑 Keyboard interrupt received. Stopping daemon.")
            terminate_process(proc)
            break
        except Exception as e:
            logging.error(f"❌ Daemon unexpected error: {e}. Restarting in 10 seconds...", exc_info=True)
            terminate_process(proc)
            time.sleep(10)


if __name__ == "__main__":
    main()

