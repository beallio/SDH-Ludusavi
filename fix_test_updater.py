import re
from pathlib import Path

content = Path("tests/test_updater.py").read_text()

# Remove all monkeypatch of GitHubReleaseClient
content = re.sub(
    r'^\s*monkeypatch\.setattr\(updater_mod, "GitHubReleaseClient", .*?MockClient\w*\(\)\)\s*\n',
    "",
    content,
    flags=re.MULTILINE,
)

# Fix line 172 which uses MockClient() instead of MockClient2() for the bad manifest case
# I will just replace `validate_release_candidate(release, MockClient())` around line 172 with MockClient2()
# Wait, the best way is to find MockClient2 usage.
content = content.replace(
    "class MockClient2:\n        def get_manifest(self, url):\n            return JsonResponse(status=200, headers={}, body=bad_manifest)",
    "class MockClient2:\n        def get_manifest(self, url):\n            return JsonResponse(status=200, headers={}, body=bad_manifest)\n\n    assert validate_release_candidate(release, MockClient2()) is None",
)

# Now I'll delete the wrong assert on line 172
content = content.replace(
    "\n    assert validate_release_candidate(release, MockClient()) is None\n", "\n"
)

Path("tests/test_updater.py").write_text(content)
print("Updated tests/test_updater.py")
