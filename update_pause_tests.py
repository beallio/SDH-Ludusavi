import re

with open("tests/test_service.py", "r") as f:
    content = f.read()

# Replace: assert service.pause_game_process(100) == {"status": "paused", "pid": 100}
content = re.sub(
    r'assert service\.pause_game_process\(100\) == \{"status": "paused", "pid": 100\}',
    'res = service.pause_game_process(100)\\n    assert res["status"] == "paused"\\n    assert res["pid"] == 100\\n    assert "lease_id" in res',
    content,
)

with open("tests/test_service.py", "w") as f:
    f.write(content)
