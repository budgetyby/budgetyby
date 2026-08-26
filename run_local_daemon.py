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

BASE_DIR = r"c:\Users\jaysi\.gemini\antigravity\scratch\budget-by"
LOG_FILE = os.path.join(BASE_DIR, "bot_runner.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
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


def terminate_process(proc: subprocess.Popen, timeout: int = 8):
    """
    Gracefully terminate the subprocess: SIGTERM first, then SIGKILL after timeout.
    Also kills the entire process tree on Windows to prevent zombie child procs.
    """
    if proc is None or proc.poll() is not None:
        return  # Already dead
    try:
        if sys.platform == "win32":
            # taskkill /F /T kills the process AND all its children
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

    python_exe = sys.executable
    cmd = [python_exe, "-m", "budgetby.main"]
    proc = None

    while True:
        try:
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

            proc.wait()
            ret_code = proc.returncode

            if ret_code == 0:
                # Clean exit (Ctrl+C or graceful shutdown)
                logging.info("✅ BudgetBy stopped cleanly (code 0). Restarting in 10 seconds...")
            else:
                logging.warning(f"⚠️ BudgetBy process exited with code {ret_code}. Auto-restarting...")

            # CRITICAL: Wait long enough for OS to release port 5000 and
            # Telethon SQLite session lock before the new process starts.
            logging.info("⏳ Waiting 15 seconds for OS to release port and session locks...")
            time.sleep(15)

        except KeyboardInterrupt:
            logging.info("🛑 Keyboard interrupt received. Stopping daemon.")
            terminate_process(proc)
            break
        except Exception as e:
            logging.error(f"❌ Daemon unexpected error: {e}. Restarting in 15 seconds...", exc_info=True)
            terminate_process(proc)
            time.sleep(15)


if __name__ == "__main__":
    main()

