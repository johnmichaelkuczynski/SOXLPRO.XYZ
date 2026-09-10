import unittest
from unittest.mock import patch

from access import (
    GUEST,
    PAID,
    SIGNED_IN,
    access_tier,
    can_access,
    can_use_market_chat,
    has_paid_access,
    require_paid_access,
)


GUEST_USER = {"is_logged_in": False}
SIGNED_IN_USER = {"is_logged_in": True, "sub": "user-1"}


class AccessTests(unittest.TestCase):
    def test_guest_keeps_public_surfaces_but_not_chat_or_paid_features(self):
        self.assertEqual(access_tier(GUEST_USER, preview=False), GUEST)
        self.assertTrue(can_access("Chart & Probabilities", GUEST_USER, preview=False))
        self.assertTrue(can_access("Snapshot", GUEST_USER, preview=False))
        self.assertFalse(can_use_market_chat(GUEST_USER, preview=False))
        self.assertFalse(
            can_access("Vol Surface", GUEST_USER, paid_verified=True, preview=False)
        )

    def test_signed_in_unpaid_user_gets_chat_without_paid_features(self):
        self.assertEqual(
            access_tier(SIGNED_IN_USER, paid_verified=False, preview=False),
            SIGNED_IN,
        )
        self.assertTrue(can_use_market_chat(SIGNED_IN_USER, preview=False))
        self.assertFalse(
            has_paid_access(SIGNED_IN_USER, paid_verified=False, preview=False)
        )

    def test_paid_user_can_enter_each_paid_feature(self):
        self.assertEqual(
            access_tier(SIGNED_IN_USER, paid_verified=True, preview=False), PAID
        )
        for feature in (
            "Vol Surface",
            "Call Risk/Reward",
            "Dislocation",
            "Backtest",
            "Strategy Builder",
        ):
            self.assertTrue(
                can_access(
                    feature,
                    SIGNED_IN_USER,
                    paid_verified=True,
                    preview=False,
                )
            )

    def test_preview_is_full_access_only_while_preview_user_is_signed_in(self):
        self.assertTrue(
            has_paid_access(
                SIGNED_IN_USER, paid_verified=False, preview=True
            )
        )
        self.assertEqual(access_tier(GUEST_USER, preview=True), GUEST)

    def test_rendering_guard_blocks_entry_and_renders_gate(self):
        purchase_dialog = lambda: None
        with patch("access.render_paid_gate") as render_gate:
            self.assertFalse(
                require_paid_access(
                    "Backtest",
                    SIGNED_IN_USER,
                    purchase_dialog,
                    paid_verified=False,
                    preview=False,
                )
            )
            render_gate.assert_called_once_with("Backtest", purchase_dialog)

            render_gate.reset_mock()
            self.assertTrue(
                require_paid_access(
                    "Backtest",
                    SIGNED_IN_USER,
                    purchase_dialog,
                    paid_verified=True,
                    preview=False,
                )
            )
            render_gate.assert_not_called()


if __name__ == "__main__":
    unittest.main()