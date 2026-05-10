try:
    from importlib.metadata import version, PackageNotFoundError

    __version__ = version("SDH-ludusavi")
except PackageNotFoundError:
    __version__ = "unknown"
