import os
import unittest
from unittest.mock import patch

from access_control import stripe_live_configured


class AccessControlConfigTests(unittest.TestCase):
    def test_live_stripe_configuration_is_accepted(self):
        values = {
            "STRIPE_PUBLISHABLE_KEY": "pk_live_example",
            "STRIPE_SECRET_KEY": "sk_live_example",
            "STRIPE_WEBHOOK_SECRET": "whsec_example",
            "STRIPE_PRICE_ID": "price_example",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertTrue(stripe_live_configured())

    def test_test_mode_stripe_configuration_is_rejected(self):
        values = {
            "STRIPE_PUBLISHABLE_KEY": "pk_test_example",
            "STRIPE_SECRET_KEY": "sk_test_example",
            "STRIPE_WEBHOOK_SECRET": "whsec_example",
            "STRIPE_PRICE_ID": "price_example",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertFalse(stripe_live_configured())

    def test_incomplete_stripe_configuration_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(stripe_live_configured())