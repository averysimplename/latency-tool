#!/usr/bin/env python3
"""
reserve-alpha-hft.py
March 5th, 2026: This is the latency version

Goals:
- One-time (multi-sample) NTP sync -> stable offset
- Convert target wallclock time to a monotonic deadline (perf_counter)
- No network calls in the final timing window
- Pre-warm element reference
- Disable GC during final window
- Prefer JS click; fallback to WebDriver click
- Optional CSV logging for calibration

Notes:
- This is still limited by browser scheduling and the website backend.
- You can further reduce jitter with: taskset + nice + performance governor.
"""

import os
import sys
import time
import csv
import gc
import datetime
from dataclasses import dataclass

import pytz
import ntplib

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Prefer Selenium Manager (Selenium 4.6+) if available, otherwise webdriver_manager.
USE_WEBDRIVER_MANAGER = True
try:
    if USE_WEBDRIVER_MANAGER:
        from webdriver_manager.chrome import ChromeDriverManager
except Exception:
    USE_WEBDRIVER_MANAGER = False


# -----------------------------
# Config
# -----------------------------
TZ_NAME = "America/Los_Angeles"
TZ = pytz.timezone(TZ_NAME)

NTP_SERVER = "time.google.com"

# Timing behavior (tune these if you want)
FAR_SLEEP_SECONDS = 0.25      # when > 1s away
MID_SLEEP_SECONDS = 0.005     # 5ms sleeps when close
FINAL_SPIN_SECONDS = 0.050    # spin last 50ms (cpu busy-wait)

# Optional small fudge in seconds (negative fires earlier)
# Start with 0.000 and tune using log results
DEADLINE_FUDGE_SECONDS = 0.000

# NTP sampling
NTP_SAMPLES = 7
NTP_PAUSE_SECONDS = 0.15

# Logging
LOG_CSV = "timing_log.csv"

# Chrome profiling
PROFILE_PATH = os.path.join(os.getcwd(), "profiles", "rec1")

# -----------------------------
# Helpers
# -----------------------------
@dataclass
class NtpSyncResult:
    offset_seconds: float   # ntp_now - local_now (seconds)
    rtt_seconds: float      # round trip time for best sample
    ntp_time: datetime.datetime
    local_time: datetime.datetime


def info(msg: str) -> None:
    print(msg, flush=True)


def now_pst() -> datetime.datetime:
    return datetime.datetime.now(TZ)


def ntp_sample() -> tuple[datetime.datetime, datetime.datetime, float]:
    """
    Returns: (ntp_pst_datetime, local_pst_datetime, rtt_seconds)
    """
    client = ntplib.NTPClient()
    t0 = time.perf_counter()
    resp = client.request(NTP_SERVER, version=3)
    t1 = time.perf_counter()
    rtt = t1 - t0

    ntp_utc = datetime.datetime.utcfromtimestamp(resp.tx_time).replace(tzinfo=pytz.utc)
    ntp_pst = ntp_utc.astimezone(TZ)
    local_pst = now_pst()

    return ntp_pst, local_pst, rtt


def sync_ntp_offset(samples: int = NTP_SAMPLES, pause: float = NTP_PAUSE_SECONDS) -> NtpSyncResult:
    """
    Estimate local clock offset relative to NTP:
      offset = ntp_now - local_now

    Choose the sample with the lowest RTT as best approximation.
    """
    best: dict | None = None

    info(f"🔍 Syncing time via NTP ({samples} samples) against {NTP_SERVER}...")
    for i in range(samples):
        try:
            ntp_t, local_t, rtt = ntp_sample()
            offset = (ntp_t - local_t).total_seconds()
            info(f"   NTP {i+1}/{samples}: rtt={rtt*1000:6.1f}ms offset={offset:+.6f}s ntp={ntp_t.strftime('%H:%M:%S.%f')}")
            if best is None or rtt < best["rtt"]:
                best = {"offset": offset, "rtt": rtt, "ntp": ntp_t, "local": local_t}
        except Exception as e:
            info(f"   NTP {i+1}/{samples}: failed ({e})")
        time.sleep(pause)

    if best is None:
        raise RuntimeError("All NTP samples failed. Check network/firewall/DNS.")

    info(f"✅ Chosen NTP offset: {best['offset']:+.6f}s (best rtt={best['rtt']*1000:.1f}ms)")
    return NtpSyncResult(
        offset_seconds=float(best["offset"]),
        rtt_seconds=float(best["rtt"]),
        ntp_time=best["ntp"],
        local_time=best["local"],
    )


