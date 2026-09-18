"""Start one loopback server and open the room once it is listening."""

import argparse
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

URL = "http://127.0.0.1:8765"


def is_riffroom():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            return json.load(response).get("name") == "Riffroom"
    except (OSError, ValueError):
        return False


def open_when_ready():
    for _ in range(100):
        if is_riffroom():
            webbrowser.open(URL)
            return
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description="Start Riffroom on this Mac")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if is_riffroom():
        if not args.no_browser:
            webbrowser.open(URL)
        print(f"Riffroom is already running at {URL}")
        return
    with socket.socket() as probe:
        # Match the server's normal Unix socket behavior so a just-closed
        # Riffroom instance can be restarted while old connections are still
        # in TIME_WAIT. This does not let us bind over another live listener.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", 8765))
        except OSError:
            raise SystemExit("Port 8765 is in use by another app. Close that app and try again.") from None
    print(f"\nRiffroom · {URL}\nKeep this window open. Press Control-C to stop.\n")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("riffroom.app:app", host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
