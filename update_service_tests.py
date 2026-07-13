import re

with open("tests/test_service.py", "r") as f:
    content = f.read()

# Replace: service._watchdog._paused_pids[123] = (_ProcessIdentity(12345, 1000), time.time() - 20.0)
# with: service._watchdog._paused_pids[123] = _PauseLease(identity=_ProcessIdentity(12345, 1000), paused_at=time.monotonic() - 20.0, lease_id="test", lease_deadline=time.monotonic() - 10.0)

# Replace: service._watchdog._paused_pids[123] = (_ProcessIdentity(12345, 1000), time.time() - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1))
# with: service._watchdog._paused_pids[123] = _PauseLease(identity=_ProcessIdentity(12345, 1000), paused_at=time.monotonic() - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1), lease_id="test", lease_deadline=time.monotonic() + 30.0)

content = content.replace("time.time()", "time.monotonic()")


# I will just write a regex substitution to update these lines.
def repl(m):
    return 'service._watchdog._paused_pids[123] = _PauseLease(identity=_ProcessIdentity(12345, 1000), paused_at=time.monotonic() - 20.0, lease_id="test", lease_deadline=time.monotonic() - 10.0)'


content = re.sub(
    r"service\._watchdog\._paused_pids\[123\] = \(_ProcessIdentity\(12345, 1000\), time\.monotonic\(\) - 20\.0\)",
    'from sdh_ludusavi.watchdog import _PauseLease\\n        service._watchdog._paused_pids[123] = _PauseLease(identity=_ProcessIdentity(12345, 1000), paused_at=time.monotonic() - 20.0, lease_id="test", lease_deadline=time.monotonic() - 10.0)',
    content,
)


def repl2(m):
    return 'from sdh_ludusavi.watchdog import _PauseLease\\n        service._watchdog._paused_pids[123] = _PauseLease(identity=_ProcessIdentity(12345, 1000), paused_at=time.monotonic() - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1), lease_id="test", lease_deadline=time.monotonic() + 30.0)'


content = re.sub(
    r"service\._watchdog\._paused_pids\[123\] = \(\\n\s*_ProcessIdentity\(12345, 1000\),\\n\s*time\.monotonic\(\) - \(WATCHDOG_ABSOLUTE_RESUME_SECONDS \+ 1\),\\n\s*\)",
    'from sdh_ludusavi.watchdog import _PauseLease\\n        service._watchdog._paused_pids[123] = _PauseLease(identity=_ProcessIdentity(12345, 1000), paused_at=time.monotonic() - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1), lease_id="test", lease_deadline=time.monotonic() + 30.0)',
    content,
)


with open("tests/test_service.py", "w") as f:
    f.write(content)
