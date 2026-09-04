from __future__ import annotations

import unittest
from decimal import Decimal, getcontext

from evalcanary.assurance.numeric import (
    canonical_decimal,
    canonical_json_text,
    parse_decimal_token,
)
from evalcanary.assurance.security import (
    is_sensitive_key,
    omission_facts,
    redact_structured,
    redact_text,
    safe_reportable_url,
)
from evalcanary.errors import InputValidationError


class DecimalCanonicalizationTests(unittest.TestCase):
    def test_normative_vectors(self) -> None:
        vectors = {
            "0": "0",
            "-0": "0",
            "1": "1",
            "1.0": "1",
            "1e0": "1",
            "1.50": "1.5",
            "0.001": "0.001",
            "1e-3": "0.001",
            "1000": "1000",
            "1e3": "1000",
            "-2.50": "-2.5",
        }
        for token, expected in vectors.items():
            with self.subTest(token=token):
                self.assertEqual(canonical_decimal(parse_decimal_token(token)), expected)

    def test_context_does_not_change_identity(self) -> None:
        original = getcontext().prec
        try:
            getcontext().prec = 2
            self.assertEqual(canonical_decimal(Decimal("123456789.0100")), "123456789.01")
        finally:
            getcontext().prec = original

    def test_boundaries_and_equivalent_spellings(self) -> None:
        self.assertEqual(canonical_decimal(parse_decimal_token("1e1000")), "1" + "0" * 1000)
        self.assertEqual(canonical_decimal(parse_decimal_token("1e-1000")), "0." + "0" * 999 + "1")
        self.assertEqual(canonical_decimal(parse_decimal_token("-0e-1000")), "0")
        legal = "9" * 100
        self.assertEqual(canonical_decimal(parse_decimal_token(legal)), legal)
        for token in ("1e1001", "1e-1001", "0e1001", "0e-1001", "9" * 101):
            with self.subTest(token=token[:20]), self.assertRaises(InputValidationError):
                parse_decimal_token(token)

    def test_rejects_non_json_and_nonfinite_attempts(self) -> None:
        for token in ("+1", ".1", "01", "1.", "--1", "NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), self.assertRaises(InputValidationError):
                parse_decimal_token(token)

    def test_canonical_json_emits_unquoted_numbers(self) -> None:
        first = canonical_json_text({"n": Decimal("1.00"), "z": Decimal("-0")})
        second = canonical_json_text({"z": Decimal("0e9"), "n": Decimal("1e0")})
        self.assertEqual(first, '{"n":1,"z":0}')
        self.assertEqual(first, second)
        with self.assertRaises(TypeError):
            canonical_json_text({"binary": 0.1})


class SafeUrlTests(unittest.TestCase):
    def test_positive_urls_are_normalized_without_dereference(self) -> None:
        self.assertEqual(
            safe_reportable_url("HTTPS://Example.COM/a%41b/source"),
            "https://example.com/a%41b/source",
        )
        self.assertEqual(safe_reportable_url("http://docs.example.org"), "http://docs.example.org")

    def test_dangerous_urls_are_rejected(self) -> None:
        values = (
            "file:///tmp/x",
            "https://user:pass@example.com/a",
            "https://example.com:443/a",
            "https://example.com:/a",
            "https://127.0.0.1/a",
            "https://[::1]/a",
            "https://localhost/a",
            "https://host.local/a",
            "https://example.com/a?token=x",
            "https://example.com/a#fragment",
            "https://example.com/%2e%2e/x",
            "https://example.com/%5cwindows",
            "https://example.com/%0aheader",
            " https://example.com/a",
            "https://example.com\\share",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(safe_reportable_url(value))


class RedactionTests(unittest.TestCase):
    def test_structured_keys_and_suffixes_are_redacted(self) -> None:
        value = redact_structured(
            {
                "Authorization": "Bearer abc",
                "nested": {"provider-request-id": "req-1", "custom_token": "abc"},
            }
        )
        self.assertEqual(value["Authorization"], "[REDACTED_SECRET]")
        self.assertEqual(value["nested"]["provider-request-id"], "[REDACTED_SECRET]")
        self.assertTrue(is_sensitive_key("custom-token"))

    def test_text_canaries_are_redacted_before_any_excerpt_stage(self) -> None:
        source = (
            "Authorization: Bearer abcdef\n"
            "AKIA1234567890ABCDEF "
            "ghp_abcdefghijklmnopqrstuvwxyz "
            "sk-abcdefghijklmnopqrstuvwxyz "
            "eyJabc.def.ghi "
            "https://user:pass@example.com/a?access_token=secret "
            "C:\\Users\\Alice\\secret.txt"
        )
        redacted = redact_text(source)
        for secret in ("abcdef", "AKIA123", "ghp_", "sk-", "eyJabc", "user:pass", "Alice", "secret.txt"):
            self.assertNotIn(secret, redacted)
        self.assertIn("[REDACTED_AUTH]", redacted)
        self.assertIn("[REDACTED_PATH]", redacted)

    def test_omission_hash_is_canonical_for_equivalent_object_order(self) -> None:
        first = omission_facts({"a": 1, "b": 2})
        second = omission_facts({"b": 2, "a": 1})
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
