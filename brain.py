import os
import random
import json
try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None
import shutil
import subprocess
import re
import time
import sys
import urllib.request
import urllib.error
import urllib.parse
from typing import Any
from datetime import datetime

from speech import speak
from moods import get_mood
from jokes import confused, greetings, random_reply

MEMORY_FILE = "memory.json"
WAKE_WORD = "riva"

# Voice wake phrases. When require_wake_word=True, the command must start with
# one of these phrases, e.g. "hi riva open chrome".
_WAKE_PREFIX_RE = re.compile(r"^\s*(hi|hey)\s+riva\b[\s,!.:-]*", re.IGNORECASE)

# After a wake phrase, keep accepting commands without repeating the wake phrase.
# Default is effectively "until go to sleep".
_DEFAULT_AWAKE_WINDOW_SEC = 60 * 60 * 24 * 365 * 10  # 10 years

# When asleep, don't spam reminders on every sentence.
_DEFAULT_WAKE_REMINDER_COOLDOWN_SEC = 8


def _strip_wake_prefix(command: str) -> tuple[bool, str]:
    """Return (woke, remaining_command) after stripping a supported wake prefix."""
    if not command:
        return False, ""
    m = _WAKE_PREFIX_RE.match(command)
    if not m:
        return False, command.strip()
    rest = command[m.end():].strip()
    return True, rest

ASSISTANT_NAME = "Riva"
CREATOR_NAME = "MD. Rifat Islam Rizvi"


PROJECT_REPO_URL = "https://github.com/ripro805/Riva-1.o-AI-Assistant"

# If you have multiple Chrome profiles, launching Chrome without specifying one can
# open the profile picker. We pin a profile directory by default.
# Override with env vars:
# - RIVA_CHROME_PROFILE_DIR (e.g., "Default", "Profile 1")
# - RIVA_CHROME_USER_DATA_DIR (optional full path to Chrome User Data)
_DEFAULT_CHROME_PROFILE_DIR = "Default"


_SITE_TARGETS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Facebook", "https://www.facebook.com/", ("facebook", "face book", "fb")),
    ("YouTube", "https://www.youtube.com/", ("youtube", "you tube")),
    ("Gmail", "https://mail.google.com/", ("gmail", "g mail")),
    ("Google", "https://www.google.com/", ("google",)),
    # Keep WhatsApp Web only for explicit "web" requests.
    ("WhatsApp Web", "https://web.whatsapp.com/", ("whatsapp web", "web whatsapp", "whats web")),
    ("Instagram", "https://www.instagram.com/", ("instagram", "insta")),
]


