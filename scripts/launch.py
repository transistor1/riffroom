"""Start Riffroom, using loopback unless network access is explicitly requested."""

import argparse
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

URL = "http://127.0.0.1:8765"


def lan_addresses():
    addresses = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(result[4][0])
    except OSError:
        pass
    # A UDP connect discovers the default interface without sending a packet.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(address for address in addresses
                  if not ipaddress.ip_address(address).is_loopback
                  and not ipaddress.ip_address(address).is_unspecified)


def lan_certificate(addresses):
    directory = Path(os.environ.get("RIFFROOM_DATA", Path(__file__).resolve().parents[1] / "data")) / "https"
    cert, key = directory / "cert.pem", directory / "key.pem"
    if cert.is_file() and key.is_file():
        return cert, key
    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit("LAN HTTPS requires the openssl CLI to generate its certificate; install openssl and retry.")
    names = sorted({"localhost", socket.gethostname()})
    # Only hostname characters belong in the OpenSSL configuration.
    names = [name for name in names if name and all(c.isalnum() or c in ".-_" for c in name)]
    sans = [f"DNS.{i} = {name}" for i, name in enumerate(names, 1)]
    sans += [f"IP.{i} = {address}" for i, address in
             enumerate(sorted({"127.0.0.1", "::1", *addresses}), 1)]
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            temporary = Path(temporary)
            config = temporary / "openssl.cnf"
            config.write_text("[req]\nprompt = no\ndistinguished_name = dn\nx509_extensions = extensions\n"
                              "[dn]\nCN = localhost\n[extensions]\nsubjectAltName = @sans\n[sans]\n"
                              + "\n".join(sans) + "\n")
            subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
                            "-config", str(config), "-keyout", str(temporary / "key.pem"),
                            "-out", str(temporary / "cert.pem")], check=True, capture_output=True, text=True)
            (temporary / "key.pem").chmod(0o600)
            (temporary / "key.pem").replace(key)
            (temporary / "cert.pem").replace(cert)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise SystemExit(f"Cannot generate LAN HTTPS certificate: {detail}") from None
    return cert, key


def is_riffroom(url=URL, context=None):
    try:
        options = {"context": context} if context is not None else {}
        with urllib.request.urlopen(url + "/api/health", timeout=1, **options) as response:
            return json.load(response).get("name") == "Riffroom"
    except (OSError, ValueError):
        return False


def open_when_ready(url=URL, cert=None):
    context = ssl.create_default_context(cafile=str(cert)) if cert else None
    for _ in range(100):
        ready = is_riffroom(url, context=context) if context else is_riffroom(url)
        if ready:
            webbrowser.open(url)
            return
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description="Start Riffroom on this computer")
    parser.add_argument("--no-browser", action="store_true")
    binding = parser.add_mutually_exclusive_group()
    binding.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    binding.add_argument("--lan", action="store_true", help="serve self-signed HTTPS on all IPv4 interfaces")
    args = parser.parse_args()
    host = "0.0.0.0" if args.lan else args.host
    scheme = "https" if args.lan else "http"
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    local_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    url = f"{scheme}://{'[' + local_host + ']' if ':' in local_host else local_host}:8765"
    # Never let an inherited opt-in weaken a default launch.
    os.environ.pop("RIFFROOM_BIND_HOST", None)
    if host != "127.0.0.1":
        os.environ["RIFFROOM_BIND_HOST"] = host
    if not loopback:
        print("WARNING: Riffroom has no authentication. Anyone who can reach this interface "
              "can access the app and data. Use only on a trusted LAN.", flush=True)
        if not args.lan:
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
    tls = {}
    browser_args = (url,)
    if args.lan:
        addresses = lan_addresses()
        cert, key = lan_certificate(addresses)
        tls = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        browser_args = (url, cert)
        print(f"LAN: open https://{addresses[0] if addresses else 'LAN-IP'}:8765 on your device. "
              "Safari will warn about the self-signed certificate; accept it to continue.", flush=True)
    print(f"\nRiffroom · {url}\nBinding to {host}:8765. Keep this window open. Press Control-C to stop.\n")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=browser_args, daemon=True).start()
    uvicorn.run("riffroom.app:app", host=host, port=8765, log_level="info", **tls)


if __name__ == "__main__":
    main()
