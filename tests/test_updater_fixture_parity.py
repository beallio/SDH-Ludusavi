from __future__ import annotations

import datetime
import json
from pathlib import Path
import threading
from typing import Any

from sdh_ludusavi.updater import PluginUpdater
from sdh_ludusavi.updater_models import JsonResponse


FIXTURE_PATH = Path(__file__).parent / "contract" / "fixtures" / "github" / "recorded.json"


class RecordedGitHub:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.manifest_urls: list[str] = []

    def list_releases(self) -> JsonResponse:
        return JsonResponse(200, {}, self.data["releases"])

    def get_release(self, tag: str) -> JsonResponse:
        release = self.data.get("revalidation", {}).get("release", {})
        if release.get("tag_name") != tag:
            return JsonResponse(404, {}, {})
        return JsonResponse(200, {}, release)

    def get_manifest(self, url: str) -> JsonResponse:
        self.manifest_urls.append(url)
        manifest = self.data.get("manifests", {}).get(url)
        if manifest is None:
            manifest = self.data.get("revalidation", {}).get("manifest", {})
        return JsonResponse(200, {}, manifest)


def _updater(client: RecordedGitHub) -> PluginUpdater:
    return PluginUpdater(
        state_lock=threading.RLock(),
        save_callback=lambda: None,
        log_callback=lambda _level, _message: None,
        release_client=client,
        version_resolver=lambda: "0.5.0",
        now=lambda: datetime.datetime(2026, 10, 26, tzinfo=datetime.timezone.utc),
        monotonic=lambda: 0.0,
    )


def test_recorded_github_release_decisions_match_expected_results() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for case in fixture["checks"]:
        client = RecordedGitHub(case)
        updater = _updater(client)
        updater.adopt_persisted_settings({"update_channel": case["channel"]})
        result = updater.check_for_update(case["installed_version"], force=True)

        assert result["status"] == case["expected"]["status"], case["name"]
        if "candidate" in case["expected"]:
            assert result["candidate"] == case["expected"]["candidate"], case["name"]
        if "expected_manifest_attempts" in case:
            assert len(client.manifest_urls) == case["expected_manifest_attempts"], case["name"]

    client = RecordedGitHub(fixture)
    updater = _updater(client)
    revalidation = fixture["revalidation"]
    assert updater.revalidate(revalidation["candidate"]) == revalidation["expected"]
    mismatch = dict(revalidation["candidate"], sha256="f" * 64)
    rejected = updater.revalidate(mismatch)
    assert rejected["status"] == "failed"
    assert rejected["message"] == "SHA-256 mismatch during revalidation"
