def sanitize_game_name(name: str | None) -> str:
    if not name:
        return ""
    return " ".join(name.split())
