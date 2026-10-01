import hashlib
import unittest
from unittest.mock import patch

from tools.access_control import (
    Account,
    account_from_token,
    authenticate,
    configured_accounts,
    is_admin_session,
    require_admin_access,
)
from tools.auth_session import issue_token


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.admin = Account("administrator", hashlib.sha256(b"admin-test-password").hexdigest(), "admin")
        self.viewer = Account("viewer", hashlib.sha256(b"viewer-test-password").hexdigest(), "viewer")
        self.accounts = (self.admin, self.viewer)

    def test_credentials_select_the_correct_role(self):
        self.assertEqual(authenticate(" Administrator ", "admin-test-password", self.accounts), self.admin)
        self.assertEqual(authenticate("viewer", "viewer-test-password", self.accounts), self.viewer)
        self.assertIsNone(authenticate("viewer", "admin-test-password", self.accounts))
        self.assertIsNone(authenticate("viewer", "wrong-password", self.accounts))

    def test_cookie_restores_only_its_own_account(self):
        token = issue_token(self.viewer.username, self.viewer.password_hash)
        self.assertEqual(account_from_token(token, self.accounts), self.viewer)
        rotated = Account(self.viewer.username, hashlib.sha256(b"new-password").hexdigest(), "viewer")
        self.assertIsNone(account_from_token(token, (self.admin, rotated)))

    def test_viewer_cannot_use_write_permission(self):
        admin_session = {"authenticated": True, "auth_role": "admin"}
        viewer_session = {"authenticated": True, "auth_role": "viewer"}
        self.assertTrue(is_admin_session(admin_session))
        require_admin_access(admin_session)
        self.assertFalse(is_admin_session(viewer_session))
        with self.assertRaises(PermissionError):
            require_admin_access(viewer_session)
        with self.assertRaises(PermissionError):
            require_admin_access({"authenticated": False, "auth_role": "admin"})

    def test_distinct_account_names_are_required(self):
        with patch.dict("os.environ", {"JOVI_ADMIN_USERNAME": "jovi", "JOVI_STANDARD_USERNAME": "JOVI"}):
            with self.assertRaises(ValueError):
                configured_accounts()


if __name__ == "__main__":
    unittest.main()
