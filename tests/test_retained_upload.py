import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from tools import retained_upload


class RetainedUploadTests(unittest.TestCase):
    def test_keeps_uploaded_data_when_widget_is_hidden(self):
        source = BytesIO(b"sample BOM")
        source.name = "bom.csv"
        state = {}
        with patch.object(retained_upload, "st", SimpleNamespace(session_state=state)):
            self.assertIs(retained_upload.retain_upload(source, "saved"), source)
            source.read()
            restored = retained_upload.retain_upload(None, "saved")
            self.assertIs(restored, source)
            self.assertEqual(restored.read(), b"sample BOM")


if __name__ == "__main__":
    unittest.main()
