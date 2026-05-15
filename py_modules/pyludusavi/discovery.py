import shutil
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Union
from ._environment import resolve_environment


class LudusaviNotFoundError(Exception):
    """Raised when the Ludusavi executable or Flatpak could not be found."""

    pass


def find_ludusavi(
    explicit_path: Optional[Union[str, Path]] = None,
    explicit_flatpak_id: Optional[str] = None,
    flatpak_id: str = "com.github.mtkennerly.ludusavi",
    env: Optional[Mapping[str, str]] = None,
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
    resolved_env = resolve_environment(env)
    path_env = None if resolved_env is None else resolved_env.get("PATH")

    # 1. Explicit path
    if explicit_path:
        str_path = str(explicit_path)
        if _verify([str_path], env=resolved_env):
            return [str_path]
        raise LudusaviNotFoundError(
            f"Explicitly provided Ludusavi path not found or invalid: {explicit_path}"
        )

    # 2. Explicit Flatpak ID
    if explicit_flatpak_id:
        prefix = ["flatpak", "run", explicit_flatpak_id]
        if _which("flatpak", path_env) and _verify(prefix, env=resolved_env):
            return prefix
        raise LudusaviNotFoundError(
            f"Explicitly provided Ludusavi Flatpak ID not found or invalid: {explicit_flatpak_id}"
        )

    # 3. PATH lookup
    path_lookup = _which("ludusavi", path_env)
    if path_lookup:
        if _verify([path_lookup], env=resolved_env):
            return [path_lookup]

    # 4. Flatpak ID lookup
    flatpak_lookup = _which("flatpak", path_env)
    if flatpak_lookup:
        prefix = ["flatpak", "run", flatpak_id]
        if _verify(prefix, env=resolved_env):
            return prefix

    raise LudusaviNotFoundError("Ludusavi could not be found via PATH or Flatpak.")


def _which(command: str, path: Optional[str]) -> Optional[str]:
    if path is None:
        return shutil.which(command)
    return shutil.which(command, path=path)


def _verify(prefix: list[str], env: Optional[dict[str, str]] = None) -> bool:
    """Verify that the command prefix correctly calls Ludusavi."""
    try:
        if env is None:
            result = subprocess.run(
                prefix + ["--version"], capture_output=True, text=True, check=False
            )
        else:
            result = subprocess.run(
                prefix + ["--version"],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
        return result.returncode == 0
    except (FileNotFoundError, PermissionError):
        return False
