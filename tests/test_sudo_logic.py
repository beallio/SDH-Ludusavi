from unittest.mock import patch
from pyludusavi.discovery import _should_sudo


def test_should_sudo_logic():
    # If no target user is provided, should_sudo should be False
    assert _should_sudo(None) is False
    assert _should_sudo("") is False

    # If target user matches current user, should_sudo should be False
    with patch("getpass.getuser", return_value="deck"):
        assert _should_sudo("deck") is False
        assert _should_sudo("root") is True

    # If target user differs from current user, should_sudo should be True
    with patch("getpass.getuser", return_value="root"):
        assert _should_sudo("deck") is True
        assert _should_sudo("root") is False

    # Test exception fallback (should return True to be safe)
    with patch("getpass.getuser", side_effect=Exception("no user")):
        assert _should_sudo("deck") is True
