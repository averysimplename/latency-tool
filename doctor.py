import os
import platform
import shutil
import sys
import subprocess

MIN_PY = (3, 10)

def fail(msg: str, code: int = 1):
    print(f"❌ {msg}")
    sys.exit(code)

def ok(msg: str):
    print(f"✅ {msg}")

def warn(msg: str):
    print(f"⚠️ {msg}")

def check_python():
    if sys.version_info < MIN_PY:
        fail(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ required. You have {sys.version.split()[0]}.")
    ok(f"Python version: {sys.version.split()[0]}")

def check_venv():
    # Not mandatory, but a useful hint
    in_venv = (hasattr(sys, "real_prefix") or (sys.base_prefix != sys.prefix))
    if in_venv:
        ok("Virtual environment: active")
    else:
        warn("Virtual environment not active. Run: source myenv/bin/activate")

def check_imports():
    try:
        import selenium  # noqa
        ok("Selenium import: OK")
    except Exception as e:
        fail(f"Selenium not installed/importable. Run setup. Details: {e}")

def find_chrome():
    system = platform.system().lower()

    # Common executable names on PATH
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

    # macOS default app path
    if system == "darwin":
        mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(mac_path):
            return mac_path

    # Windows: typical locations (best-effort)
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
        fail("Google Chrome not found. Install Chrome, then re-run.")
    ok(f"Chrome found: {chrome}")

    # Try to get version
    try:
        out = subprocess.check_output([chrome, "--version"], stderr=subprocess.STDOUT, text=True).strip()
        ok(f"Chrome version: {out}")
    except Exception:
        warn("Could not read Chrome version (not fatal).")

def main():
    print("=== recgov latency tool: doctor ===")
    check_python()
    check_venv()
    check_imports()
    check_chrome()
    print("\n✅ Preflight checks passed. You should be able to run: python run.py")

if __name__ == "__main__":
    main()
