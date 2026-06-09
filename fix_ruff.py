import re
from pathlib import Path

# Fix tests/test_updater.py
p1 = Path("tests/test_updater.py")
c1 = p1.read_text()
c1 = c1.replace("lambda l, m: None", "lambda lvl, msg: None")
p1.write_text(c1)

# Fix tests/test_updater_service.py
p2 = Path("tests/test_updater_service.py")
c2 = p2.read_text()
c2 = c2.replace(
    'if self._fetch: return self._fetch("releases")',
    'if self._fetch:\n            return self._fetch("releases")',
)
c2 = c2.replace(
    "if self._fetch: return self._fetch(tag)",
    "if self._fetch:\n            return self._fetch(tag)",
)
c2 = c2.replace(
    "if self._fetch: return self._fetch(url)",
    "if self._fetch:\n            return self._fetch(url)",
)
c2 = c2.replace(
    'if "manifest" in url: return JsonResponse(status=200, headers={}, body=manifest)',
    'if "manifest" in url:\n            return JsonResponse(status=200, headers={}, body=manifest)',
)
c2 = c2.replace(
    'if url == "releases": return JsonResponse(status=200, headers={}, body=releases)',
    'if url == "releases":\n            return JsonResponse(status=200, headers={}, body=releases)',
)

c2 = re.sub(
    r"now = lambda: datetime\.datetime\.now\(datetime\.timezone\.utc\)",
    r"""def _now():\n            return datetime.datetime.now(datetime.timezone.utc)\n        now = _now""",
    c2,
)

c2 = re.sub(
    r"log_cb = lambda l, m: None",
    r"""def _log(lvl, msg):\n            pass\n        log_cb = _log""",
    c2,
)

c2 = re.sub(
    r"save_cb = lambda: None", r"""def _save():\n            pass\n        save_cb = _save""", c2
)

p2.write_text(c2)
print("Fixed ruff errors")
