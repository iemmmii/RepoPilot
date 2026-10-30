"""Original contract tests mapped to the requirement accepted in upstream PR #133."""

import unittest

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner


class ManualClockSigner(TimestampSigner):
    clock = 1_600_000_000

    def get_timestamp(self):
        return self.clock


class TimestampContract(unittest.TestCase):
    def setUp(self):
        self.signer = ManualClockSigner("public-fixture-key")

    def token(self, age):
        self.signer.clock = 1_600_000_000 - age
        signed = self.signer.sign(b"payload")
        self.signer.clock = 1_600_000_000
        return signed

    def test_future_rejected(self):
        with self.assertRaises(SignatureExpired):
            self.signer.unsign(self.token(-1), max_age=10)

    def test_current_valid(self):
        self.assertEqual(self.signer.unsign(self.token(0), max_age=10), b"payload")

    def test_at_max_age_valid(self):
        self.assertEqual(self.signer.unsign(self.token(10), max_age=10), b"payload")

    def test_past_expired(self):
        with self.assertRaises(SignatureExpired):
            self.signer.unsign(self.token(11), max_age=10)

    def test_no_age_limit_preserved(self):
        self.assertEqual(self.signer.unsign(self.token(-1)), b"payload")

    def test_bad_signature_rejected(self):
        with self.assertRaises(BadSignature):
            self.signer.unsign(self.token(0) + b"tampered", max_age=10)
