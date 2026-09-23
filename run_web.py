"""Launcher for Memoria Web Server & UI.

Usage:
    python run_web.py [--port 8000] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import uvicorn


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Start Memoria Web Server & UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print("=" * 60)
    print("Memoria 知识系统正在启动...")
    print(f"Web 界面地址: {url}")
    print(f"API 文档地址: {url}/docs")
    print("=" * 60)

    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run("memoria.web.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