def parse_target_time_str(target_time_str: str) -> datetime.time:
    """
    Parse time like '7:00:00AM' in %I:%M:%S%p format.
    """
    return datetime.datetime.strptime(target_time_str.strip().upper(), "%I:%M:%S%p").time()


def wallclock_target_datetime_today_pst(target_time: datetime.time) -> datetime.datetime:
    """
    Returns a PST datetime for today at target_time, or tomorrow if already passed.
    """
    n = now_pst()
    target = n.replace(hour=target_time.hour, minute=target_time.minute, second=target_time.second, microsecond=0)
    if target <= n:
        target = target + datetime.timedelta(days=1)
    return target


def compute_monotonic_deadline(true_target_pst: datetime.datetime, ntp_offset_seconds: float) -> tuple[float, datetime.datetime]:
    """
    Convert true target time into a local-monotonic deadline.

    Model:
      true_time ≈ local_time + offset
      local_time ≈ true_time - offset

    We compute local wallclock moment corresponding to true target, then map to perf_counter().
    """
    local_target = true_target_pst - datetime.timedelta(seconds=ntp_offset_seconds)

    local_now = now_pst()
    mono_now = time.perf_counter()

    seconds_until_local_target = (local_target - local_now).total_seconds()
    mono_deadline = mono_now + seconds_until_local_target + DEADLINE_FUDGE_SECONDS

    return mono_deadline, local_target


def wait_until_monotonic(mono_deadline: float) -> None:
    """
    Sleep most of the time; spin in the final window.
    """
    while True:
        now_mono = time.perf_counter()
        remaining = mono_deadline - now_mono

        if remaining <= 0:
            return

        if remaining > 1.0:
            time.sleep(FAR_SLEEP_SECONDS)
        elif remaining > FINAL_SPIN_SECONDS:
            time.sleep(MID_SLEEP_SECONDS)
        else:
            # final spin
            while time.perf_counter() < mono_deadline:
                pass
            return


def click_fast(driver: webdriver.Chrome, element) -> tuple[str, str | None]:
    """
    JS click first (fast), fallback to WebDriver click.
    Returns: (method, error_message_or_none)
    """
    try:
        driver.execute_script("arguments[0].click();", element)
        return "js", None
    except Exception as e1:
        try:
            element.click()
            return "webdriver", None
        except Exception as e2:
            return "failed", f"js_click_error={repr(e1)}; webdriver_click_error={repr(e2)}"


def ensure_csv_header(path: str) -> None:
    if os.path.exists(path):
        return

    header = [
        "timestamp_local",
        "true_target_pst",
        "local_target_wallclock_pst",
        "ntp_offset_s",
        "ntp_rtt_ms",
        "deadline_fudge_s",
        "mono_deadline",
        "mono_actual",
        "mono_error_ms",
        "dom_click_delay_ms",
        "network_delay_ms",
        "network_url",
        "click_method",
        "click_error",
    ]

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)


def append_csv(path: str, row: list) -> None:
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow(row)


