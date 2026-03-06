import asyncio
import ipaddress
import socket

import psutil


INTERNET_CHECK_TARGETS = (
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
)


async def has_internet(timeout_sec: float = 2.0) -> bool:
    for host, port in INTERNET_CHECK_TARGETS:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_sec)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            continue
    return False


async def wait_for_internet(check_interval_sec: float = 5.0, timeout_sec: float = 2.0):
    while True:
        if await has_internet(timeout_sec=timeout_sec):
            return
        print(f"No internet connection, retrying in {check_interval_sec:.1f}s...")
        await asyncio.sleep(check_interval_sec)


def resolve_local_ip(prefer_prefixes: tuple[str, ...] = ("192.168.", "10.", "172.")) -> str:
    candidates: list[tuple[str, str]] = []

    for ifname, addrs in psutil.net_if_addrs().items():
        low = ifname.lower()
        if "wireguard" in low or low.startswith("wg"):
            continue

        for addr in addrs:
            family_name = getattr(addr.family, "name", "")
            if addr.family != socket.AF_INET and family_name != "AF_INET":
                continue

            ip = str(addr.address).strip()
            try:
                ip_obj = ipaddress.ip_address(ip)
            except ValueError:
                continue

            if ip_obj.is_private and not ip_obj.is_loopback:
                candidates.append((ifname, ip))

    for prefix in prefer_prefixes:
        for _ifname, ip in candidates:
            if ip.startswith(prefix):
                return ip

    if candidates:
        return candidates[0][1]

    # Fallback to previous behavior for uncommon environments.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()
