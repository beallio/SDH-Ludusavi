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
logger.info(f"pyludusavi version {__version__} loaded with environment: {dict(os.environ)}")

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
