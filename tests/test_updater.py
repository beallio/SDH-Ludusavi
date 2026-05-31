from __future__ import annotations

from sdh_ludusavi.updater import parse_plugin_version


def test_parse_plugin_version_stable() -> None:
    parsed = parse_plugin_version("0.2.1")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert not parsed.is_dev
    assert parsed.dev_suffix is None
    assert parsed.build_metadata is None


def test_parse_plugin_version_dev_gsha() -> None:
    parsed = parse_plugin_version("0.2.1-dev.g55d87c")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert parsed.is_dev
    assert parsed.dev_suffix == "g55d87c"
    assert parsed.build_metadata is None


def test_parse_plugin_version_dev_legacy() -> None:
    parsed = parse_plugin_version("0.2.1-dev.55d87c")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert parsed.is_dev
    assert parsed.dev_suffix == "55d87c"
    assert parsed.build_metadata is None


def test_parse_plugin_version_local_build() -> None:
    parsed = parse_plugin_version("0.2.1+g55d87c")
    assert parsed is not None
    assert parsed.major == 0
    assert parsed.minor == 2
    assert parsed.patch == 1
    assert not parsed.is_dev
    assert parsed.dev_suffix is None
    assert parsed.build_metadata == "g55d87c"


def test_parse_plugin_version_invalid() -> None:
    assert parse_plugin_version("invalid") is None
    assert parse_plugin_version("1.2") is None
    assert parse_plugin_version("1.2.3.4") is None
