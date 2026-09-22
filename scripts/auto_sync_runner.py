"""
BudgetBy — Automatic GitHub Sync Watcher.
Checks `git fetch origin main` every 30 seconds.
When new commits are detected:
1. Stops existing daemon & bot instances.
2. Runs `git pull origin main`.
3. Installs any updated dependencies if requirements.txt changed.
4. Gracefully restarts run_local_daemon.py.
"""

import os
import sys
import time
import shutil
import logging
import ctypes
import subprocess
import psutil

# Ensure proper encoding on Windows console
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
    """Keep system awake while watcher is active."""
    if sys.platform == "win32":
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception as e:
            logger.debug(f"Keep-awake call notice: {e}")


def is_daemon_running() -> bool:
    """Checks if run_local_daemon.py or budgetby.main is running."""
    my_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['pid'] == my_pid:
                continue
            cmdline = proc.info.get('cmdline') or []
            cmd_str = " ".join(cmdline)
            if "run_local_daemon.py" in cmd_str or "budgetby.main" in cmd_str:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def stop_daemon_processes():
    """Terminates running run_local_daemon.py and budgetby.main processes and closes their windows."""
    my_pid = os.getpid()
    killed_any = False
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['pid'] == my_pid:
                continue
            cmdline = proc.info.get('cmdline') or []
            cmd_str = " ".join(cmdline)
            if "run_local_daemon.py" in cmd_str or "budgetby.main" in cmd_str:
                pid = proc.info['pid']
                logger.info(f"Terminating process and closing attached window (PID {pid})...")
                if sys.platform == "win32":
                    # /F = force, /T = terminate entire process tree (closes console/terminal window)
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                else:
                    proc.kill()
                killed_any = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if killed_any:
        time.sleep(2)
        logger.info("Processes and windows closed cleanly. Sockets and DB released.")


def start_daemon():
    """Starts run_local_daemon.py silently in background with NO blank popup window."""
    daemon_script = os.path.join(BASE_DIR, "run_local_daemon.py")
    cmd = [PYTHON_EXE, daemon_script]
    logger.info(f"▶️ Starting BudgetBy daemon (silent background): {' '.join(cmd)}")
    
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW prevents Windows from popping open empty/blank terminal windows
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        cmd,
        cwd=BASE_DIR,
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True
    )
    logger.info(f"🚀 Daemon started silently in background with PID {proc.pid}")
    return proc


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


def sync_and_restart():
    """Performs git pull and gracefully restarts daemon."""
    old_hash = get_commit_hash("HEAD")
    remote_hash = get_commit_hash("origin/main")
    
    logger.info(f"📢 New commit(s) detected on GitHub! {old_hash[:7]} ➔ {remote_hash[:7]}")
    
    # 1. Stop current running instances
    logger.info("🛑 Stopping existing bot daemon processes...")
    stop_daemon_processes()

    # 2. Pull latest code
    logger.info("📥 Executing git pull origin main...")
    pull_res = subprocess.run(
        [GIT_EXE, "pull", "origin", "main"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True
    )
    logger.info(f"Git pull output:\n{pull_res.stdout.strip()}")
    if pull_res.returncode != 0:
        logger.error(f"Git pull error:\n{pull_res.stderr.strip()}")

    # 3. Check if dependencies changed
    if check_requirements_diff(old_hash, remote_hash):
        logger.info("📦 requirements.txt changed. Updating python dependencies...")
        req_file = os.path.join(BASE_DIR, "requirements.txt")
        subprocess.run(
            [PYTHON_EXE, "-m", "pip", "install", "-r", req_file, "--quiet"],
            cwd=BASE_DIR
        )

    # 4. Restart daemon
    logger.info("🔄 Restarting BudgetBy daemon with fresh code...")
    start_daemon()
    logger.info("✨ Daemon successfully updated and restarted!")


def main():
    logger.info("================================================================")
    logger.info("   BUDGETBY AUTOMATIC GITHUB SYNC WATCHER ACTIVE (30s POLLING)  ")
    logger.info("================================================================")
    logger.info(f"Repository Dir : {BASE_DIR}")
    logger.info(f"Git Path       : {GIT_EXE}")
    logger.info(f"Python Path    : {PYTHON_EXE}")
    logger.info(f"Check Interval : {CHECK_INTERVAL} seconds")
    logger.info(f"Logging To     : {LOG_FILE}")
    logger.info("================================================================")

    prevent_windows_sleep()

    # If daemon is not running when watcher starts, boot it up
    if not is_daemon_running():
        logger.info("Daemon is not currently running. Starting it now...")
        start_daemon()

    while True:
        try:
            prevent_windows_sleep()

            # Run git fetch
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
                    sync_and_restart()
                else:
                    logger.debug("Code is up to date with origin/main.")
            else:
                logger.warning(f"git fetch failed: {fetch_res.stderr.strip()[:200]}")

            # Also verify daemon health: if crashed or killed, ensure it runs
            if not is_daemon_running():
                logger.warning("⚠️ Daemon not detected! Auto-restarting...")
                start_daemon()

        except KeyboardInterrupt:
            logger.info("🛑 Sync watcher stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error in sync loop: {e}", exc_info=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
