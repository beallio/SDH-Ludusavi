import os
from typing import Mapping, Optional


def resolve_environment(env: Optional[Mapping[str, str]]) -> Optional[dict[str, str]]:
    """Merge environment overrides onto the current process environment."""
    if env is None:
        return None
    resolved = dict(os.environ)
    resolved.update(env)
    return resolved