def _open_whatsapp_desktop() -> bool:
    """Open WhatsApp Desktop app on Windows.

    Returns True if we successfully triggered a launch attempt.

    Notes:
    - The `whatsapp:` protocol is supported when WhatsApp Desktop is installed.
    - The AppUserModelId used below is a common Microsoft Store package id; it may vary.
    """
    # 1) Try protocol handler (best effort).
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", "whatsapp:"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        pass

    # 2) Try common Microsoft Store AppUserModelId.
    try:
        subprocess.Popen(
            [
                "explorer.exe",
                "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _find_chrome_exe() -> str | None:
    """Best-effort lookup for Google Chrome on Windows.

    Returns a path to chrome.exe if found, otherwise None.
    """
    for name in ("chrome", "chrome.exe"):
        p = shutil.which(name)
        if p:
            return p

    program_files = os.environ.get("PROGRAMFILES", r"C:\\Program Files")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    candidates = [
        os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"))

    for c in candidates:
        if os.path.exists(c):
            return c

    return None


def _open_chrome(url: str | None = None) -> bool:
    """Open Google Chrome (optionally a URL).

    Returns True if Chrome was launched, False if we had to fall back.
    """
    chrome = _find_chrome_exe()
    if chrome:
        # Pin a specific Chrome profile to avoid the profile picker UI.
        profile_dir = (os.environ.get("RIVA_CHROME_PROFILE_DIR") or "").strip() or _DEFAULT_CHROME_PROFILE_DIR
        user_data_dir = (os.environ.get("RIVA_CHROME_USER_DATA_DIR") or "").strip()

        args = [chrome]
        if user_data_dir:
            args.append(f"--user-data-dir={user_data_dir}")
        if profile_dir:
            args.append(f"--profile-directory={profile_dir}")

        if url:
            # Passing a URL typically opens a new tab if Chrome is already running.
            args.extend(["--new-tab", url])
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # Fallback: open URL in default browser if present.
    if url:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
        except Exception:
            return False
        return False

    return False


def _match_site_target(command: str) -> tuple[str, str] | None:
    t = (command or "").lower()
    for display_name, url, patterns in _SITE_TARGETS:
        if any(p in t for p in patterns):
            return display_name, url
    return None


def _close_explorer_windows() -> bool:
    """Best-effort: close all open File Explorer windows on Windows."""
    if not os.name == "nt":
        return False
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(New-Object -ComObject Shell.Application).Windows() "
                "| Where-Object { $_.FullName -like '*\\explorer.exe' } "
                "| ForEach-Object { $_.Quit() }",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _close_active_explorer_window() -> bool:
    """Close only the currently active File Explorer window (Windows best-effort)."""
    if not os.name == "nt":
        return False
    try:
        # Match the active explorer window by HWND.
        # If the foreground window isn't explorer, do nothing.
        ps = (
            "Add-Type @'\n"
            "using System;\n"
            "using System.Runtime.InteropServices;\n"
            "public class Win32 {\n"
            "  [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();\n"
            "}\n"
            "'@; "
            "$hwnd=[Win32]::GetForegroundWindow(); "
            "$wins=(New-Object -ComObject Shell.Application).Windows(); "
            "$w=$wins | Where-Object { $_.FullName -like '*\\explorer.exe' -and $_.HWND -eq $hwnd } | Select-Object -First 1; "
            "if ($null -ne $w) { $w.Quit(); 'CLOSED' } else { 'NOACTIVE' }"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out.upper() == "CLOSED"
    except Exception:
        return False


def _taskkill(image_name: str) -> bool:
    """Best-effort process close on Windows by image name (e.g., chrome.exe)."""
    if not os.name == "nt":
        return False

    # First try without /F (slightly gentler), then force if needed.
    try:
        r = subprocess.run(
            ["taskkill", "/IM", image_name, "/T"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["taskkill", "/F", "/IM", image_name, "/T"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except Exception:
        return False


def _run_powershell(ps: str, *, sta: bool = False) -> str:
    """Run a PowerShell snippet and return stdout (best-effort)."""
    args = ["powershell"]
    if sta:
        args.append("-STA")
    args.extend(["-NoProfile", "-Command", ps])
    return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True)


def _list_top_level_windows() -> list[dict[str, Any]]:
    """Enumerate top-level windows (visible and background) on Windows.

    Returns list of dicts: hwnd (int), pid (int), process (str), title (str), class (str)
    """
    if os.name != "nt":
        return []

    # Use user32 EnumWindows + GetWindowText + GetClassName.
    # We include windows even if not visible (background) to satisfy detection rule.
    ps = (
        "Add-Type @'\n"
        "using System;\n"
        "using System.Text;\n"
        "using System.Runtime.InteropServices;\n"
        "public class Win32W {\n"
        "  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);\n"
        "  [DllImport(\"user32.dll\")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);\n"
        "  [DllImport(\"user32.dll\")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);\n"
        "  [DllImport(\"user32.dll\")] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);\n"
        "  [DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);\n"
        "}\n"
        "'@; "
        "$results = New-Object System.Collections.Generic.List[object]; "
        "[Win32W]::EnumWindows({ param($h,$l) "
        "  $sb = New-Object System.Text.StringBuilder 512; "
        "  [void][Win32W]::GetWindowText($h, $sb, $sb.Capacity); $title=$sb.ToString(); "
        "  $cb = New-Object System.Text.StringBuilder 256; "
        "  [void][Win32W]::GetClassName($h, $cb, $cb.Capacity); $cls=$cb.ToString(); "
        "  $pid=0; [void][Win32W]::GetWindowThreadProcessId($h, [ref]$pid); "
        "  $pname=''; try { $pname=(Get-Process -Id $pid -ErrorAction SilentlyContinue).ProcessName } catch { } "
        "  $results.Add([pscustomobject]@{ hwnd=[int64]$h; pid=[int]$pid; process=$pname; title=$title; class=$cls }) | Out-Null; "
        "  return $true "
        "}, [IntPtr]::Zero) | Out-Null; "
        "$results | ConvertTo-Json -Compress"
    )
    try:
        out = _run_powershell(ps)
        out = (out or "").strip()
        if not out:
            return []
        data = json.loads(out)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            return [data]
        return []
    except Exception:
        return []


def _window_title_contains_any(title: str, needles: tuple[str, ...]) -> bool:
    t = (title or "").lower()
    return any(n.lower() in t for n in needles if n)


def _detect_by_process_or_window(
    *,
    image_names: tuple[str, ...],
    title_needles: tuple[str, ...],
    process_name_needles: tuple[str, ...] = (),
) -> tuple[bool, list[dict[str, Any]]]:
    """Detection: scan running processes + scan windows.

    Returns: (detected, matching_windows)
    """
    detected_proc = any(_is_process_running(n) for n in image_names if n)
    wins = _list_top_level_windows()

    matched: list[dict[str, Any]] = []
    for w in wins:
        pname = (w.get("process") or "").lower()
        title = (w.get("title") or "")
        if process_name_needles and not any(n.lower() == pname or n.lower() in pname for n in process_name_needles):
            continue
        if title_needles and not _window_title_contains_any(title, title_needles):
            continue
        matched.append(w)

    detected = detected_proc or bool(matched)
    return detected, matched


def _close_windows_hwnd(hwnds: list[int]) -> bool:
    """Try graceful close (WM_CLOSE) for the provided HWNDs."""
    if os.name != "nt" or not hwnds:
        return False
    try:
        joined = ",".join(str(int(h)) for h in hwnds if h)
        ps = (
            "Add-Type @'\n"
            "using System;\n"
            "using System.Runtime.InteropServices;\n"
            "public class Win32C {\n"
            "  public const int WM_CLOSE = 0x0010;\n"
            "  [DllImport(\"user32.dll\")] public static extern bool PostMessage(IntPtr hWnd, int Msg, IntPtr wParam, IntPtr lParam);\n"
            "}\n"
            "'@; "
            f"$hwnds=@({joined}); "
            "foreach ($h in $hwnds) { try { [Win32C]::PostMessage([IntPtr]$h, [Win32C]::WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null } catch { } }; "
            "'OK'"
        )
        _run_powershell(ps)
        return True
    except Exception:
        return False


def _close_common_apps_opened_by_riva() -> None:
    """Close common apps/sites Riva opens (best effort).

    Note: Sites like YouTube/Facebook/Gmail/Repo are tabs in Chrome.
    Closing Chrome closes those.
    """
    # Chrome covers YouTube/Facebook/Gmail/Repo tabs.
    _taskkill("chrome.exe")

    # VS Code
    _taskkill("Code.exe")

    # WhatsApp Desktop variants
    _taskkill("WhatsApp.exe")
    _taskkill("WhatsAppApp.exe")
    _taskkill("WhatsAppDesktop.exe")


def _close_app_target(target: str) -> bool:
    """Close a supported application target.

    Detection-first policy:
    - Scan processes
    - Scan visible/background windows
    Action:
    - Try graceful close via WM_CLOSE
    - Fallback to taskkill

    Returns True if the target was detected (and we attempted to close it).
    """
    t = (target or "").strip().lower()

    if t in ("vscode", "vs code", "visual studio code", "code"):
        detected, wins = _detect_by_process_or_window(
            image_names=("Code.exe",),
            title_needles=("visual studio code",),
            process_name_needles=("code",),
        )
        if not detected:
            return False
        hwnds = [int(w.get("hwnd") or 0) for w in wins if w.get("hwnd")]
        _close_windows_hwnd(hwnds)
        time.sleep(0.35)
        if _is_process_running("Code.exe"):
            _taskkill("Code.exe")
        return True

    if t in ("whatsapp", "whatsapp desktop", "what's app", "what app"):
        detected, wins = _detect_by_process_or_window(
            image_names=("WhatsApp.exe", "WhatsAppApp.exe", "WhatsAppDesktop.exe"),
            title_needles=("whatsapp",),
            process_name_needles=(),
        )
        if not detected:
            return False
        hwnds = [int(w.get("hwnd") or 0) for w in wins if w.get("hwnd")]
        _close_windows_hwnd(hwnds)
        time.sleep(0.35)
        if _is_process_running("WhatsApp.exe") or _is_process_running("WhatsAppApp.exe") or _is_process_running("WhatsAppDesktop.exe"):
            _taskkill("WhatsApp.exe")
            _taskkill("WhatsAppApp.exe")
            _taskkill("WhatsAppDesktop.exe")
        return True

    if t in ("chrome", "google chrome"):
        detected, wins = _detect_by_process_or_window(
            image_names=("chrome.exe",),
            title_needles=(),
            process_name_needles=("chrome",),
        )
        if not detected:
            return False
        hwnds = [int(w.get("hwnd") or 0) for w in wins if w.get("hwnd")]
        _close_windows_hwnd(hwnds)
        time.sleep(0.25)
        if _is_process_running("chrome.exe"):
            _taskkill("chrome.exe")
        return True

    return False


def _chrome_cdp_list_pages() -> list[dict[str, Any]]:
    """List Chrome pages via DevTools (if Chrome was launched with remote debugging)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=0.35) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []
    except Exception:
        return []


def _chrome_cdp_close_page(page_id: str) -> bool:
    try:
        if not page_id:
            return False
        url = f"http://127.0.0.1:9222/json/close/{urllib.parse.quote(page_id)}"
        with urllib.request.urlopen(url, timeout=0.35) as r:
            _ = r.read()
        return True
    except Exception:
        return False


def _get_active_chrome_url_if_foreground() -> tuple[bool, str]:
    """Best-effort: read the active Chrome tab URL if Chrome is foreground.

    Returns: (is_chrome_foreground, url_or_empty)
    """
    if os.name != "nt":
        return False, ""

    try:
        ps = (
            "Add-Type @'\n"
            "using System;\n"
            "using System.Runtime.InteropServices;\n"
            "public class Win32A {\n"
            "  [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();\n"
            "  [DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);\n"
            "}\n"
            "'@; "
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$hwnd=[Win32A]::GetForegroundWindow(); "
            "$pid=0; [Win32A]::GetWindowThreadProcessId($hwnd, [ref]$pid) | Out-Null; "
            "if ($pid -le 0) { 'NOTCHROME'; exit } ; "
            "$p=Get-Process -Id $pid -ErrorAction SilentlyContinue; "
            "if ($null -eq $p) { 'NOTCHROME'; exit } ; "
            "if ($p.ProcessName -ne 'chrome') { 'NOTCHROME'; exit } ; "
            "[System.Windows.Forms.SendKeys]::SendWait('^l'); Start-Sleep -Milliseconds 120; "
            "[System.Windows.Forms.SendKeys]::SendWait('^c'); Start-Sleep -Milliseconds 120; "
            "$url=[System.Windows.Forms.Clipboard]::GetText(); "
            "if ([string]::IsNullOrWhiteSpace($url)) { 'URL:'; exit } ; "
            "'URL:' + $url"
        )
        out = subprocess.check_output(
            ["powershell", "-STA", "-NoProfile", "-Command", ps],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out.upper() == "NOTCHROME":
            return False, ""
        if out.startswith("URL:"):
            return True, out[4:].strip()
        return False, ""
    except Exception:
        return False, ""


def _detect_chrome_tab_target(target: str) -> tuple[bool, str]:
    """Detect whether a target tab appears to be open.

    Returns: (found, method)
    method: CDP | ACTIVE_TAB | WINDOW_TITLE | NONE
    """
    if not _is_process_running("chrome.exe"):
        return False, "NONE"

    t = (target or "").strip().lower()
    if t == "youtube":
        url_patterns = ("youtube.com", "youtu.be")
        title_patterns = ("youtube",)
    elif t == "facebook":
        url_patterns = ("facebook.com",)
        title_patterns = ("facebook",)
    elif t == "gmail":
        url_patterns = ("mail.google.com", "gmail.com")
        title_patterns = ("gmail", "inbox")
    else:
        url_patterns = ("github.com",)
        title_patterns = ("github",)

    # 1) CDP (best): enumerate all tabs and check URL/title.
    pages = _chrome_cdp_list_pages()
    if pages:
        for p in pages:
            u = (p.get("url") or "").lower()
            ti = (p.get("title") or "").lower()
            if any(pat in u for pat in url_patterns) or any(pat in ti for pat in title_patterns):
                return True, "CDP"

    # 2) Foreground active-tab URL via clipboard (pure detection).
    is_fg, url = _get_active_chrome_url_if_foreground()
    if is_fg:
        u = (url or "").lower()
        if any(pat in u for pat in url_patterns):
            return True, "ACTIVE_TAB"

    # 3) Window-title detection (active tab titles per window).
    wins = _list_top_level_windows()
    for w in wins:
        if (w.get("process") or "").lower() != "chrome":
            continue
        title = (w.get("title") or "")
        if _window_title_contains_any(title, title_patterns):
            return True, "WINDOW_TITLE"

    return False, "NONE"


def _close_chrome_tab_target(target: str) -> str:
    """Close a Chrome tab target.

    Returns one of:
    - CHROME_NOT_RUNNING
    - TAB_NOT_FOUND
    - CLOSED
    """
    if not _is_process_running("chrome.exe"):
        return "CHROME_NOT_RUNNING"

    t = (target or "").strip().lower()
    if t not in ("youtube", "facebook", "gmail", "repo", "github"):
        return "TAB_NOT_FOUND"

    # 1) CDP: enumerate and close the first matching page.
    pages = _chrome_cdp_list_pages()
    if pages:
        if t == "youtube":
            url_patterns = ("youtube.com", "youtu.be")
        elif t == "facebook":
            url_patterns = ("facebook.com",)
        elif t == "gmail":
            url_patterns = ("mail.google.com", "gmail.com")
        else:
            url_patterns = ("github.com",)

        matches: list[dict[str, Any]] = []
        for p in pages:
            u = (p.get("url") or "").lower()
            if any(pat in u for pat in url_patterns):
                matches.append(p)

        if matches:
            # Prefer active if available; otherwise first match.
            chosen = None
            for m in matches:
                if m.get("active") is True:
                    chosen = m
                    break
            chosen = chosen or matches[0]
            pid = str(chosen.get("id") or "")
            if pid and _chrome_cdp_close_page(pid):
                return "CLOSED"

    # 2) Fallback: close active tab ONLY when Chrome is foreground (existing behavior).
    res = _close_active_chrome_tab_for_target("github" if t in ("repo", "github") else t)
    if res == "CLOSED":
        return "CLOSED"

    # 3) Last resort (no CDP, Chrome not foreground): activate a matching Chrome window by title and Ctrl+W.
    if t == "youtube":
        title_patterns = ("youtube",)
    elif t == "facebook":
        title_patterns = ("facebook",)
    elif t == "gmail":
        title_patterns = ("gmail",)
    else:
        title_patterns = ("github",)

    try:
        wins = _list_top_level_windows()
        chosen_hwnd = 0
        for w in wins:
            if (w.get("process") or "").lower() != "chrome":
                continue
            title = (w.get("title") or "")
            if _window_title_contains_any(title, title_patterns):
                chosen_hwnd = int(w.get("hwnd") or 0)
                break

        if chosen_hwnd:
            ps = (
                "Add-Type @'\n"
                "using System;\n"
                "using System.Runtime.InteropServices;\n"
                "public class Win32F {\n"
                "  [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);\n"
                "  [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);\n"
                "}\n"
                "'@; "
                "Add-Type -AssemblyName System.Windows.Forms; "
                f"$h=[IntPtr]{chosen_hwnd}; "
                "[Win32F]::ShowWindow($h, 5) | Out-Null; "  # SW_SHOW
                "[Win32F]::SetForegroundWindow($h) | Out-Null; "
                "Start-Sleep -Milliseconds 120; "
                "[System.Windows.Forms.SendKeys]::SendWait('^w'); 'CLOSED'"
            )
            out = subprocess.check_output(
                ["powershell", "-STA", "-NoProfile", "-Command", ps],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if (out or "").upper() == "CLOSED":
                return "CLOSED"
    except Exception:
        pass

    return "TAB_NOT_FOUND"


def _is_process_running(image_name: str) -> bool:
    """Return True if a process with this image name appears to be running."""
    try:
        target = (image_name or "").lower()
        if psutil is not None:
            for p in psutil.process_iter(["name"]):
                name = (p.info.get("name") or "").lower()
                if name == target:
                    return True
            return False

        # Fallback (Windows): tasklist
        if os.name == "nt" and target:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"IMAGENAME eq {target}"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return target in out.lower()
    except Exception:
        pass
    return False


def _close_active_chrome_tab_for_target(target: str) -> str:
    """Best-effort: close the active Chrome tab if it matches target.

    Returns one of: CLOSED, NOTCHROME, NOURL, NOTMATCH, ERROR

    Note:
    - This does not enumerate tabs. It only inspects the *active* Chrome window/tab
      using SendKeys + clipboard.
    - Requires Chrome to be the foreground window.
    """
    if not os.name == "nt":
        return "ERROR"

    t = (target or "").strip().lower()
    if t == "youtube":
        patterns = ["youtube.com", "youtu.be"]
    elif t == "facebook":
        patterns = ["facebook.com"]
    elif t == "gmail":
        patterns = ["mail.google.com", "gmail.com"]
    elif t in ("repo", "github"):
        patterns = ["github.com/ripro805/riva-1.o-ai-assistant", "github.com/ripro805"]
    else:
        return "ERROR"

    # Use PowerShell in STA mode for Clipboard.
    try:
        ps = (
            "Add-Type @'\n"
            "using System;\n"
            "using System.Runtime.InteropServices;\n"
            "public class Win32 {\n"
            "  [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();\n"
            "  [DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);\n"
            "}\n"
            "'@; "
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$hwnd=[Win32]::GetForegroundWindow(); "
            "$pid=0; [Win32]::GetWindowThreadProcessId($hwnd, [ref]$pid) | Out-Null; "
            "if ($pid -le 0) { 'ERROR'; exit } ; "
            "$p=Get-Process -Id $pid -ErrorAction SilentlyContinue; "
            "if ($null -eq $p) { 'ERROR'; exit } ; "
            "if ($p.ProcessName -ne 'chrome') { 'NOTCHROME'; exit } ; "
            "[System.Windows.Forms.SendKeys]::SendWait('^l'); Start-Sleep -Milliseconds 120; "
            "[System.Windows.Forms.SendKeys]::SendWait('^c'); Start-Sleep -Milliseconds 120; "
            "$url=[System.Windows.Forms.Clipboard]::GetText(); "
            "if ([string]::IsNullOrWhiteSpace($url)) { 'NOURL'; exit } ; "
            "$u=$url.ToLowerInvariant(); "
            "$patterns=@('" + "','".join(patterns) + "'); "
            "$match=$false; foreach ($pat in $patterns) { if ($u -like ('*' + $pat + '*')) { $match=$true } } ; "
            "if (-not $match) { 'NOTMATCH'; exit } ; "
            "[System.Windows.Forms.SendKeys]::SendWait('^w'); 'CLOSED'"
        )
        out = subprocess.check_output(
            ["powershell", "-STA", "-NoProfile", "-Command", ps],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        out_u = out.upper()
        if out_u in ("CLOSED", "NOTCHROME", "NOURL", "NOTMATCH"):
            return out_u
        return "ERROR"
    except Exception:
        return "ERROR"


def _intro_text() -> str:
    return f"Hi! I'm {ASSISTANT_NAME}, your AI assistant created by {CREATOR_NAME}. How can I help you today?"


def _capabilities_lines() -> list[str]:
    return [
        "I can: open VS Code, open Chrome, open websites (YouTube/Facebook), open the current folder, check battery, shut down your PC, and go to sleep.",
        "Try: open vs code; open chrome; open youtube; open folder; battery; shutdown; go to sleep."
    ]


def _is_yes(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ("yes", "yeah", "yep", "ok", "okay", "confirm", "do it", "sure"))


def _is_no(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ("no", "nope", "cancel", "stop", "don't", "do not"))

def load_memory():
    with open(MEMORY_FILE, "r") as f:
        data = json.load(f)
        # Backward-compatible defaults
        data.setdefault("pending_action", None)
        data.setdefault("pending_url", None)
        data.setdefault("awake_until", 0.0)
        data.setdefault("wake_reminder_until", 0.0)
        return data

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def process(command, require_wake_word: bool = True):
    # Normalize
    command = (command or "").lower().strip()
    # Whisper often returns trailing punctuation like "time." or "go to sleep.".
    # Normalize by stripping most punctuation and collapsing whitespace.
    try:
        # Normalize smart quotes
        command = command.replace("’", "'").replace("‘", "'")
        # Keep letters/numbers/underscore/whitespace/apostrophe; drop the rest.
        command = re.sub(r"[^\w\s']+", " ", command)
        command = re.sub(r"\s+", " ", command).strip()
    except Exception:
        pass

    # EXIT COMMAND (hard stop)
    # User request: when they say "now,Leave" (normalized to "now leave"), say goodbye and exit.
    # This should work regardless of wake state.
    try:
        c_compact = command.replace(" ", "")
    except Exception:
        c_compact = command
    if (
        command == "now leave"
        or command == "leave now"
        or "now leave" in command
        or "leavenow" in c_compact
        or "nowleave" in c_compact
    ):
        speak("Okay. Goodbye! See you next time.")
        raise SystemExit(0)

    memory = load_memory()

    # Handle confirmations first (e.g., shutdown confirmation)
    pending = memory.get("pending_action")
    if pending:
        if _is_yes(command):
            if pending == "shutdown":
                speak("Confirmed. Shutting down now.")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                os.system("shutdown /s /t 5")
                return
            elif pending == "open_vscode":
                speak("Okay. Opening VS Code.")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                os.system("code")
                return
            elif pending == "open_folder":
                speak("Okay. Opening the current folder.")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                os.system("explorer .")
                return
            elif pending == "open_chrome":
                speak("Okay. Opening Chrome.")
                url = memory.get("pending_url")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                launched = _open_chrome(url=url)
                if not launched and not url:
                    speak("I couldn't find Chrome on this PC.")
                elif not launched and url:
                    speak("I couldn't find Chrome, so I opened it in your default browser.")
                return

            # Unknown pending action
            speak("Confirmed.")
            memory["pending_action"] = None
            memory["pending_url"] = None
            save_memory(memory)
            return

        if _is_no(command):
            speak("Okay, cancelled.")
            memory["pending_action"] = None
            memory["pending_url"] = None
            save_memory(memory)
            return

        speak("Please say yes to confirm, or say cancel.")
        return

    # Wake gating.
    # In voice mode (require_wake_word=True), Riva only responds after:
    #   "hi riva" or "hey riva"
    # After that, she stays awake until you say go to sleep.
    woke = False
    if require_wake_word:
        now = time.time()
        awake_until = float(memory.get("awake_until") or 0.0)
        is_awake = now < awake_until

        woke, stripped = _strip_wake_prefix(command)
        if woke:
            command = stripped
            # Optional override: RIVA_AWAKE_WINDOW_SEC
            window_raw = os.environ.get("RIVA_AWAKE_WINDOW_SEC", "")
            try:
                window = int(window_raw) if str(window_raw).strip() else int(_DEFAULT_AWAKE_WINDOW_SEC)
            except Exception:
                window = int(_DEFAULT_AWAKE_WINDOW_SEC)

            memory["awake_until"] = now + max(3, window)
            memory["wake_reminder_until"] = 0.0
            save_memory(memory)
        elif not is_awake:
            # Strict sleep/idle behavior: stay silent until wake phrase is used.
            return
    else:
        # In text mode, wake word is optional. If 'riva' appears anywhere, strip it.
        if WAKE_WORD in command:
            command = command.replace(WAKE_WORD, "").strip()
            woke = True

    # If wake word exists, remove it (even when already awake).
    if WAKE_WORD in command:
        command = command.replace(WAKE_WORD, "").strip()

    mood = get_mood()
    memory["last_command"] = command
    save_memory(memory)

    # If user just woke you up (e.g., "hi riva") with no extra command,
    # keep it simple and don't read out a long "Try: ..." script.
    if woke and not command:
        speak(_intro_text())
        return


    if "hello" in command or "hi" in command:
        speak(random_reply(greetings))

    elif (
        "help" in command
        or "what can you do" in command
        or "commands" in command
        or "features" in command
        or "capabilities" in command
    ):
        speak("Here is what I can do right now.")
        speak("Open VS Code: say open vs code.")
        speak("Open Chrome: say open chrome.")
        speak("Open a site in Chrome: say open youtube or open facebook.")
        speak("Open this project's GitHub repo: say open your repo.")
        speak("Open WhatsApp app: say open whatsapp.")
        speak("Open WhatsApp Web in Chrome: say open whatsapp web.")
        speak("Open current folder: say open folder.")
        speak("Close folder windows: say exit folder.")
        speak("Check battery: say battery.")
        speak("Shutdown PC: say shutdown (I will ask you to confirm).")
        speak("Exit: say now leave.")
        speak("Close apps: say close chrome / close vscode / close whatsapp.")
        speak("Close tabs (best effort): close youtube / close facebook / close gmail / close repo.")
        speak("Close current folder window: close folder.")

        # Mention wake behavior.
        if require_wake_word:
            speak("Voice mode wake phrase: say 'hi riva' or 'hey riva'.")
            speak("After waking once, you can talk normally until you exit.")
        else:
            speak("Text mode: wake phrase is optional.")

    elif (
        "who are you" in command
        or "what are you" in command
        or "introduce yourself" in command
        or "your name" in command
    ):
        speak(_intro_text())

    elif "who am i" in command or "do you know me" in command:
        whoami = [
            "You are my favorite human. Probably.",
            "You are the boss of this PC.",
            "You are a legend in progress.",
            "You are the one who keeps giving me tasks. And I respect that.",
            "You are the reason my code exists.",
        ]
        speak(random.choice(whoami))

    # Fuzzy matching for 'open vs code' to handle mis-transcriptions
    elif (
        "open vscode" in command
        or "open vs code" in command
        or "open this code" in command  # common mis-transcription
        or "open base code" in command  # another possible mis-transcription
        or "open best code" in command
    ):
        speak("Opening VS Code. Programmer mode on 🤓")
        os.system("code")

    # If it's close to the intent, confirm instead of doing the wrong thing.
    elif "open" in command and "code" in command:
        speak("Did you mean 'open VS Code'?")
        memory["pending_action"] = "open_vscode"
        memory["pending_url"] = None
        save_memory(memory)

    # Chrome / website shortcuts
    elif (
        "open chrome" in command
        or "open google chrome" in command
        or command.strip() == "chrome"
    ):
        speak("Opening Chrome.")
        launched = _open_chrome()
        if not launched:
            speak("I couldn't find Chrome on this PC.")

    elif (
        "open your repo" in command
        or "open your repository" in command
        or ("open" in command and "your" in command and "github" in command and "repo" in command)
        or ("open" in command and "your" in command and "github" in command and "repository" in command)
    ):
        speak("Opening the project repository on GitHub.")
        launched = _open_chrome(url=PROJECT_REPO_URL)
        if not launched:
            speak("I couldn't find Chrome, so I opened it in your default browser.")

    # WhatsApp Desktop (prefer app over web)
    elif (
        ("open" in command or "start" in command)
        and ("whatsapp" in command or "what's app" in command or "what app" in command)
        and "web" not in command
    ):
        speak("Opening WhatsApp app.")
        ok = _open_whatsapp_desktop()
        if not ok:
            speak("I couldn't open the WhatsApp app. Opening WhatsApp Web instead.")
            _open_chrome(url="https://web.whatsapp.com/")

    elif (
        ("open" in command or "new tab" in command or "open tab" in command)
        and _match_site_target(command) is not None
    ):
        site = _match_site_target(command)
        assert site is not None
        site_name, url = site
        speak(f"Opening {site_name}.")
        launched = _open_chrome(url=url)
        if not launched:
            speak("I couldn't find Chrome, so I opened it in your default browser.")

    elif "open" in command and ("chrome" in command or "crome" in command or "chrom" in command):
        speak("Did you mean 'open chrome'?")
        memory["pending_action"] = "open_chrome"
        memory["pending_url"] = None
        save_memory(memory)

    elif "open folder" in command:
        speak("Opening current folder.")
        os.system("explorer .")

    elif "open" in command and "folder" in command:
        speak("Did you mean 'open folder'?")
        memory["pending_action"] = "open_folder"
        memory["pending_url"] = None
        save_memory(memory)

    elif "battery" in command:
        if psutil is None:
            speak("Battery status is unavailable because the 'psutil' package is not installed.")
        else:
            battery = psutil.sensors_battery()
            if battery is None:
                speak("I couldn't read the battery status on this device.")
            else:
                speak(f"Battery is {battery.percent} percent.")

    elif (
        "time" == command
        or "current time" in command
        or "what time" in command
        or "tell me the time" in command
    ):
        now = datetime.now()
        # Example: 09:05 PM
        speak(f"It's {now.strftime('%I:%M %p')}.".lstrip("0"))

    elif "shutdown" in command:
        if mood == "happy":
            speak("You did great today.")
        elif mood == "sleepy":
            speak("Finally… good night.")

        speak("Do you want me to shut down the PC? Please say yes to confirm, or say cancel.")
        memory["pending_action"] = "shutdown"
        memory["pending_url"] = None
        save_memory(memory)

    # CLOSE COMMANDS
    elif command.startswith("close "):
        target = command[len("close "):].strip()
        if not target:
            speak("Please say close and then the target.")
            return

        # Normalize target for more robust matching (Whisper often inserts extra words/spaces).
        t = target.lower().strip()
        t_compact = t.replace("'", "").replace(" ", "")

        # Folder: close ONLY the active explorer window
        if ("folder" in t) or ("currentfolder" in t_compact):
            closed = _close_active_explorer_window()
            if closed:
                speak("Done.")
            else:
                speak("No folder window is currently active.")
            return

        # Applications
        if (
            ("vscode" in t_compact)
            or ("visualstudiocode" in t_compact)
            or ("whatsapp" in t_compact)
            or ("whatsapp" in t_compact)
            or ("whatapp" in t_compact)
            or ("chrome" in t_compact)
        ):
            # Choose a canonical app target for the closer.
            if "chrome" in t_compact:
                app_target = "chrome"
            elif "vscode" in t_compact or "visualstudiocode" in t_compact:
                app_target = "vscode"
            else:
                app_target = "whatsapp"

            attempted = _close_app_target(app_target)
            if attempted:
                speak("Done.")
            else:
                speak("That is not currently open.")
            return

        # Website tabs: best-effort only.
        if (
            ("youtube" in t_compact) or ("youtu" in t_compact) or ("youtub" in t_compact)
            or ("facebook" in t_compact) or ("fb" == t_compact)
            or ("gmail" in t_compact) or ("mailgoogle" in t_compact)
            or ("repo" in t_compact) or ("github" in t_compact) or ("githu" in t_compact)
        ):
            if ("youtube" in t_compact) or ("youtu" in t_compact):
                web_target = "youtube"
            elif ("facebook" in t_compact) or (t_compact == "fb"):
                web_target = "facebook"
            elif ("gmail" in t_compact) or ("mailgoogle" in t_compact):
                web_target = "gmail"
            else:
                web_target = "repo"

            result = _close_chrome_tab_target(web_target)
            if result == "CHROME_NOT_RUNNING":
                speak("Chrome is not currently running.")
            elif result == "CLOSED":
                speak("Done.")
            else:
                speak("The tab is not currently open.")
            return

        speak("I can't close that target.")
        return

    else:
        speak(random_reply(confused))
