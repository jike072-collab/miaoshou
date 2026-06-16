"""Small macOS Keychain wrapper; secrets never enter SQLite."""

import subprocess


SERVICE = "MiaoShouWorkbench"


def get_secret(account="image-api-key"):
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def set_secret(value, account="image-api-key"):
    if not value:
        return
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", value],
        check=True, capture_output=True, text=True, timeout=10,
    )

