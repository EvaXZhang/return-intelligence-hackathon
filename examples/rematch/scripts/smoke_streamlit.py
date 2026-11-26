"""Bounded Streamlit startup/health smoke that always terminates its child."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    port = available_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["REMATCH_MODE"] = "demo"
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "streamlit_app.py", "--server.headless=true", f"--server.port={port}", "--browser.gatherUsageStats=false"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 25
        last_error = ""
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"Streamlit exited early ({process.returncode}): {output}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                    body = response.read().decode("utf-8")
                    if response.status == 200 and body.strip().lower() == "ok":
                        print(f"PASS Streamlit health returned ok on bounded port {port}")
                        return
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.25)
        raise RuntimeError(f"Streamlit health timeout: {last_error}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        print("PASS Streamlit child process terminated")


if __name__ == "__main__":
    main()
