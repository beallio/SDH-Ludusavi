import os
import logging
from .main import Ludusavi
from .core import LudusaviResponse, LudusaviError, LudusaviExecutionError, LudusaviContractError
from .discovery import (
    find_ludusavi,
    find_ludusavi_binary,
    find_ludusavi_config_dir,
    LudusaviNotFoundError,
)
from ._version import __version__

logger = logging.getLogger(__name__)

# Log relevant environment variables at DEBUG level for troubleshooting.
_relevant_keys = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LD_LIBRARY_PATH",
    "XDG_DATA_DIRS",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
}
_filtered_env = {
    k: v
    for k, v in os.environ.items()
    if k in _relevant_keys or k.startswith(("DECKY_", "FLATPAK_"))
}
logger.debug(f"pyludusavi version {__version__} loaded with filtered environment: {_filtered_env}")

__all__ = [
    "Ludusavi",
    "LudusaviResponse",
    "LudusaviError",
    "LudusaviExecutionError",
    "LudusaviContractError",
    "find_ludusavi",
    "find_ludusavi_binary",
    "find_ludusavi_config_dir",
    "LudusaviNotFoundError",
    "__version__",
]
