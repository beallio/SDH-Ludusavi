import pytest
from scripts.version_guard import (
    parse_semver,
    highest_stable_version,
    is_base_ahead_of_stable,
    is_version_behind_stable,
)


def test_parse_semver():
    assert parse_semver("0.3.1") == (0, 3, 1)
    assert parse_semver("1.0.0") == (1, 0, 0)

    with pytest.raises(ValueError):
        parse_semver("0.3.1-dev")

    with pytest.raises(ValueError):
        parse_semver("not_a_version")


def test_highest_stable_version():
    assert highest_stable_version(["v0.1.0", "v0.3.2", "v0.2.0"]) == (0, 3, 2)
    assert highest_stable_version(["v0.3.2", "v0.3.3-dev.abc"]) == (0, 3, 2)
    assert highest_stable_version([]) is None
    assert highest_stable_version(["v0.3.3-dev"]) is None
    assert highest_stable_version(["0.3.2"]) == (0, 3, 2)


def test_is_base_ahead_of_stable():
    # Base ahead
    assert is_base_ahead_of_stable("0.3.3", ["v0.3.2"]) is True
    # Base equal
    assert is_base_ahead_of_stable("0.3.2", ["v0.3.2"]) is False
    # Base behind
    assert is_base_ahead_of_stable("0.3.1", ["v0.3.2"]) is False
    # No stable tags
    assert is_base_ahead_of_stable("0.1.0", []) is True
    # Base ahead of mixed
    assert is_base_ahead_of_stable("0.3.3", ["v0.3.2", "v0.3.4-dev"]) is True


def test_is_version_behind_stable():
    # Behind -> True (the drift we guard against)
    assert is_version_behind_stable("0.3.1", ["v0.3.2"]) is True
    # Equal -> not behind (valid: this is the version being/just released)
    assert is_version_behind_stable("0.3.3", ["v0.3.3"]) is False
    # Ahead -> not behind
    assert is_version_behind_stable("0.3.4", ["v0.3.3"]) is False
    # No stable tags -> not behind
    assert is_version_behind_stable("0.1.0", []) is False
    # Pre-release tags ignored when finding the highest stable
    assert is_version_behind_stable("0.3.3", ["v0.3.3", "v0.3.4-dev"]) is False
