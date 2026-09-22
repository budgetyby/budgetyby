"""
BudgetBy — Automatic GitHub Sync Runner & Live Console Monitor.
Runs `budgetby.main` directly in the active terminal with full live streaming output.
Background thread checks `git fetch origin main` every 30 seconds.
When a new commit is detected on GitHub:
1. Gracefully stops the current engine process.
2. Runs `git pull origin main`.
3. If requirements.txt changed, updates dependencies.
4. Seamlessly re-launches the engine in the SAME terminal window.
Zero blank screens, zero orphaned windows, full real-time console visibility.
"""

import os
import sys
import time
import shutil
import logging
import ctypes
import threading
import subprocess
import psutil

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "sync_watcher.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SyncWatcher] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("auto_sync_runner")

CHECK_INTERVAL = 30  # seconds


def find_git() -> str:
    """Finds working git executable on system."""
    candidates = [
        shutil.which("git"),
        r"C:\Users\jay\AppData\Local\Programs\Git\cmd\git.exe",
        r"C:\Program Files\Git\cmd\git.exe",
        "git"
    ]
    for cand in candidates:
        if cand and (os.path.exists(cand) or shutil.which(cand)):
            try:
                res = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    return cand
            except Exception:
                continue
    return "git"


def find_python() -> str:
    """Finds working python executable."""
    candidates = [
        sys.executable,
        r"C:\Users\jay\AppData\Local\Programs\Python\Python311\python.exe",
        r"C:\Program Files\Python311\python.exe",
        "python"
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return sys.executable


GIT_EXE = find_git()
PYTHON_EXE = find_python()


def prevent_windows_sleep():
    """Keep system awake while active."""
    if sys.platform == "win32":
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:
            pass


def get_commit_hash(ref: str) -> str:
    """Gets commit hash for given ref (HEAD, origin/main, etc)."""
    res = subprocess.run(
        [GIT_EXE, "rev-parse", ref],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=True
    )
    return res.stdout.strip()


def check_requirements_diff(old_commit: str, new_commit: str) -> bool:
    """Checks if requirements.txt changed between commits."""
    try:
        res = subprocess.run(
            [GIT_EXE, "diff", "--name-only", old_commit, new_commit],
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        return "requirements.txt" in res.stdout
    except Exception:
        return False


class EngineManager:
    """Manages the BudgetBy engine process with live console streaming and auto-sync."""
    
    def __init__(self):
        self.proc = None
        self.restart_requested = False
        self.lock = threading.Lock()
        self.running = True

    def stop_existing_orphans(self):
        """Kills any orphaned budgetby processes from previous runs."""
        my_pid = os.getpid()
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                if p.info['pid'] == my_pid:
                    continue
                cmdline = p.info.get('cmdline') or []
                cmd_str = " ".join(cmdline)
                if ("budgetby.main" in cmd_str or "run_local_daemon.py" in cmd_str) and "auto_sync_runner.py" not in cmd_str:
                    logger.info(f"Cleaning up orphaned instance (PID {p.info['pid']})...")
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.info['pid'])], capture_output=True)
                    else:
                        p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(1)

    def terminate_engine(self):
        """Terminates current engine process cleanly."""
        with self.lock:
            if self.proc and self.proc.poll() is None:
                pid = self.proc.pid
                logger.info(f"Stopping active engine process (PID {pid})...")
                try:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                    else:
                        self.proc.terminate()
                        try:
                            self.proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self.proc.kill()
                except Exception as e:
                    logger.warning(f"Process termination notice: {e}")
                self.proc = None
                time.sleep(2)

    def git_watcher_loop(self):
        """Background thread that polls GitHub every 30s."""
        logger.info(f"🔍 Background Git poller active (checking every {CHECK_INTERVAL}s)...")
        while self.running:
            try:
                prevent_windows_sleep()
                fetch_res = subprocess.run(
                    [GIT_EXE, "fetch", "origin", "main"],
                    cwd=BASE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=45
                )
                if fetch_res.returncode == 0:
                    local_hash = get_commit_hash("HEAD")
                    remote_hash = get_commit_hash("origin/main")

                    if local_hash != remote_hash:
                        logger.info(f"📢 New commit detected on GitHub: {local_hash[:7]} ➔ {remote_hash[:7]}")
                        self.restart_requested = True
                        
                        # Stop engine so git pull doesn't conflict
                        self.terminate_engine()
                        
                        # Pull latest code
                        logger.info("📥 Running git pull origin main...")
                        pull_res = subprocess.run(
                            [GIT_EXE, "pull", "origin", "main"],
                            cwd=BASE_DIR,
                            capture_output=True,
                            text=True
                        )
                        logger.info(f"Git pull: {pull_res.stdout.strip()}")
                        
                        # Check dependencies
                        if check_requirements_diff(local_hash, remote_hash):
                            logger.info("📦 requirements.txt changed. Installing updates...")
                            subprocess.run(
                                [PYTHON_EXE, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
                                cwd=BASE_DIR
                            )
                        
                        logger.info("✨ Code updated successfully! Engine will restart immediately.")
                        self.restart_requested = False
            except Exception as e:
                logger.error(f"Git watcher check error: {e}")

            time.sleep(CHECK_INTERVAL)

    def run(self):
        """Main process runner: starts engine and streams live output to console."""
        prevent_windows_sleep()
        self.stop_existing_orphans()

        # Start watcher thread
        watcher_thread = threading.Thread(target=self.git_watcher_loop, daemon=True)
        watcher_thread.start()

        cmd = [PYTHON_EXE, "-u", "-m", "budgetby.main"]

        while self.running:
            prevent_windows_sleep()
            logger.info(f"▶️ Starting BudgetBy Engine (Live Output Mode)...")
            logger.info("─" * 60)

            # Notice: stdout=None and stderr=None streams output LIVE to terminal!
            with self.lock:
                self.proc = subprocess.Popen(
                    cmd,
                    cwd=BASE_DIR,
                    stdout=None,
                    stderr=None
                )

            # Wait for process to exit or be restarted by watcher
            self.proc.wait()
            ret_code = self.proc.returncode

            if not self.running:
                break

            if self.restart_requested:
                logger.info("🔄 Applying git update restart...")
                time.sleep(1)
            else:
                if ret_code == 0:
                    logger.info("✅ Engine exited cleanly. Restarting in 5s...")
                else:
                    logger.warning(f"⚠️ Engine exited with code {ret_code}. Auto-restarting in 5s...")
                time.sleep(5)


def main():
    print("\n" + "=" * 64)
    print("   BUDGETBY LIVE TERMINAL RUNNER & AUTOMATIC SYNC WATCHER   ")
    print("=" * 64)
    print(f"Repository : {BASE_DIR}")
    print(f"Git Path   : {GIT_EXE}")
    print(f"Python     : {PYTHON_EXE}")
    print(f"Watch Loop : Every {CHECK_INTERVAL}s (Auto-pull from origin/main)")
    print("=" * 64 + "\n")

    manager = EngineManager()
    try:
        manager.run()
    except KeyboardInterrupt:
        logger.info("\n🛑 User pressed Ctrl+C. Stopping BudgetBy and watcher...")
        manager.running = False
        manager.terminate_engine()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
