"""Optional persistent storage for the Jovi Quality Center.

The portal can still run with its repository-local ``data_store`` directory.
When Supabase secrets are configured, this module makes Supabase Storage the
durable copy of that directory. This is intentionally file-based so existing
SMT, Assembly, OQC/FQC, and Smart Report logic can retain their tested local
SQLite and Excel readers while avoiding Streamlit Community Cloud's ephemeral
filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st

try:  # Kept optional so local development works before cloud setup is complete.
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - exercised by Streamlit after requirements install.
    Client = Any  # type: ignore[misc,assignment]
    create_client = None


DEFAULT_BUCKET = "jovi-quality-data"
DATABASE_OBJECT = "state/jovi_quality.db"


def _setting(name: str, default: str = "") -> str:
    """Read a Supabase setting without requiring a local secrets.toml file."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default)).strip()


def supabase_config() -> dict[str, str]:
    return {
        "url": _setting("SUPABASE_URL").rstrip("/"),
        "key": _setting("SUPABASE_SECRET_KEY"),
        "bucket": _setting("SUPABASE_BUCKET", DEFAULT_BUCKET),
    }


def supabase_is_configured() -> bool:
    config = supabase_config()
    return bool(config["url"] and config["key"])


@st.cache_resource(show_spinner=False)
def _client(url: str, key: str) -> Client:
    if create_client is None:
        raise RuntimeError("Supabase support is not installed. Add the 'supabase' package and restart the app.")
    return create_client(url, key)


def _get_client() -> tuple[Client, dict[str, str]]:
    config = supabase_config()
    if not config["url"] or not config["key"]:
        raise RuntimeError("Supabase is not configured. Add SUPABASE_URL and SUPABASE_SECRET_KEY to Streamlit Secrets.")
    try:
        return _client(config["url"], config["key"]), config
    except Exception as exc:
        raise RuntimeError("The portal could not connect to Supabase. Check the Streamlit Secrets values.") from exc


def _ensure_bucket(client: Client, bucket: str) -> None:
    """Create the private bucket once when the server has a server-side secret key."""
    try:
        existing = client.storage.list_buckets()
        existing_ids = {str(item.get("id", "")) for item in existing if isinstance(item, dict)}
    except Exception as exc:
        raise RuntimeError("Supabase Storage could not be reached.") from exc
    if bucket in existing_ids:
        return
    try:
        client.storage.create_bucket(bucket, options={"public": False})
    except Exception as exc:
        raise RuntimeError(
            f"The private Supabase bucket '{bucket}' could not be created. "
            "Confirm that SUPABASE_SECRET_KEY is a server-side secret key."
        ) from exc


def _storage() -> tuple[Any, dict[str, str]]:
    client, config = _get_client()
    _ensure_bucket(client, config["bucket"])
    return client.storage.from_(config["bucket"]), config


def _clean_object_path(path: str) -> str:
    clean = str(path).replace("\\", "/").strip("/")
    if not clean or any(part in {"", ".", ".."} for part in clean.split("/")):
        raise ValueError("Invalid Supabase object path.")
    return clean


def _safe_local_target(directory: Path, name: str) -> Path:
    if Path(name).name != name:
        raise ValueError("Invalid remote file name.")
    target = directory / name
    if target.parent.resolve() != directory.resolve():
        raise ValueError("Invalid local target path.")
    return target


def _list_objects(prefix: str) -> list[dict]:
    store, _ = _storage()
    try:
        rows = store.list(_clean_object_path(prefix), {"limit": 1000, "offset": 0})
    except Exception as exc:
        raise RuntimeError("Supabase Storage could not list the portal data files.") from exc
    return [row for row in rows if isinstance(row, dict) and str(row.get("name", "")).strip()]


def remote_object_exists(path: str) -> bool:
    clean = _clean_object_path(path)
    parent, _, name = clean.rpartition("/")
    if not parent:
        return False
    return any(str(row.get("name")) == name for row in _list_objects(parent))


