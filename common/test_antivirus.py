import subprocess
from io import BytesIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from common.antivirus import scan_upload


@override_settings(CLAMAV_ENABLED=True, CLAMAV_CLIENT="clamdscan")
class AntivirusTests(SimpleTestCase):
    @patch("common.antivirus.subprocess.run")
    def test_clean_infected_unavailable_and_timeout(self, run):
        upload = BytesIO(b"imagen ficticia")
        upload.seek(4)
        run.return_value.returncode = 0
        scan_upload(upload)
        self.assertEqual(run.call_args.kwargs["input"], upload.getvalue())
        self.assertEqual(upload.tell(), 0)
        for code in (1, 2):
            run.return_value.returncode = code
            with self.assertRaises(ValidationError):
                scan_upload(upload)
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("clamdscan", 15)):
            run.side_effect = error
            with self.assertRaises(ValidationError):
                scan_upload(upload)

    @override_settings(CLAMAV_ENABLED=False)
    @patch("common.antivirus.subprocess.run")
    def test_disabled_skips_external_client(self, run):
        scan_upload(BytesIO())
        run.assert_not_called()
