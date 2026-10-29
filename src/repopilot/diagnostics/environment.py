import importlib.metadata
import os
import shutil
import subprocess
import sys


def inspect_environment() -> dict:
    docker = shutil.which("docker")
    podman = shutil.which("podman")
    wsl = shutil.which("wsl")
    wsl_state = "not_available"
    if wsl:
        try:
            result = subprocess.run([wsl, "--status"], capture_output=True, timeout=5)
            wsl_state = "available" if result.returncode == 0 else "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            wsl_state = "probe_failed"
    engine = None
    try:
        engine = importlib.metadata.version("mini-swe-agent")
    except importlib.metadata.PackageNotFoundError:
        pass
    return {
        "python": sys.version.split()[0],
        "git_available": bool(shutil.which("git")),
        "container_command_available": bool(docker or podman),
        "wsl": wsl_state,
        "deepseek_key_configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        "engine_version": engine,
        "read_only_investigation_available": bool(shutil.which("git")),
        "target_execution_enabled": False,
        "notes": [
            "Provider credentials are not printed or tested by doctor.",
            "Container command presence does not prove a working sandbox.",
            "This version never executes target repository commands.",
        ],
    }
