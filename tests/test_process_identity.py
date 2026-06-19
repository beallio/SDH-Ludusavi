from sdh_ludusavi import service


def test_identity_resolves_user_from_uid_not_env(monkeypatch):
    class _Pw:
        pw_name = "deck"

    monkeypatch.setattr(service.os, "getuid", lambda: 1000)
    monkeypatch.setattr(service.os, "geteuid", lambda: 1000)
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("LOGNAME", "root")

    import pwd

    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _Pw())

    result = service._resolve_process_identity()
    assert result == "uid=1000, euid=1000, user=deck"
    assert "root" not in result


def test_identity_falls_back_on_keyerror(monkeypatch):
    monkeypatch.setattr(service.os, "getuid", lambda: 1000)
    monkeypatch.setattr(service.os, "geteuid", lambda: 1000)

    import pwd

    def raise_keyerror(uid):
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", raise_keyerror)

    import getpass

    monkeypatch.setattr(getpass, "getuser", lambda: "fallback_user")

    result = service._resolve_process_identity()
    assert result == "uid=1000, euid=1000, user=fallback_user"
    assert "user=fallback_user" in result
