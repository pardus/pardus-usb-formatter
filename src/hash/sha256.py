import hashlib


class HashMismatchError(Exception):
    def __init__(self, expected, actual):
        super().__init__("SHA-256 checksum does not match")
        self.expected = expected
        self.actual = actual


class SHA256Verifier:
    """Incrementally validates a byte stream against a SHA-256 checksum."""

    def __init__(self, expected):
        expected = expected.lower().strip()
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise ValueError("Expected SHA-256 checksum must be 64 hexadecimal characters")
        self.expected = expected
        self._hasher = hashlib.sha256()

    def update(self, chunk):
        self._hasher.update(chunk)

    def hexdigest(self):
        return self._hasher.hexdigest()

    def verify(self):
        actual = self.hexdigest()
        if actual != self.expected:
            raise HashMismatchError(self.expected, actual)
        return actual
