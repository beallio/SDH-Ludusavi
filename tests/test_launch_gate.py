"""TDD naming sentinel for the launch-gate module.

The detailed filesystem and transition contract lives in test_launch_gate_scope.py.
"""

from sdh_ludusavi.launch_gate import ScopeTransitionResult


def test_scope_transition_result_defaults_to_an_extant_scope() -> None:
    result = ScopeTransitionResult(success=True)

    assert result.reason == ""
    assert result.disappeared is False
