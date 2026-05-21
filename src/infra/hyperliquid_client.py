"""Read-only client for Hyperliquid info endpoint."""

from __future__ import annotations

from typing import Any

import requests


class HyperliquidClient:
    def __init__(self, base_url: str = "https://api.hyperliquid.xyz"):
        self.base_url = base_url.rstrip("/")

    def universe(self) -> list[str]:
        data = self._post_info({"type": "meta"})
        return [asset["name"] for asset in data["universe"]]

    def universe_with_volumes(self) -> dict[str, float]:
        meta, asset_contexts = self._post_info({"type": "metaAndAssetCtxs"})
        names = [asset["name"] for asset in meta["universe"]]
        volumes = [float(asset_context["dayNtlVlm"]) for asset_context in asset_contexts]
        return dict(zip(names, volumes, strict=True))

    def _post_info(self, payload: dict[str, Any]) -> Any:
        response = requests.post(f"{self.base_url}/info", json=payload, timeout=20)
        response.raise_for_status()
        return response.json()
