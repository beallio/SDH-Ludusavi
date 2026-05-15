try:
    from importlib.metadata import version, PackageNotFoundError

    __version__ = version("pyludusavi")
except PackageNotFoundError:
    __version__ = "unknown"
