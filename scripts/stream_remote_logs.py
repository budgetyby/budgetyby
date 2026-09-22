"""
BudgetBy — Live Remote Console Log Streamer.
Connects directly to Dell Server over local home Wi-Fi.
Zero Supabase egress, 100% on-demand, authenticated and colorized.
"""

import os
import sys
import time
import json
import socket
import asyncio
from pathlib import Path
from urllib.parse import urlencode

# Project root
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from budgetby import config
    ADMIN_SECRET_KEY = getattr(config, "ADMIN_SECRET_KEY", "") or os.getenv("ADMIN_SECRET_KEY", "bb_sec_9e72f8a14b30c5e7d82f091a384b62d1")
except Exception:
    ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "bb_sec_9e72f8a14b30c5e7d82f091a384b62d1")

CACHE_FILE = BASE_DIR / ".dell_server_ip"

# Enable ANSI colors on Windows Command Prompt
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        hStdOut = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(hStdOut, ctypes.byref(mode))
        mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(hStdOut, mode)
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[90m"
RESET = "\033[0m"


def get_local_ip() -> str:
    """Gets primary local IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


async def probe_ip(ip: str, port: int = 5000, timeout: float = 0.8) -> str | None:
    """Checks if IP is running BudgetBy server on port 5000."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout
        )
        req = f"GET /api/live-logs/ping HTTP/1.1\r\nHost: {ip}:{port}\r\nConnection: close\r\n\r\n"
        writer.write(req.encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        resp_text = data.decode("utf-8", errors="ignore").lower()
        if "200 ok" in resp_text and ("budgetby" in resp_text or "uvicorn" in resp_text):
            return ip
    except Exception:
        pass
    return None


async def discover_server_ip() -> str | None:
    """Discovers Dell server IP on local network subnet."""
    local_ip = get_local_ip()
    print(f"{DIM}🔍 Local IP detected: {local_ip}{RESET}")

    # 1. Check cached IP
    if CACHE_FILE.exists():
        try:
            cached_ip = CACHE_FILE.read_text().strip()
            if cached_ip:
                print(f"{DIM}Testing cached server IP: {cached_ip}...{RESET}")
                if await probe_ip(cached_ip, timeout=1.0):
                    print(f"{GREEN}✓ Connected to cached server: {cached_ip}{RESET}")
                    return cached_ip
        except Exception:
            pass

    # 2. Check environment override
    env_ip = os.getenv("DELL_SERVER_IP", "").strip()
    if env_ip:
        if await probe_ip(env_ip, timeout=1.5):
            CACHE_FILE.write_text(env_ip)
            return env_ip

    # 3. Check ARP table (finds hotspot devices, router peers in 50ms)
    try:
        import subprocess, re
        arp_res = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=2)
        arp_ips = re.findall(r'(\d+\.\d+\.\d+\.\d+)', arp_res.stdout)
        candidates = [
            ip for ip in set(arp_ips)
            if not ip.endswith(".255") and not ip.startswith("224.") and not ip.startswith("255.") and ip != local_ip
        ]
        if candidates:
            print(f"{DIM}Probing {len(candidates)} active network devices (Hotspot/LAN)...{RESET}")
            arp_tasks = [probe_ip(ip, timeout=0.8) for ip in candidates]
            arp_results = await asyncio.gather(*arp_tasks)
            for ip in arp_results:
                if ip:
                    print(f"{GREEN}✓ Found BudgetBy server via network ARP: {ip}{RESET}")
                    CACHE_FILE.write_text(ip)
                    return ip
    except Exception:
        pass

    # 3. Scan local /24 subnet
    parts = local_ip.split(".")
    if len(parts) != 4:
        return None

    subnet_prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
    print(f"{YELLOW}Scanning local network ({subnet_prefix}.1 to 254) for Dell server...{RESET}")

    tasks = [probe_ip(f"{subnet_prefix}.{i}") for i in range(1, 255)]
    results = await asyncio.gather(*tasks)

    for ip in results:
        if ip:
            print(f"{GREEN}✓ Found BudgetBy server at: {ip}{RESET}")
            CACHE_FILE.write_text(ip)
            return ip

    return None


