import unittest

from support import fake

from ghost.redact import redact


class RedactTests(unittest.TestCase):
    def test_known_key_formats(self):
        samples = [
            fake("AKIA", "Q" * 16),
            fake("gh", "p_", "a1" * 18),
            fake("github", "_pat_", "B2" * 25),
            fake("gl", "pat-", "c3" * 10),
            fake("sk", "-", "proj-", "x9" * 15),
            fake("sk", "_live_", "z" * 24),
            fake("xox", "b-", "1234567890-abcdef"),
            fake("AI", "za", "y" * 35),
            fake("hf", "_", "Hf" * 16),
            fake("ey", "J", "a" * 12, ".ey", "J", "b" * 12, ".", "c" * 12),
            fake("-----BEGIN ", "OPENSSH PRIVATE KEY-----\n", "abc\n" * 3, "-----END ", "OPENSSH PRIVATE KEY-----"),
        ]
        for secret in samples:
            with self.subTest(secret=secret[:5]):
                text, count = redact(f"before {secret} after")
                self.assertEqual(text, "before [redacted] after")
                self.assertEqual(count, 1)

    def test_an_unfinished_private_key_is_hidden_to_the_end(self):
        text, count = redact(fake("note\n-----BEGIN ", "RSA PRIVATE KEY-----\n", "MIIE" * 10))
        self.assertEqual((text, count), ("note\n[redacted]", 1))

    def test_assignments_hide_values_that_look_like_keys(self):
        value = fake("hunter2", "hunter2")
        for line in (f'password = "{value}"', f"API_KEY={value}", f"token: {value}", f"client_secret='{value}'"):
            with self.subTest(line=line):
                self.assertEqual(redact(line), (line.replace(value, "[redacted]"), 1))

    def test_words_and_code_are_left_alone(self):
        for line in (
            "token = get_token()",
            'api_key = os.environ["API_KEY"]',
            "password: correcthorsebattery",
            "the secret is out",
            "token_url: ${{ inputs.url }}",
            "a task-management-system-overview-2026",
        ):
            with self.subTest(line=line):
                self.assertEqual(redact(line), (line, 0))

    def test_redacting_twice_finds_nothing_new(self):
        value = fake("abc123", "def456")
        once, count = redact(fake("AKIA", "Q" * 16) + f' password="{value}"')
        self.assertEqual(count, 2)
        self.assertEqual(redact(once), (once, 0))
