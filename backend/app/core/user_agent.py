"""V17.3 — a small, dependency-free User-Agent parser.

Good enough to label a session list with a recognizable
device/browser/OS ("Chrome on Windows", "Safari on iPhone") — not a
claim of exhaustive/precise UA parsing (real UA strings are messy and
inconsistent across vendors). No third-party UA-parsing library is
added since this environment has no network access to install one and
none was already a project dependency; this covers the common cases
with plain regex and degrades to "Unknown" rather than guessing.
"""

import re


def parse_user_agent(user_agent: str | None) -> dict:
    if not user_agent:
        return {"browser": "Unknown", "os": "Unknown", "device": "Unknown"}

    ua = user_agent

    if re.search(r"iPhone", ua):
        device, os_name = "iPhone", "iOS"
    elif re.search(r"iPad", ua):
        device, os_name = "iPad", "iOS"
    elif re.search(r"Android", ua):
        device = "Mobile" if re.search(r"Mobile", ua) else "Tablet"
        os_match = re.search(r"Android\s*([\d.]+)?", ua)
        os_name = f"Android {os_match.group(1)}".strip() if os_match and os_match.group(1) else "Android"
    elif re.search(r"Windows NT", ua):
        device, os_name = "Desktop", "Windows"
    elif re.search(r"Macintosh|Mac OS X", ua):
        device, os_name = "Desktop", "macOS"
    elif re.search(r"Linux", ua):
        device, os_name = "Desktop", "Linux"
    else:
        device, os_name = "Unknown", "Unknown"

    if re.search(r"Edg/", ua):
        browser = "Edge"
    elif re.search(r"OPR/|Opera", ua):
        browser = "Opera"
    elif re.search(r"Chrome/", ua) and not re.search(r"Chromium/", ua):
        browser = "Chrome"
    elif re.search(r"CriOS/", ua):
        browser = "Chrome"
    elif re.search(r"FxiOS/|Firefox/", ua):
        browser = "Firefox"
    elif re.search(r"Version/.*Safari/", ua):
        browser = "Safari"
    else:
        browser = "Unknown"

    return {"browser": browser, "os": os_name, "device": device}
