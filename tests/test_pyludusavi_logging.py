import logging
import importlib
import pyludusavi


def test_pyludusavi_logs_environment(caplog):
    caplog.set_level(logging.DEBUG)

    # Reload the module to trigger the load-time logging
    importlib.reload(pyludusavi)

    # Check if os.environ (filtered) was logged at DEBUG level
    found = False
    for record in caplog.records:
        if (
            record.levelno == logging.DEBUG
            and "pyludusavi" in record.message
            and "PATH" in record.message
        ):
            found = True
            break

    assert found, "Filtered environment variables were not found in logs at DEBUG level"