# -----------------------------
# Selenium setup / flow
# -----------------------------
def build_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")

    # enable DevTools performance logging
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    # Create portable profile directory inside project
    profile_path = os.path.join(os.getcwd(), "profiles", "rec1")
    os.makedirs(profile_path, exist_ok=True)

    # Use persistent Chrome profile
    options.add_argument(f"--user-data-dir={profile_path}")
    
    # Prevent Chrome from throttling timers when backgrounded
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    
    # For best stability, avoid extra extensions / prompts.
    # You can uncomment these if you want less UI noise:
    # options.add_argument("--disable-notifications")
    # options.add_argument("--disable-popup-blocking")

    if USE_WEBDRIVER_MANAGER:
        info("🔧 Starting Chrome with webdriver-manager (may download driver if not cached)...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    else:
        info("🔧 Starting Chrome using Selenium Manager (built-in driver management)...")
        driver = webdriver.Chrome(options=options)

    return driver

def setup_or_continue(driver, profile_path):
    print("\n==============================")
    print("Chrome Profile Setup")
    print("==============================\n")

    print(f"👤 Chrome profile location: {profile_path}\n")

    print("If this is your FIRST time running the program:")
    print("  1) Log into recreation.gov in the opened browser window.")
    print("  2) After logging in successfully, CLOSE THE PROGRAM (Ctrl+C).")
    print("  3) Your login session will be saved for future runs.\n")

    print("If you have already logged in before:")
    print("  Verify that you are logged into recreation.gov in the browser.")
    print("  Then press ENTER to continue.\n")

    input("Press ENTER when ready...")



def navigate_to_site(driver: webdriver.Chrome, campsite_number: str) -> None:
    site_url = f"https://www.recreation.gov/camping/campsites/{campsite_number}"
    driver.get(site_url)
    info(f"✅ Navigated to campsite page: {site_url}")
    input("🔹 Select your dates in the browser, then press ENTER here to continue: ")


def wait_for_add_to_cart_button(driver: webdriver.Chrome, timeout: int = 60):
    """
    Wait for presence and enabled-looking state.
    Returns the element (pre-warmed reference).
    """
    info("⏳ Waiting for 'Add to Cart' button to appear and become active...")

    wait = WebDriverWait(driver, timeout)
    btn = wait.until(EC.presence_of_element_located((By.ID, "add-cart-campsite")))

    # Wait until it looks enabled. Your prior logic used class contains 'sarsa-button-primary'.
    # We'll keep that, and also wait for it to be clickable.
    def class_has_enabled_style(d):
        el = d.find_element(By.ID, "add-cart-campsite")
        cls = el.get_attribute("class") or ""
        return "sarsa-button-primary" in cls

    wait.until(class_has_enabled_style)
    wait.until(EC.element_to_be_clickable((By.ID, "add-cart-campsite")))

    info("✅ 'Add to Cart' button is visible and clickable (pre-warmed reference acquired).")
    return btn

def arm_dom_click_metrics(driver, element, tag="add_to_cart"):
    """
    Installs a one-shot click listener that stores high-res timestamps into localStorage.
    Uses epoch-ms via performance.timeOrigin + performance.now() so it survives navigation.
    """
    driver.execute_script(
        """
        const tag = arguments[1];
        const btn = arguments[0];

        // Clear prior metrics for this tag
        localStorage.removeItem(`__dom_before_${tag}`);
        localStorage.removeItem(`__dom_handled_${tag}`);
        localStorage.removeItem(`__dom_armed_${tag}`);

        // Mark armed time (debug)
        localStorage.setItem(`__dom_armed_${tag}`, String(performance.timeOrigin + performance.now()));

        // Capture early in event flow
        btn.addEventListener('click', () => {
            const t = performance.timeOrigin + performance.now();
            localStorage.setItem(`__dom_handled_${tag}`, String(t));
        }, { once: true, capture: true });
        """,
        element,
        tag,
    )


def mark_before_dispatch(driver, tag="add_to_cart"):
    """
    Records a timestamp immediately before we attempt to dispatch the click.
    """
    driver.execute_script(
        """
        const tag = arguments[0];
        const t = performance.timeOrigin + performance.now();
        localStorage.setItem(`__dom_before_${tag}`, String(t));
        """,
        tag,
    )


def read_dom_click_metrics(driver, tag="add_to_cart"):
    """
    Reads stored timestamps from localStorage.
    Returns (delay_ms, before_ms, handled_ms) or (None, before, handled) if incomplete.
    """
    before = driver.execute_script("return localStorage.getItem(arguments[0]);", f"__dom_before_{tag}")
    handled = driver.execute_script("return localStorage.getItem(arguments[0]);", f"__dom_handled_{tag}")

    before_ms = float(before) if before else None
    handled_ms = float(handled) if handled else None

    if before_ms is not None and handled_ms is not None:
        return (handled_ms - before_ms), before_ms, handled_ms

    return None, before_ms, handled_ms


def read_reservation_network_request(driver, start_mono, timeout=5):
    """
    Returns milliseconds between click dispatch and the reservation/cart API request.
    """
    import json
    import time

    start = time.perf_counter()

    while time.perf_counter() - start < timeout:

        logs = driver.get_log("performance")

        for entry in logs:
            message = json.loads(entry["message"])["message"]

            if message["method"] != "Network.requestWillBeSent":
                continue

            url = message["params"]["request"]["url"]

            # Ignore browser-internal requests
            if url.startswith("chrome://") or url.startswith("data:") or url.startswith("blob:"):
                continue

            # Only track recreation.gov traffic
            if "recreation.gov" not in url:
                continue

            # Detect the exact cart API endpoint
            if "/api/cart/" in url and "shoppingcart" in url:
                return (time.perf_counter() - start_mono) * 1000, url           

        time.sleep(0.01)

    return None, None
    

def wait_for_checkout_navigation(driver, timeout=15):
    """
    Waits for URL change. (Checkout URL patterns vary; URL-change alone is still useful.)
    """
    start_url = driver.current_url
    t0 = time.time()
    while time.time() - t0 < timeout:
        url = driver.current_url
        if url != start_url:
            return url
        time.sleep(0.05)
    return driver.current_url

def schedule_and_click(driver: webdriver.Chrome, add_btn) -> None:
    # 1) Ask user for target time
    while True:
        target_time_str = input(
            "⏳ Enter the Pacific Time to click 'Add to Cart' (format H:MM:SSAM or H:MM:SSPM, e.g., 7:00:00AM): "
        ).strip().upper()
        try:
            target_time = parse_target_time_str(target_time_str)
            break
        except ValueError:
            info("⚠️ Invalid format. Use H:MM:SSAM or H:MM:SSPM (e.g., 7:00:00AM). Try again.")

    # 2) NTP sync (multi-sample) early
    sync = sync_ntp_offset()

    # 3) Build true target datetime (PST)
    true_target = wallclock_target_datetime_today_pst(target_time)

    # 4) Convert to monotonic deadline
    mono_deadline, local_target = compute_monotonic_deadline(true_target, sync.offset_seconds)

    info("")
    info(f"🎯 True target PST:   {true_target.strftime('%Y-%m-%d %H:%M:%S.%f %Z')}")
    info(f"🧭 Local target PST:  {local_target.strftime('%Y-%m-%d %H:%M:%S.%f %Z')}  (after NTP offset)")
    info(f"🧪 Deadline fudge:    {DEADLINE_FUDGE_SECONDS:+.6f}s (negative fires earlier)")
    info("⏳ Armed. Waiting...")
    info("")

    # 5) Wait until we're close (T-2s), then re-acquire & re-arm.
    while True:
        remaining = mono_deadline - time.perf_counter()
        if remaining <= 2.0:
            break
        time.sleep(0.25)

    # Always re-acquire the element near the end
    try:
        add_btn = driver.find_element(By.ID, "add-cart-campsite")
    except Exception as e:
        info(f"❌ Could not re-find 'Add to Cart' button at T-2s: {e}")
        raise

    # Quick sanity check
    try:
        _ = add_btn.is_enabled()
    except Exception as e:
        info(f"❌ Button found but not usable at T-2s: {e}")
        raise

    # Arm DOM timing metrics (persist across navigation via localStorage)
    try:
        arm_dom_click_metrics(driver, add_btn, tag="add_to_cart")
    except Exception as e:
        info(f"⚠️ Failed to arm DOM timing metrics (continuing anyway): {e}")

    # 6) Final timing window: disable GC, wait, sample mono_actual immediately, then instrument + click
    ensure_csv_header(LOG_CSV)
    gc.disable()

    click_error = None
    dom_click_delay_ms = None
    checkout_url = None
    stamped_dispatch = None

    try:
        wait_until_monotonic(mono_deadline)

        # CRITICAL: sample perf_counter immediately after the wait (no webdriver calls before this)
        mono_actual = time.perf_counter()

        # Browser-side timestamp immediately before dispatch
        try:
            mark_before_dispatch(driver, tag="add_to_cart")
        except Exception as e:
            info(f"⚠️ Failed to mark before-dispatch DOM timestamp: {e}")

        method, click_error = click_fast(driver, add_btn)
        network_delay_ms, network_url = read_reservation_network_request(driver, mono_actual)

        # Timestamp right after we issue the click command (not after waiting for navigation)
        stamped_dispatch = now_pst().isoformat()

    finally:
        gc.enable()

    # 7) Compute monotonic scheduling error with multiple units
    mono_error_s = (mono_actual - mono_deadline)
    mono_error_ms = mono_error_s * 1000.0
    mono_error_us = mono_error_s * 1_000_000.0
    direction = "late" if mono_error_s > 0 else "early"

    # 8) Wait briefly for navigation and read DOM metrics after navigation
    try:
        checkout_url = wait_for_checkout_navigation(driver, timeout=15)
    except Exception:
        checkout_url = driver.current_url

    try:
        dom_click_delay_ms, before_ms, handled_ms = read_dom_click_metrics(driver, tag="add_to_cart")
    except Exception as e:
        info(f"⚠️ Failed to read DOM timing metrics: {e}")
        dom_click_delay_ms = None

    # Record local timestamp after navigation wait (optional, for debugging)
    stamped_post = now_pst().isoformat()

    # 9) CLI output
    info(f"🚀 Click dispatched. Method={method}")
    info(f"⏱️ Monotonic scheduling error: {mono_error_ms:+.6f} ms  ({mono_error_us:+.1f} µs, {mono_error_s:+.9f} s) [{direction}]")

    if dom_click_delay_ms is None:
        info("🧩 DOM timing: dispatch→handler not captured (possible: click blocked, DOM replaced, or extremely fast navigation).")
    else:
        info(f"🧩 DOM timing: dispatch→handler = {dom_click_delay_ms:.3f} ms (browser-side)")
        
    if network_delay_ms is not None:
        info(f"🌐 Reservation API request: {network_delay_ms:.3f} ms after click dispatch")
        info(f"🔗 Request URL: {network_url}")
    else:
        info("🌐 Reservation request timing not detected")

    if checkout_url:
        info(f"🧭 Post-click URL: {checkout_url}")

    # 10) CSV logging
    # Use stamped_dispatch for timestamp_local so it reflects click dispatch time.
    append_csv(LOG_CSV, [
        stamped_dispatch or stamped_post,
        true_target.isoformat(),
        local_target.isoformat(),
        f"{sync.offset_seconds:+.6f}",
        f"{sync.rtt_seconds*1000:.1f}",
        f"{DEADLINE_FUDGE_SECONDS:+.6f}",
        f"{mono_deadline:.9f}",
        f"{mono_actual:.9f}",
        f"{mono_error_ms:+.6f}",
        f"{dom_click_delay_ms:.3f}" if dom_click_delay_ms is not None else "",
        f"{network_delay_ms:.3f}" if network_delay_ms else "",
        network_url or "",
        method,
        click_error or "",
    ])

    info(f"🧾 Logged to {LOG_CSV}")


def main():
    # Campsite number prompt
    campsite_number = input("🔹 Please enter the campsite number (e.g., '2460' for Campsite #100): ").strip()
    if not campsite_number.isdigit():
        info("❌ Campsite number should be digits (e.g., 229). Exiting.")
        sys.exit(1)

    # Start driver
    driver = build_driver()

    # Determine profile path (same logic used in build_driver)
    profile_path = os.path.join(os.getcwd(), "profiles", "rec1")

    try:
        driver.get("https://www.recreation.gov")

        # Simple login/setup instructions
        setup_or_continue(driver, profile_path)

        navigate_to_site(driver, campsite_number)
        add_btn = wait_for_add_to_cart_button(driver, timeout=90)
        schedule_and_click(driver, add_btn)

        input("🔹 Press ENTER to close the browser...")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
