import unittest

from pydantic import ValidationError

from fastapi_cache.main import InferenceRequest


class InferenceRequestTests(unittest.TestCase):
    def test_prompt_is_required(self):
        with self.assertRaises(ValidationError):
            InferenceRequest()

    def test_empty_prompt_is_rejected(self):
        with self.assertRaises(ValidationError):
            InferenceRequest(prompt="")

    def test_prompt_over_maximum_length_is_rejected(self):
        with self.assertRaises(ValidationError):
            InferenceRequest(prompt="x" * 1001)

    def test_prompt_at_maximum_length_is_accepted(self):
        request = InferenceRequest(prompt="x" * 1000)

        self.assertEqual(len(request.prompt), 1000)

    def test_invalid_provider_is_rejected(self):
        with self.assertRaises(ValidationError):
            InferenceRequest(prompt="what is a cache", provider="bad")

    def test_provider_defaults_to_fake(self):
        request = InferenceRequest(prompt="what is a cache")

        self.assertEqual(request.provider, "fake")

    def test_huggingface_provider_is_accepted(self):
        request = InferenceRequest(
            prompt="what is a cache",
            provider="huggingface",
        )

        self.assertEqual(request.provider, "huggingface")


if __name__ == "__main__":
    unittest.main()
