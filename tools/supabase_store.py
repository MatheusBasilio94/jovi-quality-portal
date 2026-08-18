"""Optional persistent storage for the Jovi Quality Center.

The portal can still run with its repository-local ``data_store`` directory.
When Supabase secrets are configured, this module makes Supabase Storage the
durable copy of that directory. This is intentionally file-based so existing
SMT, Assembly, OQC/FQC, and Smart Report logic can retain their tested local
SQLite and Excel readers while avoiding Streamlit Community Cloud's ephemeral
filesystem.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

try:  # Kept optional so local development works before cloud setup is complete.
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - exercised by Streamlit after requirements install.
    Client = Any  # type: ignore[misc,assignment]
    create_client = None


DEFAULT_BUCKET = "jovi-quality-data"
DATABASE_OBJECT = "state/jovi_quality.db"
DATA_VERSION_OBJECT = "state/data_version.json"
SYNC_MANIFEST_FILENAME = ".supabase_sync_manifest.json"
DATA_VERSION_FILENAME = ".supabase_data_version"


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
        # storage3 v0.12+ returns ``SyncBucket`` objects, while earlier
        # releases returned dictionaries. Support both shapes so that a
        # pre-existing bucket is not mistaken for a missing one.
        existing_ids = {
            str(item.get("id", "")) if isinstance(item, dict) else str(getattr(item, "id", ""))
            for item in existing
        }
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


@st.cache_resource(show_spinner=False)
def _bucket_store(url: str, key: str, bucket: str) -> Any:
    """Keep the checked bucket client across Streamlit reruns."""
    client = _client(url, key)
    _ensure_bucket(client, bucket)
    return client.storage.from_(bucket)


def _storage() -> tuple[Any, dict[str, str]]:
    _, config = _get_client()
    return _bucket_store(config["url"], config["key"], config["bucket"]), config


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


def _sync_manifest_path(local_path: Path) -> Path:
    return local_path.parent / SYNC_MANIFEST_FILENAME


def _data_version_path(local_path: Path) -> Path:
    return (local_path if local_path.is_dir() else local_path.parent) / DATA_VERSION_FILENAME


def _read_local_data_version(local_path: Path) -> str:
    try:
        return _data_version_path(local_path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_local_data_version(local_path: Path, version: str) -> None:
    if not version:
        return
    try:
        _data_version_path(local_path).write_text(version, encoding="utf-8")
    except OSError:
        # A missing marker only causes a safe metadata recheck on the next load.
        return


def _read_sync_manifest(local_path: Path) -> dict[str, str]:
    try:
        data = json.loads(_sync_manifest_path(local_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}


def _write_sync_manifest(local_path: Path, manifest: dict[str, str]) -> None:
    manifest_path = _sync_manifest_path(local_path)
    try:
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    except OSError:
        # A missing manifest only causes a future safe re-download; it must not
        # prevent the portal from using the durable cloud copy.
        return


def _object_fingerprint(row: dict) -> str:
    """Return stable remote metadata used to avoid downloading unchanged files."""
    metadata = row.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    marker = {
        "id": row.get("id", ""),
        "updated_at": row.get("updated_at", row.get("created_at", "")),
        "etag": metadata.get("eTag", metadata.get("etag", "")),
        "last_modified": metadata.get("lastModified", metadata.get("last_modified", "")),
        "size": metadata.get("size", row.get("size", "")),
    }
    return json.dumps(marker, sort_keys=True, default=str)


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


def cloud_data_version() -> str:
    """Read the compact revision marker without listing every stored source file."""
    if not supabase_is_configured():
        return ""
    store, _ = _storage()
    try:
        raw = bytes(store.download(DATA_VERSION_OBJECT))
    except Exception:
        return ""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return ""
    return str(payload.get("version", "")).strip() if isinstance(payload, dict) else ""


def bump_cloud_data_version(reason: str = "data update") -> str:
    """Publish a new revision after a successful portal data write."""
    store, _ = _storage()
    version = f"{datetime.now(timezone.utc).isoformat(timespec='microseconds')}:{uuid4().hex}"
    payload = json.dumps(
        {"version": version, "reason": str(reason), "updated_at": datetime.now(timezone.utc).isoformat()},
        sort_keys=True,
    ).encode("utf-8")
    try:
        store.upload(
            path=DATA_VERSION_OBJECT,
            file=payload,
            file_options={"content-type": "application/json", "upsert": "true"},
        )
    except Exception as exc:
        raise RuntimeError("Supabase could not publish the portal data revision.") from exc
    return version


def ensure_cloud_data_version() -> str:
    """Create the revision marker once for pre-existing migrated portal data."""
    version = cloud_data_version()
    if version:
        return version
    if remote_object_exists(DATABASE_OBJECT):
        return bump_cloud_data_version("initialize data revision")
    return ""


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


def sync_file_from_cloud(
    remote_path: str,
    local_path: Path,
    *,
    force: bool = False,
    data_version: str = "",
    cloud_active: bool | None = None,
) -> bool:
    """Sync one remote file, downloading it only when its metadata changed."""
    if cloud_active is None:
        cloud_active = cloud_store_is_active()
    if not cloud_active:
        return False
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if data_version and not force and local_path.is_file() and _read_local_data_version(local_path) == data_version:
        return True
    clean = _clean_object_path(remote_path)
    parent, _, name = clean.rpartition("/")
    if not parent:
        return False
    remote_row = next((row for row in _list_objects(parent) if str(row.get("name")) == name), None)
    if remote_row is None:
        return False
    manifest = _read_sync_manifest(local_path)
    fingerprint = _object_fingerprint(remote_row)
    if not force and local_path.is_file() and manifest.get(clean) == fingerprint:
        _write_local_data_version(local_path, data_version)
        return True
    store, _ = _storage()
    try:
        data = bytes(store.download(clean))
    except Exception as exc:
        raise RuntimeError("Supabase could not retrieve the portal data file.") from exc
    if not local_path.is_file() or local_path.read_bytes() != data:
        local_path.write_bytes(data)
    manifest[clean] = fingerprint
    _write_sync_manifest(local_path, manifest)
    _write_local_data_version(local_path, data_version)
    return True


def sync_prefix_from_cloud(
    prefix: str,
    local_directory: Path,
    *,
    prune: bool = True,
    force: bool = False,
    data_version: str = "",
    cloud_active: bool | None = None,
) -> list[Path]:
    """Mirror one source folder, downloading only new or changed cloud objects."""
    if cloud_active is None:
        cloud_active = cloud_store_is_active()
    if not cloud_active:
        return []
    local_directory.mkdir(parents=True, exist_ok=True)
    if data_version and not force and _read_local_data_version(local_directory) == data_version:
        return sorted(
            path
            for path in local_directory.iterdir()
            if path.is_file() and path.name not in {SYNC_MANIFEST_FILENAME, DATA_VERSION_FILENAME}
        )
    clean_prefix = _clean_object_path(prefix)
    remote_rows = _list_objects(clean_prefix)
    remote_names = {str(row.get("name")) for row in remote_rows}
    manifest = _read_sync_manifest(local_directory)
    next_manifest: dict[str, str] = {}
    store, _ = _storage()
    paths: list[Path] = []
    for row in sorted(remote_rows, key=lambda item: str(item.get("name", ""))):
        name = str(row.get("name"))
        target = _safe_local_target(local_directory, name)
        remote_path = f"{clean_prefix}/{name}"
        fingerprint = _object_fingerprint(row)
        if force or not target.is_file() or manifest.get(remote_path) != fingerprint:
            try:
                data = bytes(store.download(remote_path))
            except Exception as exc:
                raise RuntimeError("Supabase could not retrieve the portal data file.") from exc
            if not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)
        next_manifest[remote_path] = fingerprint
        paths.append(target)

    if prune:
        for local_path in local_directory.iterdir():
            if local_path.name in {SYNC_MANIFEST_FILENAME, DATA_VERSION_FILENAME}:
                continue
            if local_path.is_file() and local_path.name not in remote_names:
                local_path.unlink()
    _write_sync_manifest(local_directory, next_manifest)
    _write_local_data_version(local_directory, data_version)
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
        if (
            path.is_file()
            and path != database_path
            and path.name not in {SYNC_MANIFEST_FILENAME, DATA_VERSION_FILENAME}
            and "__pycache__" not in path.parts
        )
    ]
    uploaded_bytes = 0
    for path in source_files:
        remote_path = path.relative_to(data_store_dir).as_posix()
        data = path.read_bytes()
        upload_bytes(remote_path, data, upsert=True)
        uploaded_bytes += len(data)

    upload_local_file(DATABASE_OBJECT, database_path, upsert=True)
    bump_cloud_data_version("initial data migration")
    return {"files": len(source_files) + 1, "bytes": uploaded_bytes + database_path.stat().st_size}
