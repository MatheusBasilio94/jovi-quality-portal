import unittest

from tools.auth_session import SESSION_SECONDS, issue_token, revoke_token, verify_token


class AuthSessionTests(unittest.TestCase):
    def test_token_survives_new_session_until_expiry(self):
        token = issue_token("jovi", "password-hash", now=1000)
        self.assertTrue(verify_token(token, "jovi", "password-hash", now=1001))
        self.assertTrue(verify_token(token, "jovi", "password-hash", now=1000 + SESSION_SECONDS - 1))
        self.assertFalse(verify_token(token, "jovi", "password-hash", now=1000 + SESSION_SECONDS))

    def test_tampering_or_password_change_invalidates_token(self):
        token = issue_token("jovi", "password-hash", now=1000)
        self.assertFalse(verify_token(token, "jovi", "new-password-hash", now=1001))
        self.assertFalse(verify_token(token, "another-user", "password-hash", now=1001))
        self.assertFalse(verify_token(token[:-1] + ("0" if token[-1] != "0" else "1"), "jovi", "password-hash", now=1001))

    def test_sign_out_revokes_token(self):
        token = issue_token("jovi", "password-hash")
        self.assertTrue(verify_token(token, "jovi", "password-hash"))
        revoke_token(token)
        self.assertFalse(verify_token(token, "jovi", "password-hash"))


if __name__ == "__main__":
    unittest.main()
