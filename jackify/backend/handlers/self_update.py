import os
import sys
import json
import requests
import shutil
import tempfile
import time
from pathlib import Path

GITHUB_OWNER = "Omni-guides"
GITHUB_REPO = "Jackify"
ASSET_NAME = "jackify"
CONFIG_DIR = os.path.expanduser("~/.config/jackify")
TOKEN_PATH = os.path.join(CONFIG_DIR, "github_token")
LAST_CHECK_PATH = os.path.join(CONFIG_DIR, "last_update_check.json")

THROTTLE_HOURS = 6

def get_github_token():
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "r") as f:
            return f.read().strip()
    return None

def get_latest_release_info():
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    headers = {}
    token = get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"
    resp = requests.get(url, headers=headers, verify=True)
    if resp.status_code == 200:
        return resp.json()
    else:
        raise RuntimeError(f"Failed to fetch release info: {resp.status_code} {resp.text}")

def get_current_version():
    # This should match however Jackify stores its version
    try:
        from jackify import __version__
        return __version__
    except ImportError:
        return None

def should_check_for_update():
    try:
        if os.path.exists(LAST_CHECK_PATH):
            with open(LAST_CHECK_PATH, "r") as f:
                data = json.load(f)
                last_check = data.get("last_check", 0)
                now = int(time.time())
                if now - last_check < THROTTLE_HOURS * 3600:
                    return False
        return True
    except Exception as e:
        print(f"[WARN] Could not read last update check timestamp: {e}")
        return True

def record_update_check():
    try:
        with open(LAST_CHECK_PATH, "w") as f:
            json.dump({"last_check": int(time.time())}, f)
    except Exception as e:
        print(f"[WARN] Could not write last update check timestamp: {e}")

def check_for_update():
    if not should_check_for_update():
        return False, None, None
    try:
        release = get_latest_release_info()
        latest_version = release["tag_name"].lstrip("v")
        current_version = get_current_version()
        if current_version is None:
            print("[WARN] Could not determine current version.")
            record_update_check()
            return False, None, None
        if latest_version > current_version:
            record_update_check()
            return True, latest_version, release
        record_update_check()
        return False, latest_version, release
    except Exception as e:
        print(f"[ERROR] Update check failed: {e}")
        record_update_check()
        return False, None, None

def download_latest_asset(release):
    token = get_github_token()
    headers = {"Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"token {token}"
    for asset in release["assets"]:
        if asset["name"] == ASSET_NAME:
            download_url = asset["url"]
            resp = requests.get(download_url, headers=headers, stream=True, verify=True)
            if resp.status_code == 200:
                return resp.content
            else:
                raise RuntimeError(f"Failed to download asset: {resp.status_code} {resp.text}")
    raise RuntimeError(f"Asset '{ASSET_NAME}' not found in release.")

def replace_current_binary(new_binary_bytes):
    current_exe = os.path.realpath(sys.argv[0])
    backup_path = current_exe + ".bak"
    try:
        # Write to a temp file first
        with tempfile.NamedTemporaryFile(delete=False, dir=os.path.dirname(current_exe)) as tmpf:
            tmpf.write(new_binary_bytes)
            tmp_path = tmpf.name
        # Backup current binary
        shutil.copy2(current_exe, backup_path)
        # Replace atomically
        os.replace(tmp_path, current_exe)
        os.chmod(current_exe, 0o755)
        print(f"[INFO] Updated binary written to {current_exe}. Backup at {backup_path}.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to replace binary: {e}")
        return False

def main():
    if '--update' in sys.argv:
        print("Checking for updates...")
        update_available, latest_version, release = check_for_update()
        if update_available:
            print(f"A new version (v{latest_version}) is available. Downloading...")
            try:
                new_bin = download_latest_asset(release)
                if replace_current_binary(new_bin):
                    print("Update complete! Please restart Jackify.")
                else:
                    print("Update failed during binary replacement.")
            except Exception as e:
                print(f"[ERROR] Update failed: {e}")
        else:
            print("You are already running the latest version.")
        sys.exit(0)

# For direct CLI testing
if __name__ == "__main__":
    main() 