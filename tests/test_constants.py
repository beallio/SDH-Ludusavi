from __future__ import annotations

import ast
import inspect

import pytest

import sdh_ludusavi.constants as constants
from sdh_ludusavi.constants import (
    DEFAULT_NOTIFICATION_SETTINGS,
    LUDUSAVI_OPERATION_TIMEOUT_SECONDS,
    LUDUSAVI_PREVIEW_TIMEOUT_SECONDS,
    MAX_INSTALLED_APP_IDS_BYTES,
    SETTINGS_KEYS,
    WATCHDOG_ABSOLUTE_RESUME_SECONDS,
)


def test_constants_defined() -> None:
    assert DEFAULT_NOTIFICATION_SETTINGS["enabled"] is True
    assert DEFAULT_NOTIFICATION_SETTINGS["update_available"] is True
    assert "auto_sync_enabled" in SETTINGS_KEYS
    assert MAX_INSTALLED_APP_IDS_BYTES == 16384


@pytest.mark.xfail(
    strict=True,
    reason="RED: Task 1 pins the requested timeout policy before Task 2 applies it.",
)
def test_ludusavi_timeouts_are_capped_at_three_minutes() -> None:
    assert LUDUSAVI_OPERATION_TIMEOUT_SECONDS == 180.0
    assert LUDUSAVI_PREVIEW_TIMEOUT_SECONDS == 180.0


@pytest.mark.xfail(
    strict=True,
    reason="RED: Task 1 pins the requested watchdog derivation before Task 2 applies it.",
)
def test_watchdog_emergency_ceiling_is_derived_from_the_longest_ludusavi_timeout() -> None:
    assert WATCHDOG_ABSOLUTE_RESUME_SECONDS == 240.0

    module = ast.parse(inspect.getsource(constants))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "WATCHDOG_ABSOLUTE_RESUME_SECONDS"
            for target in node.targets
        )
    )

    assert isinstance(assignment.value, ast.BinOp)
    assert isinstance(assignment.value.left, ast.Call)
    assert isinstance(assignment.value.left.func, ast.Name)
    assert assignment.value.left.func.id == "max"
    assert [
        argument.id for argument in assignment.value.left.args if isinstance(argument, ast.Name)
    ] == [
        "LUDUSAVI_OPERATION_TIMEOUT_SECONDS",
        "LUDUSAVI_PREVIEW_TIMEOUT_SECONDS",
    ]
    assert isinstance(assignment.value.op, ast.Add)
    assert isinstance(assignment.value.right, ast.Constant)
    assert assignment.value.right.value == 60.0
