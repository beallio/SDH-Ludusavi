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


def test_version_comparison() -> None:
    v_0_2_0 = parse_plugin_version("0.2.0")
    v_0_2_1 = parse_plugin_version("0.2.1")
    v_0_2_1_local = parse_plugin_version("0.2.1+g123")
    v_0_2_1_dev1 = parse_plugin_version("0.2.1-dev.g123")
    v_0_2_1_dev2 = parse_plugin_version("0.2.1-dev.g456")
    v_0_2_2_dev = parse_plugin_version("0.2.2-dev.g123")

    assert v_0_2_0 is not None
    assert v_0_2_1 is not None
    assert v_0_2_1_local is not None
    assert v_0_2_1_dev1 is not None
    assert v_0_2_1_dev2 is not None
    assert v_0_2_2_dev is not None

    # Higher stable is greater
    assert v_0_2_1 > v_0_2_0
    assert v_0_2_1 >= v_0_2_0
    assert v_0_2_0 < v_0_2_1
    assert v_0_2_0 <= v_0_2_1

    # Local builds are stable-equivalent
    assert v_0_2_1 == v_0_2_1_local
    assert not (v_0_2_1 < v_0_2_1_local)
    assert not (v_0_2_1 > v_0_2_1_local)

    # Stable wins over same-base dev
    assert v_0_2_1 > v_0_2_1_dev1
    assert v_0_2_1_local > v_0_2_1_dev1

    # Higher base dev is greater than lower stable
    assert v_0_2_2_dev > v_0_2_1
    assert v_0_2_2_dev > v_0_2_1_local
    assert v_0_2_1 < v_0_2_2_dev

    # Same-base dev builds are equal in version comparison (ordering relies on published_at)
    assert v_0_2_1_dev1 == v_0_2_1_dev2
    assert not (v_0_2_1_dev1 < v_0_2_1_dev2)
    assert not (v_0_2_1_dev1 > v_0_2_1_dev2)
