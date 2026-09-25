"""
launcher.pyw — Silent Windows launcher for PaperTrade.io.
Starts the unified backend (with embedded production frontend) if not already running,
prompts for or retrieves browser preference (Chrome, Edge, etc.),
and automatically launches PaperTrade in the chosen browser.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
import winreg

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
VENV_PYTHON = os.path.join(BACKEND_DIR, "venv", "Scripts", "python.exe")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "browser_config.json")
ICON_PATH = os.path.join(PROJECT_ROOT, "resources", "app_icon.ico")
HEALTH_URL = "http://127.0.0.1:8000/api/health"
APP_URL = "http://localhost:8000"


def is_server_running(timeout=1.0):
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "PaperTradeLauncher"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _check_reg_key(root, subkey):
    try:
        with winreg.OpenKey(root, subkey) as k:
            val, _ = winreg.QueryValueEx(k, "")
            cleaned = val.strip('"').strip("'")
            if os.path.isfile(cleaned):
                return cleaned
    except Exception:
        pass
    return None


def detect_installed_browsers():
    """Detect major browsers installed on Windows via registry and standard file paths."""
    found = {}

    # 1. Registry App Paths (HKLM and HKCU)
    reg_candidates = [
        ("Google Chrome", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        ("Microsoft Edge", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        ("Brave", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"),
        ("Mozilla Firefox", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"),
    ]

    for name, subkey in reg_candidates:
        path = _check_reg_key(winreg.HKEY_LOCAL_MACHINE, subkey) or _check_reg_key(winreg.HKEY_CURRENT_USER, subkey)
        if path:
            found[name] = path

    # 2. Filesystem fallbacks
    common_paths = {
        "Google Chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "Microsoft Edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "Brave": [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ],
        "Mozilla Firefox": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
    }

    for name, paths in common_paths.items():
        if name not in found:
            for p in paths:
                if os.path.isfile(p):
                    found[name] = p
                    break

    return found


def get_saved_browser_pref():
    """Read saved browser preference from config file."""
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                b_name = data.get("browser")
                b_path = data.get("path")
                if b_path and os.path.isfile(b_path):
                    return b_name, b_path
        except Exception:
            pass
    return None, None


def save_browser_pref(name, path):
    """Save browser preference to config file."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"browser": name, "path": path}, f, indent=2)
    except Exception:
        pass


def prompt_browser_dialog(browsers):
    """Display a fast, native, dark-themed Tkinter dialog to choose browser."""
    import tkinter as tk

    root = tk.Tk()
    root.title("PaperTrade.io — Browser Selection")
    root.configure(bg="#0e1117")
    root.resizable(False, False)

    # Set icon if available
    if os.path.isfile(ICON_PATH):
        try:
            root.iconbitmap(ICON_PATH)
        except Exception:
            pass

    # Window geometry centered
    width, height = 380, 290
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max(0, int((screen_w - width) / 2))
    y = max(0, int((screen_h - height) / 2))
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.attributes("-topmost", True)

    selected_var = tk.StringVar(value=list(browsers.keys())[0])
    remember_var = tk.BooleanVar(value=True)
    result = {"name": list(browsers.keys())[0], "path": list(browsers.values())[0], "remember": True}

    # Header frame
    header = tk.Label(
        root,
        text="PAPERTRADE.IO",
        font=("Segoe UI", 12, "bold"),
        fg="#00e5ff",
        bg="#0e1117",
        pady=10,
    )
    header.pack()

    sub_label = tk.Label(
        root,
        text="Choose browser to open the trading terminal:",
        font=("Segoe UI", 9),
        fg="#a0aec0",
        bg="#0e1117",
    )
    sub_label.pack(pady=(0, 10))

    # Radio options frame
    frame = tk.Frame(root, bg="#161b22", padx=15, pady=10, highlightthickness=1, highlightbackground="#30363d")
    frame.pack(fill="x", padx=25, pady=5)

    for name in browsers.keys():
        r = tk.Radiobutton(
            frame,
            text=name,
            variable=selected_var,
            value=name,
            font=("Segoe UI", 10, "bold" if "Chrome" in name or "Edge" in name else "normal"),
            fg="#e6e8ec",
            bg="#161b22",
            selectcolor="#0e1117",
            activebackground="#161b22",
            activeforeground="#00e5ff",
            anchor="w",
            padx=10,
            pady=4,
        )
        r.pack(fill="x", anchor="w")

    # Remember checkbox
    cb = tk.Checkbutton(
        root,
        text="Remember my choice for future launches",
        variable=remember_var,
        font=("Segoe UI", 9),
        fg="#cbd5e1",
        bg="#0e1117",
        selectcolor="#161b22",
        activebackground="#0e1117",
        activeforeground="#ffffff",
        pady=8,
    )
    cb.pack()

    def on_launch():
        picked_name = selected_var.get()
        result["name"] = picked_name
        result["path"] = browsers.get(picked_name)
        result["remember"] = remember_var.get()
        root.destroy()

    btn = tk.Button(
        root,
        text="Launch PaperTrade",
        font=("Segoe UI", 10, "bold"),
        fg="#ffffff",
        bg="#2962ff",
        activebackground="#1e40af",
        activeforeground="#ffffff",
        relief="flat",
        padx=18,
        pady=6,
        command=on_launch,
        cursor="hand2",
    )
    btn.pack(pady=(5, 12))

    root.bind("<Return>", lambda event: on_launch())
    root.protocol("WM_DELETE_WINDOW", on_launch)

    root.mainloop()
    return result["name"], result["path"], result["remember"]


