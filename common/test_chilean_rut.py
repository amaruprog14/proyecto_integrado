from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from common.chilean_rut import normalize_chilean_rut, validate_chilean_rut


class ChileanRutValidationTests(SimpleTestCase):
    def test_accepts_and_normalizes_valid_rut_formats(self):
        self.assertEqual(normalize_chilean_rut("12.345.678-5"), "12345678-5")
        self.assertEqual(normalize_chilean_rut("12.345.6785"), "12345678-5")

    def test_accepts_lowercase_k_and_returns_uppercase(self):
        self.assertEqual(normalize_chilean_rut("16.666.666-k"), "16666666-K")

    def test_rejects_invalid_check_digit(self):
        with self.assertRaises(ValidationError):
            validate_chilean_rut("12.345.678-9")

    def test_rejects_arbitrary_identifiers_and_malformed_format(self):
        for value in ("RUT-123", "12345678-A", "12.34.567-8", "1234567890-1"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_chilean_rut(value)