def cloud_store_status() -> dict[str, str | bool]:
    if not supabase_is_configured():
        return {
            "mode": "Local fallback",
            "configured": False,
            "active": False,
            "message": "Supabase Secrets have not been configured yet.",
        }
    try:
        active = remote_object_exists(DATABASE_OBJECT)
    except RuntimeError as exc:
        return {"mode": "Configuration error", "configured": True, "active": False, "message": str(exc)}
    if active:
        return {
            "mode": "Supabase persistent storage",
            "configured": True,
            "active": True,
            "message": "Supabase is the active durable data store.",
        }
    return {
        "mode": "Supabase awaiting migration",
        "configured": True,
        "active": False,
        "message": "Supabase is connected, but the current portal data has not been migrated yet.",
    }


def cloud_store_is_active() -> bool:
    return bool(cloud_store_status()["active"])


def upload_bytes(path: str, data: bytes, *, upsert: bool = True) -> None:
    store, _ = _storage()
    try:
        store.upload(
            path=_clean_object_path(path),
            file=data,
            file_options={"content-type": "application/octet-stream", "upsert": "true" if upsert else "false"},
        )
    except Exception as exc:
        raise RuntimeError("Supabase could not save the portal data file.") from exc


def download_bytes(path: str) -> bytes | None:
    if not remote_object_exists(path):
        return None
    store, _ = _storage()
    try:
        return bytes(store.download(_clean_object_path(path)))
    except Exception as exc:
        raise RuntimeError("Supabase could not retrieve the portal data file.") from exc


def delete_object(path: str) -> None:
    clean = _clean_object_path(path)
    if not remote_object_exists(clean):
        return
    store, _ = _storage()
    try:
        store.remove([clean])
    except Exception as exc:
        raise RuntimeError("Supabase could not delete the selected portal data file.") from exc


def sync_file_from_cloud(remote_path: str, local_path: Path) -> bool:
    """Download a durable file if it exists. Returns whether a remote copy was found."""
    if not cloud_store_is_active():
        return False
    data = download_bytes(remote_path)
    if data is None:
        return False
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if not local_path.is_file() or local_path.read_bytes() != data:
        local_path.write_bytes(data)
    return True


def sync_prefix_from_cloud(prefix: str, local_directory: Path, *, prune: bool = True) -> list[Path]:
    """Mirror one flat source-file folder from Supabase into the app's temporary cache."""
    if not cloud_store_is_active():
        return []
    local_directory.mkdir(parents=True, exist_ok=True)
    clean_prefix = _clean_object_path(prefix)
    remote_rows = _list_objects(clean_prefix)
    remote_names = {str(row.get("name")) for row in remote_rows}
    paths: list[Path] = []
    for name in sorted(remote_names):
        target = _safe_local_target(local_directory, name)
        data = download_bytes(f"{clean_prefix}/{name}")
        if data is None:
            continue
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
        paths.append(target)

    if prune:
        for local_path in local_directory.iterdir():
            if local_path.is_file() and local_path.name not in remote_names:
                local_path.unlink()
    return paths


def upload_local_file(remote_path: str, local_path: Path, *, upsert: bool = True) -> None:
    if not local_path.is_file():
        raise FileNotFoundError(f"Local portal data file not found: {local_path.name}")
    upload_bytes(remote_path, local_path.read_bytes(), upsert=upsert)


def migrate_local_data_store(data_store_dir: Path) -> dict[str, int]:
    """Upload the current managed data directory. Source files go first; DB marks completion."""
    if not supabase_is_configured():
        raise RuntimeError("Configure Supabase Secrets before starting the data migration.")
    if not data_store_dir.is_dir():
        raise RuntimeError("The local portal data store is not available for migration.")

    database_path = data_store_dir / "jovi_quality.db"
    if not database_path.is_file():
        raise RuntimeError("The local portal database is not available for migration.")

    source_files = [
        path for path in data_store_dir.rglob("*")
        if path.is_file() and path != database_path and "__pycache__" not in path.parts
    ]
    uploaded_bytes = 0
    for path in source_files:
        remote_path = path.relative_to(data_store_dir).as_posix()
        data = path.read_bytes()
        upload_bytes(remote_path, data, upsert=True)
        uploaded_bytes += len(data)

    upload_local_file(DATABASE_OBJECT, database_path, upsert=True)
    return {"files": len(source_files) + 1, "bytes": uploaded_bytes + database_path.stat().st_size}