async def stream_logs_from_server(server_ip: str, port: int = 5000):
    """Streams live Server-Sent Events from Dell server."""
    query = urlencode({"key": ADMIN_SECRET_KEY})
    path = f"/api/live-logs/stream?{query}"

    print(f"\n{BOLD}{GREEN}================================================================{RESET}")
    print(f"{BOLD}{GREEN}       BUDGETBY LIVE REMOTE CONSOLE (DELL SERVER)               {RESET}")
    print(f"{BOLD}{GREEN}================================================================{RESET}")
    print(f" * Server Host : {BOLD}{server_ip}:{port}{RESET}")
    print(f" * Data Flow   : Direct Home Wi-Fi ({GREEN}Zero Supabase Egress{RESET})")
    print(f" * Controls    : Close window or press {YELLOW}Ctrl + C{RESET} to stop streaming")
    print(f"{BOLD}{GREEN}================================================================{RESET}\n")

    while True:
        try:
            reader, writer = await asyncio.open_connection(server_ip, port)
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {server_ip}:{port}\r\n"
                f"Accept: text/event-stream\r\n"
                f"Connection: keep-alive\r\n"
                f"\r\n"
            )
            writer.write(req.encode())
            await writer.drain()

            # Read HTTP headers first
            status_line = await reader.readline()
            status_str = status_line.decode("utf-8", errors="ignore").strip()

            if "200" not in status_str:
                print(f"{RED}Server returned error: {status_str}{RESET}")
                if "403" in status_str:
                    print(f"{RED}Authentication failed. Check ADMIN_SECRET_KEY.{RESET}")
                    return
                elif "404" in status_str:
                    print(f"{RED}Stream endpoint not found on server.{RESET}")
                    return
                await asyncio.sleep(5)
                continue

            # Skip remaining response headers
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break

            print(f"{GREEN}● Live stream established! Waiting for logs...{RESET}\n")

            # Stream body lines
            while True:
                raw_line = await reader.readline()
                if not raw_line:
                    break

                text = raw_line.decode("utf-8", errors="replace").strip()
                if text.startswith("data: "):
                    payload_str = text[6:].strip()
                    try:
                        data = json.loads(payload_str)
                        src = data.get("source", "engine")
                        lvl = data.get("level", "INFO")
                        msg = data.get("text", "")

                        # Format tag
                        if src == "sync_watcher":
                            tag = f"{YELLOW}[SYNC WATCHER]{RESET}"
                        else:
                            tag = f"{CYAN}[DEAL ENGINE]{RESET}"

                        # Format level
                        if lvl in ("ERROR", "CRITICAL"):
                            lvl_tag = f"{RED}[{lvl}]{RESET}"
                        elif lvl == "WARNING":
                            lvl_tag = f"{YELLOW}[{lvl}]{RESET}"
                        else:
                            lvl_tag = f"{DIM}[INFO]{RESET}"

                        print(f"{tag} {lvl_tag} {msg}")
                        sys.stdout.flush()
                    except Exception:
                        print(f"{DIM}{payload_str}{RESET}")

        except (ConnectionResetError, ConnectionRefusedError, asyncio.IncompleteReadError):
            print(f"\n{YELLOW}🔄 Connection lost (Dell server is likely auto-reloading after a git push)...{RESET}")
            print(f"{DIM}Reconnecting in 4 seconds...{RESET}")
            await asyncio.sleep(4)
        except Exception as e:
            print(f"\n{RED}Stream error: {e}. Reconnecting in 5s...{RESET}")
            await asyncio.sleep(5)


def main():
    if len(sys.argv) > 1:
        server_ip = sys.argv[1].strip()
    else:
        server_ip = asyncio.run(discover_server_ip())

    if not server_ip:
        print(f"\n{RED}❌ Could not automatically locate Dell server on your Wi-Fi.{RESET}")
        print(f"Please check:")
        print(f"1. Is the Dell laptop turned on and running start_all.bat?")
        print(f"2. Are both laptops connected to the same Wi-Fi router?")
        print(f"3. You can manually specify Dell's IP by running:")
        print(f"   python scripts\\stream_remote_logs.py <DELL_IP>")
        input("\nPress Enter to exit...")
        sys.exit(1)

    try:
        asyncio.run(stream_logs_from_server(server_ip))
    except KeyboardInterrupt:
        print(f"\n{DIM}🛑 Log streaming stopped by user.{RESET}")


if __name__ == "__main__":
    main()
