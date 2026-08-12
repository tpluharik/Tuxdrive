import unittest
from unittest.mock import MagicMock, patch

from tuxindrive.password_helper import ACCOUNT, LEGACY_SERVICE, SERVICE, configuration_password


class PasswordHelperTests(unittest.TestCase):
    @patch("tuxindrive.password_helper._keyring")
    def test_current_native_key_is_returned(self, keyring_factory):
        keyring = keyring_factory.return_value
        keyring.get_password.return_value = "current-secret"
        self.assertEqual(configuration_password(), "current-secret")
        keyring.get_password.assert_called_once_with(SERVICE, ACCOUNT)

    @patch("tuxindrive.password_helper._keyring")
    def test_legacy_native_key_is_read_in_place(self, keyring_factory):
        keyring = keyring_factory.return_value
        keyring.get_password.side_effect = [None, "legacy-secret"]
        self.assertEqual(configuration_password(), "legacy-secret")
        keyring.get_password.assert_any_call(LEGACY_SERVICE, ACCOUNT)
        keyring.set_password.assert_not_called()

    @patch("tuxindrive.password_helper.secrets.token_urlsafe", return_value="new-secret")
    @patch("tuxindrive.password_helper._keyring")
    def test_ensure_creates_key_only_when_missing(self, keyring_factory, _token):
        keyring = keyring_factory.return_value
        keyring.get_password.return_value = None
        self.assertEqual(configuration_password(ensure=True), "new-secret")
        keyring.set_password.assert_called_once_with(SERVICE, ACCOUNT, "new-secret")


if __name__ == "__main__":
    unittest.main()
