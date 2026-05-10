import shutil
import subprocess
from typing import Optional


class LudusaviNotFoundError(Exception):
    """Raised when the Ludusavi executable or Flatpak could not be found."""

    pass


def find_ludusavi(
    explicit_path: Optional[str] = None,
    explicit_flatpak_id: Optional[str] = None,
    flatpak_id: str = "com.github.mtkennerly.ludusavi",
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
        prefix = ["flatpak", "run", explicit_flatpak_id]
        if shutil.which("flatpak") and _verify(prefix):
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
    flatpak_lookup = shutil.which("flatpak")
    if flatpak_lookup:
        prefix = ["flatpak", "run", flatpak_id]
        if _verify(prefix):
            return prefix

    raise LudusaviNotFoundError("Ludusavi could not be found via PATH or Flatpak.")


def _verify(prefix: list[str]) -> bool:
    """Verify that the command prefix correctly calls Ludusavi."""
    try:
        result = subprocess.run(prefix + ["--version"], capture_output=True, text=True, check=False)
        return result.returncode == 0
    except (FileNotFoundError, PermissionError):
        return False
