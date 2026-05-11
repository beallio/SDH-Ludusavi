import shutil
import subprocess
from pathlib import Path
from typing import Optional

FLATPAK_EXECUTABLES = (
    "/usr/bin/flatpak",
    "/bin/flatpak",
    "/usr/local/bin/flatpak",
)
ENV_EXECUTABLE = "/usr/bin/env"
VERIFY_TIMEOUT_SECONDS = 5


class LudusaviNotFoundError(Exception):
    """Raised when the Ludusavi executable or Flatpak could not be found."""

    pass


def find_ludusavi(
    explicit_path: Optional[str] = None,
    explicit_flatpak_id: Optional[str] = None,
    flatpak_id: str = "com.github.mtkennerly.ludusavi",
    flatpak_user_home: Optional[str] = None,
) -> list[str]:
    """
    Find the Ludusavi executable or Flatpak.

    Precedence:
    1. Explicit path.
    2. Explicit Flatpak ID.
    3. PATH lookup.
    4. Default Flatpak ID lookup.

    Returns:
        list[str]: The command prefix to use for calling Ludusavi.

    Raises:
        LudusaviNotFoundError: If Ludusavi could not be found or verified.
    """
    # 1. Explicit path
    if explicit_path:
        if _verify([explicit_path]):
            return [explicit_path]
        raise LudusaviNotFoundError(
            f"Explicitly provided Ludusavi path not found or invalid: {explicit_path}"
        )

    # 2. Explicit Flatpak ID
    if explicit_flatpak_id:
        for prefix in _flatpak_prefixes(explicit_flatpak_id, flatpak_user_home):
            if _verify(prefix):
                return prefix
        raise LudusaviNotFoundError(
            f"Explicitly provided Ludusavi Flatpak ID not found or invalid: {explicit_flatpak_id}"
        )

    # 3. PATH lookup
    path_lookup = shutil.which("ludusavi")
    if path_lookup:
        if _verify([path_lookup]):
            return [path_lookup]

    # 4. Flatpak ID lookup
    for prefix in _flatpak_prefixes(flatpak_id, flatpak_user_home):
        if _verify(prefix):
            return prefix

    raise LudusaviNotFoundError("Ludusavi could not be found via PATH or Flatpak.")


def _flatpak_commands() -> list[str]:
    commands: list[str] = []
    path_lookup = shutil.which("flatpak")
    if path_lookup:
        commands.append(path_lookup)
    for command in FLATPAK_EXECUTABLES:
        if command not in commands:
            commands.append(command)
    return commands


def _flatpak_prefixes(flatpak_id: str, flatpak_user_home: Optional[str]) -> list[list[str]]:
    prefixes: list[list[str]] = []
    for flatpak in _flatpak_commands():
        if flatpak_user_home:
            prefixes.append(
                _flatpak_user_env(flatpak_user_home) + [flatpak, "run", "--user", flatpak_id]
            )
        prefixes.append([flatpak, "run", flatpak_id])
    return prefixes


def _flatpak_user_env(flatpak_user_home: str) -> list[str]:
    user_home = Path(flatpak_user_home).expanduser()
    data_home = user_home / ".local" / "share"
    return [
        ENV_EXECUTABLE,
        f"HOME={user_home}",
        f"XDG_DATA_HOME={data_home}",
        f"FLATPAK_USER_DIR={data_home / 'flatpak'}",
    ]


def _verify(prefix: list[str]) -> bool:
    """Verify that the command prefix correctly calls Ludusavi."""
    try:
        result = subprocess.run(
            prefix + ["--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return False
