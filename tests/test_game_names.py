from sdh_ludusavi.game_names import sanitize_game_name


def test_sanitize_game_name_none():
    assert sanitize_game_name(None) == ""


def test_sanitize_game_name_empty():
    assert sanitize_game_name("") == ""
    assert sanitize_game_name("   ") == ""
    assert sanitize_game_name("\t\n") == ""


def test_sanitize_game_name_whitespace():
    assert sanitize_game_name("  Hades  ") == "Hades"
    assert sanitize_game_name("Hades\t(Test)") == "Hades (Test)"
    assert sanitize_game_name("  Hades \n (Test)  ") == "Hades (Test)"


def test_sanitize_game_name_preserves_case_and_punctuation():
    assert sanitize_game_name("Hades: The Game!") == "Hades: The Game!"
    assert sanitize_game_name("  HADES  ") == "HADES"
