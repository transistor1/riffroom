"""Start Riffroom, using loopback unless network access is explicitly requested."""

import argparse
import ipaddress
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

URL = "http://127.0.0.1:8765"


def is_riffroom(url=URL):
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
            return json.load(response).get("name") == "Riffroom"
    except (OSError, ValueError):
        return False


def open_when_ready(url=URL):
    for _ in range(100):
        if is_riffroom(url):
            webbrowser.open(url)
            return
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description="Start Riffroom on this computer")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    args = parser.parse_args()
    host = args.host
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    local_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    url = f"http://{'[' + local_host + ']' if ':' in local_host else local_host}:8765"
    # Never let an inherited opt-in weaken a default launch.
    os.environ.pop("RIFFROOM_BIND_HOST", None)
    if host != "127.0.0.1":
        os.environ["RIFFROOM_BIND_HOST"] = host
    if not loopback:
        print("WARNING: Riffroom has no authentication. Anyone who can reach this interface "
              "can access the app and data. Use only on a trusted LAN.", flush=True)
        print("Remote clients: use this computer's LAN IP and port 8765 (http://LAN-IP:8765).",
              flush=True)
    # Only reuse the default server: its health response cannot prove a LAN binding.
    if host == "127.0.0.1" and is_riffroom():
        if not args.no_browser:
            webbrowser.open(url)
        print(f"Riffroom is already running at {url}")
        return
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family) as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, 8765))
        except OSError as exc:
            raise SystemExit(
                f"Cannot bind {host}:8765: {exc}. Port 8765 is in use or the address is unavailable. "
                "Stop any existing Riffroom server before changing its bind address."
            ) from None
    print(f"\nRiffroom · {url}\nBinding to {host}:8765. Keep this window open. Press Control-C to stop.\n")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("riffroom.app:app", host=host, port=8765, log_level="info")


if __name__ == "__main__":
    main()
