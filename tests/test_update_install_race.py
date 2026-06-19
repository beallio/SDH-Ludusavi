"""Regression tests for the post-update reconcile race.

Decky's install reload storm can run two backend instances against the same
persisted state. An instance constructed before another instance promoted the
pending install holds a stale in-memory snapshot; its reconcile must re-read
the persisted state under the inter-process lock instead of acting on that
snapshot, so the pending record is promoted exactly once and is never
resurrected by a later save from the stale instance.
"""

from __future__ import annotations

import json
from sdh_ludusavi.persistence import JsonSettingsStore
from pathlib import Path
from typing import Any

from sdh_ludusavi.service import SDHLudusaviService

PENDING_VERSION = "9.9.9"
PENDING_TAG = "v9.9.9"


def _make_service(state_path: Path) -> SDHLudusaviService:
    return SDHLudusaviService(
        settings_store=JsonSettingsStore(state_path.with_name("settings.json")),
        cache_path=state_path.with_name("cache.json"),
    )


def _record_pending(service: SDHLudusaviService) -> None:
    service.record_update_install_requested(
        {
            "version": PENDING_VERSION,
            "tag": PENDING_TAG,
            "channel": "stable",
            "published_at": "2026-06-11T00:00:00+00:00",
            "updateTraceId": "tr-test",
        }
    )


def _promotion_log_count(service: SDHLudusaviService) -> int:
    return sum(
        1
        for entry in service.get_recent_logs()
        if "Pending update promoted" in str(entry.get("message", ""))
    )


def _persisted_update_cache(state_path: Path) -> dict[str, Any]:
    data = json.loads(state_path.with_name("cache.json").read_text(encoding="utf-8"))
    cache = data.get("update_check_cache", {})
    return cache if isinstance(cache, dict) else {}


def test_stale_instance_does_not_double_promote_pending_install(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"

    service_a = _make_service(state_path)
    _record_pending(service_a)

    # Second instance constructed while the pending record is on disk: its
    # in-memory snapshot still holds the pending install after A promotes it.
    service_b = _make_service(state_path)

    service_a.reconcile_pending_update_install(PENDING_VERSION)
    service_b.reconcile_pending_update_install(PENDING_VERSION)

    assert _promotion_log_count(service_a) == 1
    assert _promotion_log_count(service_b) == 0

    context_b = service_b.get_update_check_context()
    assert context_b["pending_update_install"] is None
    assert context_b["installed_release_tag"] == PENDING_TAG


def test_stale_instance_save_does_not_resurrect_promoted_install(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"

    service_a = _make_service(state_path)
    _record_pending(service_a)
    service_b = _make_service(state_path)

    service_a.reconcile_pending_update_install(PENDING_VERSION)
    service_b.reconcile_pending_update_install(PENDING_VERSION)

    # Any later state save from the stale instance must not write back the
    # already-promoted pending record or the pre-promotion release tag.
    service_b.set_selected_game("Celeste")

    persisted = _persisted_update_cache(state_path)
    assert "pending_update_install" not in persisted
    assert persisted.get("installed_release_tag") == PENDING_TAG


def test_reconcile_with_no_pending_anywhere_logs_no_promotion(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    service = _make_service(state_path)

    service.reconcile_pending_update_install(PENDING_VERSION)

    assert _promotion_log_count(service) == 0
    assert any(
        "No pending update found" in str(entry.get("message", ""))
        for entry in service.get_recent_logs()
    )
