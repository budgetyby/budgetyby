"""
BudgetBy Database Exporter.
Exports the optimized PostgreSQL database into a compressed .sql.gz archive
ready for cloud import into Supabase or any cloud PostgreSQL provider.
"""
import os
import sys
import subprocess
import gzip
import shutil
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = r"c:\Users\jaysi\.gemini\antigravity\scratch\budget-by"
sys.path.insert(0, BASE_DIR)
from budgetby import config

PG_DUMP_CANDIDATES = [
    r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe",
    r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
    r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
    r"C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
    "pg_dump"
]

def find_pg_dump():
    for p in PG_DUMP_CANDIDATES:
        if os.path.exists(p):
            return p
    return "pg_dump"

def export_database():
    if "--force" not in sys.argv:
        print("NOTICE: Database export requires the '--force' flag (python export_database.py --force) to prevent accidental cloud egress downloads.")
        print("To manage backups automatically, rely on Supabase's managed cloud auto-backups.")
        return

    pg_dump = find_pg_dump()
    print("=" * 60)
    print("STARTING BUDGETBY DATABASE CLOUD EXPORT")
    print("=" * 60)
    print(f"Using pg_dump binary: {pg_dump}")

    sql_out = os.path.join(BASE_DIR, "budgetby_optimized.sql")
    gz_out = os.path.join(BASE_DIR, "budgetby_optimized.sql.gz")

    env = os.environ.copy()
    env["PGPASSWORD"] = str(config.DB_PASSWORD)

    cmd = [
        pg_dump,
        "-h", str(config.DB_HOST),
        "-p", str(config.DB_PORT),
        "-U", str(config.DB_USER),
        "-d", str(config.DB_NAME),
        "--no-owner",
        "--no-privileges",
        "-f", sql_out
    ]

    print(f"Dumping database '{config.DB_NAME}' to {sql_out}...")
    t0 = time.time()
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"ERROR running pg_dump: {res.stderr}")
        return False

    raw_size_mb = os.path.getsize(sql_out) / (1024 * 1024)
    print(f"Dump completed in {time.time() - t0:.1f}s. Raw SQL file size: {raw_size_mb:.1f} MB")

    print(f"Compressing into {gz_out} with maximum compression...")
    t0 = time.time()
    with open(sql_out, "rb") as f_in:
        with gzip.open(gz_out, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)

    gz_size_mb = os.path.getsize(gz_out) / (1024 * 1024)
    print(f"Compressed in {time.time() - t0:.1f}s. Final Gzip Archive Size: {gz_size_mb:.1f} MB")

    # Clean up uncompressed file to save disk space
    if os.path.exists(sql_out):
        os.remove(sql_out)

    print("\n" + "=" * 60)
    print("SUCCESS: DATABASE EXPORT READY FOR CLOUD RESTORE!")
    print(f"File Path: {gz_out}")
    print(f"Archive Size: {gz_size_mb:.1f} MB (Extremely compact, fits any free cloud)")
    print("=" * 60)
    return True

if __name__ == "__main__":
    export_database()
