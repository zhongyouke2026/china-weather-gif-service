from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .config import Settings


LOGGER = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SupabaseStore:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for uploads"
            )
        self.settings = settings
        self.base_url = settings.supabase_url.rstrip("/")
        self.key = settings.supabase_service_role_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "User-Agent": "china-weather-gif/1.0",
            }
        )

    def claim(self, gfs_run: str, trigger_source: str = "batch") -> bool:
        response = self.session.post(
            f"{self.base_url}/rest/v1/rpc/claim_weather_generation",
            json={
                "p_asset_key": self.settings.asset_key,
                "p_gfs_run": gfs_run,
                "p_trigger_source": trigger_source,
            },
            timeout=30,
        )
        response.raise_for_status()
        return bool(response.json())

    def upload_file(
        self,
        source: Path,
        storage_path: str,
        content_type: str,
        cache_seconds: int = 31_536_000,
    ) -> None:
        encoded = quote(storage_path, safe="/")
        bucket = quote(self.settings.storage_bucket, safe="")
        url = f"{self.base_url}/storage/v1/object/{bucket}/{encoded}"
        payload = source.read_bytes()
        response = self.session.post(
            url,
            data=payload,
            headers={
                "Content-Type": content_type,
                "cache-control": f"max-age={cache_seconds}",
                "x-upsert": "false",
            },
            timeout=(15, 180),
        )
        if response.status_code in {400, 409} and "exist" in response.text.lower():
            existing = self.download(storage_path)
            if hashlib.sha256(existing).hexdigest() == hashlib.sha256(payload).hexdigest():
                LOGGER.info("Versioned object already exists with the same checksum: %s", storage_path)
                return
            raise RuntimeError(
                f"Storage path already exists with different content: {storage_path}"
            )
        response.raise_for_status()

    def download(self, storage_path: str) -> bytes:
        encoded = quote(storage_path, safe="/")
        bucket = quote(self.settings.storage_bucket, safe="")
        response = self.session.get(
            f"{self.base_url}/storage/v1/object/authenticated/{bucket}/{encoded}",
            timeout=(15, 180),
        )
        response.raise_for_status()
        return response.content

    def mark_ready(
        self,
        gfs_run: str,
        *,
        storage_path: str,
        sha256: str,
        byte_size: int,
        frame_count: int,
        forecast_start: str,
        forecast_end: str,
        generated_at: str,
        metadata: dict[str, Any],
    ) -> None:
        self._patch(
            gfs_run,
            {
                "status": "ready",
                "storage_bucket": self.settings.storage_bucket,
                "storage_path": storage_path,
                "content_type": "image/gif",
                "sha256": sha256,
                "byte_size": byte_size,
                "frame_count": frame_count,
                "forecast_start": forecast_start,
                "forecast_end": forecast_end,
                "generated_at": generated_at,
                "finished_at": generated_at,
                "error_message": None,
                "metadata": metadata,
            },
        )

    def mark_failed(self, gfs_run: str, error: str) -> None:
        try:
            self._patch(
                gfs_run,
                {
                    "status": "failed",
                    "finished_at": "now()",
                    "error_message": error[:4_000],
                },
            )
        except Exception as exc:
            LOGGER.error("Unable to record failed status: %s", exc)

    def _patch(self, gfs_run: str, payload: dict[str, Any]) -> None:
        # PostgREST expects actual timestamps, not SQL expressions.
        if payload.get("finished_at") == "now()":
            from datetime import datetime, timezone

            payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        response = self.session.patch(
            f"{self.base_url}/rest/v1/weather_assets",
            params={
                "asset_key": f"eq.{self.settings.asset_key}",
                "gfs_run": f"eq.{gfs_run}",
            },
            headers={"Content-Type": "application/json", "Prefer": "return=representation"},
            data=json.dumps(payload),
            timeout=30,
        )
        response.raise_for_status()
        updated = response.json()
        if len(updated) != 1:
            raise RuntimeError(
                f"Expected one weather_assets row for {gfs_run}, updated {len(updated)}"
            )

