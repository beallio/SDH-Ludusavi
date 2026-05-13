from unittest.mock import patch, MagicMock
from pyludusavi.discovery import _should_sudo


def test_should_sudo_logic():
    # If no target user is provided, should_sudo should be False
    assert _should_sudo(None) is False
    assert _should_sudo("") is False

    # Mock pwd.getpwnam to return specific UIDs
    mock_deck = MagicMock()
    mock_deck.pw_uid = 1000
    mock_root = MagicMock()
    mock_root.pw_uid = 0

    def side_effect(name):
        if name == "deck":
            return mock_deck
        if name == "root":
            return mock_root
        raise KeyError(name)

    with patch("os.getuid", return_value=1000), patch("pwd.getpwnam", side_effect=side_effect):
        assert _should_sudo("deck") is False
        assert _should_sudo("root") is True

    with patch("os.getuid", return_value=0), patch("pwd.getpwnam", side_effect=side_effect):
        assert _should_sudo("deck") is True
        assert _should_sudo("root") is False

    # Test exception fallback (should return True to be safe)
    with (
        patch("os.getuid", return_value=1000),
        patch("pwd.getpwnam", side_effect=KeyError("no user")),
    ):
        assert _should_sudo("deck") is True