def resolve_browser(force_prompt=False, prompt_gui=True):
    """Determine which browser to use, prompting if needed."""
    if not force_prompt:
        b_name, b_path = get_saved_browser_pref()
        if b_name and b_path:
            return b_path

    browsers = detect_installed_browsers()
    if not browsers:
        return None  # Fallback to system default

    if len(browsers) == 1 and not force_prompt:
        name, path = next(iter(browsers.items()))
        save_browser_pref(name, path)
        return path

    if not prompt_gui:
        name, path = next(iter(browsers.items()))
        return path

    # Multiple browsers found or force_prompt requested
    name, path, remember = prompt_browser_dialog(browsers)
    if remember and name and path:
        save_browser_pref(name, path)
    return path


def open_browser(url, browser_path=None):
    """Open specified browser executable or fallback to default."""
    if browser_path and os.path.isfile(browser_path):
        try:
            subprocess.Popen([browser_path, url], creationflags=0x00000008 | 0x08000000)
            return
        except Exception:
            pass
    webbrowser.open(url)


def launch(open_browser_window=True, exit_on_complete=False, force_browser_select=False, prompt_gui=True):
    # Check command-line flags
    if "--select-browser" in sys.argv or "--reset-browser" in sys.argv:
        force_browser_select = True

    chosen_browser = resolve_browser(force_prompt=force_browser_select, prompt_gui=prompt_gui)

    # 1. Duplicate check: If server is already running, open browser and exit
    if is_server_running():
        if open_browser_window:
            open_browser(APP_URL, chosen_browser)
        if exit_on_complete:
            sys.exit(0)
        return True

    # 2. Server not running — start it in the background silently
    python_bin = VENV_PYTHON if os.path.isfile(VENV_PYTHON) else sys.executable

    # Detached, windowless, breakaway from job
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB

    cmd = [python_bin, "-m", "uvicorn", "main:app", "--port", "8000"]
    log_path = os.path.join(BACKEND_DIR, "server.log")

    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            subprocess.Popen(
                cmd,
                cwd=BACKEND_DIR,
                creationflags=creationflags,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=log_file,
            )
    except Exception as e:
        err_log = os.path.join(PROJECT_ROOT, "launcher_error.log")
        with open(err_log, "w", encoding="utf-8") as f:
            f.write(f"Failed to start server: {e}\n")
        if exit_on_complete:
            sys.exit(1)
        return False

    # 3. Wait for the server to become responsive
    max_wait = 10.0
    start_time = time.time()
    while time.time() - start_time < max_wait:
        if is_server_running(timeout=0.4):
            break
        time.sleep(0.2)

    # 4. Open selected browser to the application
    if open_browser_window:
        open_browser(APP_URL, chosen_browser)

    if exit_on_complete:
        sys.exit(0)
    return True


if __name__ == "__main__":
    launch(open_browser_window=True, exit_on_complete=True)
