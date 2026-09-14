import importlib
import sys
import types
import unittest
from unittest.mock import patch


def _identity_cache_resource(*args, **kwargs):
    def decorator(function):
        return function

    return decorator


streamlit_stub = types.ModuleType("streamlit")
streamlit_stub.cache_resource = _identity_cache_resource
streamlit_stub.secrets = {}
sys.modules.setdefault("streamlit", streamlit_stub)

supabase_stub = types.ModuleType("supabase")
supabase_stub.Client = object
supabase_stub.create_client = lambda *args, **kwargs: object()
supabase_client_stub = types.ModuleType("supabase.client")
supabase_client_stub.ClientOptions = lambda **kwargs: kwargs
sys.modules.setdefault("supabase", supabase_stub)
sys.modules.setdefault("supabase.client", supabase_client_stub)

supabase_store = importlib.import_module("tools.supabase_store")


class FakeStore:
    def __init__(self, rows=None, failures=0, list_failures=0):
        self.rows = rows or []
        self.failures = failures
        self.list_failures = list_failures
        self.download_calls = 0
        self.list_calls = 0

    def list(self, *args, **kwargs):
        self.list_calls += 1
        if self.list_calls <= self.list_failures:
            raise TimeoutError("temporary list timeout")
        return self.rows

    def download(self, path):
        self.download_calls += 1
        if self.download_calls <= self.failures:
            raise TimeoutError("temporary timeout")
        return b"ok"


class SupabaseStoreTests(unittest.TestCase):
    def test_list_objects_ignores_folders_and_internal_placeholders(self):
        store = FakeStore(
            [
                {"name": ".emptyFolderPlaceholder", "metadata": {"size": 0}},
                {"name": "nested-folder", "metadata": None},
                {"name": "input.xls", "metadata": {"size": 10}},
            ]
        )
        with patch.object(supabase_store, "_storage", return_value=(store, {})):
            rows = supabase_store._list_objects("smt/fpy/input")
        self.assertEqual([row["name"] for row in rows], ["input.xls"])

    def test_download_retries_transient_timeouts(self):
        store = FakeStore(failures=2)
        with patch.object(supabase_store.time, "sleep", return_value=None):
            data = supabase_store._download_with_retry(store, "smt/fpy/input/input.xls")
        self.assertEqual(data, b"ok")
        self.assertEqual(store.download_calls, 3)

    def test_list_objects_retries_transient_timeouts(self):
        store = FakeStore(
            [{"name": "input.xls", "metadata": {"size": 10}}],
            list_failures=2,
        )
        with (
            patch.object(supabase_store, "_storage", return_value=(store, {})),
            patch.object(supabase_store.time, "sleep", return_value=None),
        ):
            rows = supabase_store._list_objects("smt/fpy/input")
        self.assertEqual([row["name"] for row in rows], ["input.xls"])
        self.assertEqual(store.list_calls, 3)


if __name__ == "__main__":
    unittest.main()
