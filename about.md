recgov-latency-tool

What this is
- Schedules a precise Add-to-Cart click (America/Los_Angeles time) using NTP offset and monotonic deadlines.
- Measures scheduler error (mono_deadline vs mono_actual).
- Measures browser-side click handling latency (DOM listener stored in localStorage).
- Measures click-to-request delay (DevTools Network.requestWillBeSent).

What this is not
- Not a CAPTCHA bypass.
- Not an auth bypass.
- Not a rate-limit evasion tool.
If a security control appears, treat it as a boundary.

Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Run
python run.py

First-run login flow (persistent profile)
- Chrome profile stored at ./profiles/rec1
- First run: log in manually in the automation Chrome window, then Ctrl+C to stop so cookies persist.
- Next runs: verify you're logged in, press ENTER to proceed.

Output
- timing_log.csv in the working directory.
- Columns:
  timestamp_local, true_target_pst, local_target_wallclock_pst,
  ntp_offset_s, ntp_rtt_ms, deadline_fudge_s,
  mono_deadline, mono_actual, mono_error_ms,
  dom_click_delay_ms, network_delay_ms, network_url,
  click_method, click_error

Portability
- Defaults to Selenium Manager (Selenium 4.6+).
- Optional webdriver-manager available by toggling config.USE_WEBDRIVER_MANAGER.
