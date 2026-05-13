import logging
import importlib
import pyludusavi


def test_pyludusavi_logs_environment(caplog):
    caplog.set_level(logging.INFO)

    # Reload the module to trigger the load-time logging
    importlib.reload(pyludusavi)

    # Check if os.environ was logged
    # We look for a log message that contains "pyludusavi" and some environment keys
    found = False
    for record in caplog.records:
        if "pyludusavi" in record.message and "PATH" in record.message:
            found = True
            break

    assert found, "Environment variables were not found in logs"
