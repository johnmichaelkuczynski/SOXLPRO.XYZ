import os
import unittest
from unittest.mock import patch

import anthropic_client
import openai_client


class OpenAIProviderKeyTests(unittest.TestCase):
    def test_owner_key_uses_standard_endpoint_by_default(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "owner-key"}, clear=True), \
                patch.object(openai_client, "OpenAI") as constructor:
            openai_client.get_openai_client()
        constructor.assert_called_once_with(api_key="owner-key")
        self.assertTrue(openai_client.openai_available())

    def test_owner_key_and_optional_base_url_take_precedence(self):
        env = {
            "OPENAI_API_KEY": "owner-key",
            "OPENAI_BASE_URL": "https://api.example.test/v1",
            "AI_INTEGRATIONS_OPENAI_API_KEY": "replit-key",
            "AI_INTEGRATIONS_OPENAI_BASE_URL": "https://replit.example.test",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(openai_client, "OpenAI") as constructor:
            openai_client.get_openai_client()
        constructor.assert_called_once_with(
            api_key="owner-key", base_url="https://api.example.test/v1"
        )

    def test_replit_integration_remains_fallback(self):
        env = {
            "AI_INTEGRATIONS_OPENAI_API_KEY": "integration-key",
            "AI_INTEGRATIONS_OPENAI_BASE_URL": "https://replit.example.test",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(openai_client, "OpenAI") as constructor:
            openai_client.get_openai_client()
        constructor.assert_called_once_with(
            api_key="integration-key", base_url="https://replit.example.test"
        )


class AnthropicProviderKeyTests(unittest.TestCase):
    def test_owner_key_uses_standard_endpoint_by_default(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "owner-key"}, clear=True), \
                patch.object(anthropic_client, "Anthropic") as constructor:
            anthropic_client.get_anthropic_client()
        constructor.assert_called_once_with(api_key="owner-key")
        self.assertTrue(anthropic_client.anthropic_available())

    def test_owner_key_and_optional_base_url_take_precedence(self):
        env = {
            "ANTHROPIC_API_KEY": "owner-key",
            "ANTHROPIC_BASE_URL": "https://api.example.test",
            "AI_INTEGRATIONS_ANTHROPIC_API_KEY": "replit-key",
            "AI_INTEGRATIONS_ANTHROPIC_BASE_URL": "https://replit.example.test",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(anthropic_client, "Anthropic") as constructor:
            anthropic_client.get_anthropic_client()
        constructor.assert_called_once_with(
            api_key="owner-key", base_url="https://api.example.test"
        )

    def test_replit_integration_remains_fallback(self):
        env = {
            "AI_INTEGRATIONS_ANTHROPIC_API_KEY": "integration-key",
            "AI_INTEGRATIONS_ANTHROPIC_BASE_URL": "https://replit.example.test",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(anthropic_client, "Anthropic") as constructor:
            anthropic_client.get_anthropic_client()
        constructor.assert_called_once_with(
            api_key="integration-key", base_url="https://replit.example.test"
        )

    def test_missing_credentials_fails_clearly(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(anthropic_client.anthropic_available())
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                anthropic_client.get_anthropic_client()

