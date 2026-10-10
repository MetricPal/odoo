"""Fixture safety does not depend on an email mock in the test runner."""
import unittest
from unittest.mock import Mock, patch

from .test_users import new_test_user


class TestUserInvitationSafety(unittest.TestCase):
    def test_invites_and_tracking_are_disabled_with_custom_context(self):
        original = {'lang': 'en_US', 'no_reset_password': False}
        with patch('odoo.addons.omni_channel.tests.test_users.odoo_new_test_user') as create:
            new_test_user(Mock(), login='fixture', context=original)
        context = create.call_args.kwargs['context']
        self.assertTrue(context['no_reset_password'])
        self.assertTrue(context['tracking_disable'])
        self.assertTrue(context['mail_create_nosubscribe'])
        self.assertEqual(context['lang'], 'en_US')
        self.assertFalse(original['no_reset_password'])
