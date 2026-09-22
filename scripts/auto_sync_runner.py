"""
BudgetBy — Independent Automatic GitHub Sync Watcher.
Runs independently in its own window (Window 2).
Checks `git fetch origin main` every 30 seconds.
When a new commit is detected:
1. Fast-forwards local branch to origin/main (100% local, zero network/DNS errors).
2. Installs updated dependencies if requirements.txt changed.
3. Signals the Deal Engine in Window 1 to reload with the new code.
Zero conflict, zero blank windows, clean independent execution.
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


def is_engine_running() -> bool:
    """Checks if budgetby.main or run_local_daemon.py is running in Window 1."""
    my_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['pid'] == my_pid:
                continue
            cmdline = proc.info.get('cmdline') or []
            cmd_str = " ".join(cmdline)
            if "budgetby.main" in cmd_str or "run_local_daemon.py" in cmd_str:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def trigger_engine_reload():
    """
    Signals Window 1 (run_local_daemon.py) to reload with fresh code
    by terminating the child budgetby.main process.
    run_local_daemon will immediately restart it with the new code in Window 1.
    """
    my_pid = os.getpid()
    reloaded = False
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['pid'] == my_pid:
                continue
            cmdline = proc.info.get('cmdline') or []
            cmd_str = " ".join(cmdline)
            if "budgetby.main" in cmd_str:
                pid = proc.info['pid']
                logger.info(f"🔄 Reloading Deal Engine (notifying PID {pid})...")
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                else:
                    proc.kill()
                reloaded = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if reloaded:
        logger.info("✨ Deal Engine in Window 1 received reload signal! Relaunching with new code...")
    else:
        # If engine was not running, launch it in its own window
        logger.info("Deal Engine not running. Starting it in a new window...")
        start_bat = os.path.join(BASE_DIR, "start_bot.bat")
        if os.path.exists(start_bat):
            subprocess.Popen(["cmd.exe", "/c", "start", "BudgetBy Deal Engine", start_bat], cwd=BASE_DIR)


def sync_and_reload():
    """Merges latest git commits locally from origin/main and triggers reload in Window 1."""
    local_hash = get_commit_hash("HEAD")
    remote_hash = get_commit_hash("origin/main")

    logger.info(f"📢 New commit detected on GitHub: {local_hash[:7]} ➔ {remote_hash[:7]}")

    # 1. Commits were already downloaded locally by git fetch!
    # Fast-forward local branch to origin/main (100% local, zero network calls, zero DNS errors).
    logger.info("📥 Fast-forwarding local branch to origin/main...")
    merge_res = subprocess.run(
        [GIT_EXE, "merge", "--ff-only", "origin/main"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=30
    )

    if merge_res.returncode != 0:
        logger.warning(f"⚠️ Fast-forward failed ({merge_res.stderr.strip()[:150]}). Attempting standard git merge...")
        merge_res = subprocess.run(
            [GIT_EXE, "merge", "origin/main", "-m", "Auto-sync update from origin/main"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )

    if merge_res.returncode != 0:
        logger.warning(f"⚠️ Git merge failed (will retry in {CHECK_INTERVAL}s):\n{merge_res.stderr.strip()[:250]}")
        logger.info("🛡️ Deal Engine in Window 1 NOT interrupted because merge did not succeed.")
        return False

    new_hash = get_commit_hash("HEAD")
    logger.info(f"✅ Code updated successfully to {new_hash[:7]}:\n{merge_res.stdout.strip()}")

    # 2. Check if dependencies changed
    if check_requirements_diff(local_hash, new_hash):
        logger.info("📦 requirements.txt changed. Updating dependencies...")
        subprocess.run(
            [PYTHON_EXE, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
            cwd=BASE_DIR
        )

    # 3. Reload the Deal Engine in Window 1 ONLY after successful merge
    trigger_engine_reload()
    return True


def main():
    print("\n" + "=" * 64)
    print("   BUDGETBY AUTOMATIC GITHUB SYNC WATCHER (WINDOW 2)   ")
    print("=" * 64)
    print(f"Repository : {BASE_DIR}")
    print(f"Git Path   : {GIT_EXE}")
    print(f"Interval   : Every {CHECK_INTERVAL}s")
    print(f"Status     : Monitoring origin/main for new commits...")
    print("=" * 64 + "\n")

    prevent_windows_sleep()

    # Check if Deal Engine is running
    if not is_engine_running():
        logger.warning("⚠️ Window 1 (Deal Engine) is not currently running.")
        logger.info("Tip: Double click 'start_bot.bat' to start the live deal engine.")

    while True:
        try:
            prevent_windows_sleep()

            fetch_res = subprocess.run(
                [GIT_EXE, "-c", "http.ipresolve=4", "fetch", "origin", "main"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=45
            )

            if fetch_res.returncode == 0:
                local_hash = get_commit_hash("HEAD")
                remote_hash = get_commit_hash("origin/main")

                if local_hash != remote_hash:
                    sync_and_reload()
                else:
                    logger.debug("Code is up to date.")
            else:
                logger.warning(f"git fetch notice: {fetch_res.stderr.strip()[:150]}")

        except KeyboardInterrupt:
            logger.info("\n🛑 Sync watcher stopped by user.")
            break
        except Exception as e:
            logger.error(f"Watcher loop notice: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
