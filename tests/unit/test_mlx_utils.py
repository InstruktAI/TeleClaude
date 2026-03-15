"""Characterization tests for teleclaude.mlx_utils."""

from __future__ import annotations

import pytest

from teleclaude import mlx_utils

pytestmark = pytest.mark.unit


class TestPathHelpers:
    @pytest.mark.parametrize("value", ["./model", "/tmp/model", "~/model", "C:\\model"])
    def test_is_local_path_detects_filesystem_paths(self, value: str) -> None:
        assert mlx_utils.is_local_path(value) is True

    def test_normalize_model_ref_expands_local_paths_only(self) -> None:
        assert mlx_utils.normalize_model_ref("~/demo-model").endswith("/demo-model")
        assert mlx_utils.normalize_model_ref("mlx-community/model") == "mlx-community/model"


class TestCacheResolution:
    def test_probe_local_caches_returns_none_for_non_repo_id(self) -> None:
        assert mlx_utils.probe_local_caches("not-a-repo-id") is None

    def test_resolve_model_ref_prefers_existing_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mlx_utils, "probe_local_caches", lambda repo_id: "/cache/model")

        assert mlx_utils.resolve_model_ref("mlx-community/model") == "/cache/model"
