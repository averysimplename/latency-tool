#!/usr/bin/env python3

import os
import platform
import shutil
import sys
import subprocess

MIN_PY = (3, 10)


def fail(msg: str, code: int = 1):
    print(f"\n❌ {msg}")
    sys.exit(code)


def ok(msg: str):
    print(f"✅ {msg}")


def warn(msg: str):
    print(f"⚠️  {msg}")


def info(msg: str):
    print(f"ℹ️  {msg}")


def check_python():
    if sys.version_info < MIN_PY:
        fail(
            f"Python {MIN_PY[0]}.{MIN_PY[1]}+ required.\n"
            f"You have {sys.version.split()[0]}.\n\n"
            "Install Python from:\n"
            "https://www.python.org/downloads/"
        )

    ok(f"Python version: {sys.version.split()[0]}")


def check_pip():
    try:
        subprocess.check_output([sys.executable, "-m", "pip", "--version"])
        ok("pip available")
    except Exception:
        fail(
            "pip is not available.\n"
            "Reinstall Python and ensure pip is included."
        )


def check_venv():
    in_venv = hasattr(sys, "real_prefix") or (sys.base_prefix != sys.prefix)

    if in_venv:
        ok("Virtual environment: active")
    else:
        warn(
            "Virtual environment not active.\n"
            "The setup script will create one automatically."
        )


def check_imports():
    try:
        import selenium  # noqa

        ok("Selenium import: OK")

    except Exception:
        warn(
            "Selenium not installed yet.\n"
            "This will be installed during setup."
        )


def find_chrome():
    system = platform.system().lower()

    candidates = [
        "google-chrome",
        "chrome",
        "chromium",
        "chromium-browser",
        "Google Chrome",
    ]

    for c in candidates:
        p = shutil.which(c)
        if p:
            return p

    if system == "darwin":
        mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(mac_path):
            return mac_path

    if system == "windows":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        win_paths = [
            os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
        ]

        for wp in win_paths:
            if os.path.exists(wp):
                return wp

    return None


def check_chrome():
    chrome = find_chrome()

    if not chrome:
        fail(
            "Google Chrome not found.\n"
            "Install Chrome from:\n"
            "https://www.google.com/chrome/"
        )

    ok(f"Chrome found: {chrome}")

    try:
        out = subprocess.check_output(
            [chrome, "--version"],
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()

        ok(f"Chrome version: {out}")

    except Exception:
        warn("Could not read Chrome version (not fatal)")


def print_next_steps():
    system = platform.system().lower()

    print("\nNext step:\n")

    if system == "windows":
        print("Run the setup script:\n")
        print("    Set-ExecutionPolicy -Scope Process Bypass")
        print("    .\\scripts\\setup.ps1\n")

        print("Then run:\n")
        print("    .\\scripts\\run.ps1\n")

    else:
        print("Run the setup script:\n")
        print("    chmod +x scripts/setup.sh scripts/run.sh")
        print("    ./scripts/setup.sh\n")

        print("Then run:\n")
        print("    ./scripts/run.sh\n")


def main():
    print("\n=== recgov latency tool : doctor ===\n")

    check_python()
    check_pip()
    check_venv()
    check_imports()
    check_chrome()

    print("\n🎉 Preflight checks passed.")
    print_next_steps()


if __name__ == "__main__":
    main()
