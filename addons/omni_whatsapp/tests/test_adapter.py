"""The adapter between the dispatch queue and Meta. Fake sends only; needs Odoo's import path."""
import json
import os
import unittest
from unittest.mock import patch

try:
    from odoo.addons.omni_channel.providers.dispatch import DispatchClaim
    from odoo.addons.omni_whatsapp.providers import adapter as wa
except ImportError:  # the stand-alone protocol run (python -m unittest discover) has no Odoo
    wa = None

PHONE = '234567890'
CONFIG = {'account_key': PHONE, 'namespace': PHONE, 'sender_key': PHONE, 'credential_reference': 'ref',
          'adapter': {'database': 'db', 'company_id': 1, 'purpose_id': 1, 'business_account_id': '123456789'}}


def payload(**changes):
    return dict({'operation': 'template.send', 'account': PHONE, 'sender': PHONE, 'recipient': '+60123456789',
                 'body': 'Hi Sara, spring is here!',
                 'template': {'name': 'spring_offer_7', 'language': 'en', 'body': ['Sara']}}, **changes)


@unittest.skipIf(wa is None, 'needs Odoo')
class TestAdapter(unittest.TestCase):
    def claim(self, data):
        return DispatchClaim(1, 1, 'token', 'uuid', 'whatsapp', json.dumps(data), PHONE, PHONE, PHONE, 'ref',
                             json.dumps(CONFIG['adapter']))

    def dispatch(self, data, answer):
        sent = []

        def send(version, phone, token, recipient, template):
            sent.append((version, phone, token, recipient, template))
            return answer

        with patch.object(wa, 'bundle', lambda config: {'access_token': 'synthetic-only'}), \
                patch.object(wa.business, 'send_template', send), \
                patch.dict(os.environ, {'OMNI_WHATSAPP_GRAPH_VERSION': 'v99.0'}):
            return wa.WhatsAppAdapter().dispatch(self.claim(data)), sent

    def test_only_a_template_for_this_number_is_valid(self):
        adapter = wa.WhatsAppAdapter()
        self.assertTrue(adapter.validate_command(payload(), CONFIG))
        self.assertFalse(adapter.validate_command(payload(operation='message.send'), CONFIG), 'No free text')
        self.assertFalse(adapter.validate_command(payload(account='999'), CONFIG))
        self.assertFalse(adapter.validate_command(payload(recipient='not a number'), CONFIG))
        self.assertFalse(adapter.validate_command(payload(template={'name': 'x', 'language': 'en',
                                                                    'body': ['a\nb']}), CONFIG))

    def test_dispatch_sends_once_with_digits_only(self):
        result, sent = self.dispatch(payload(), ('accepted', 'wamid.synthetic', 0))
        self.assertEqual((result.outcome, result.provider_message_key), ('accepted', 'wamid.synthetic'))
        self.assertEqual(sent, [('v99.0', PHONE, 'synthetic-only', '60123456789',
                                 {'name': 'spring_offer_7', 'language': 'en', 'body': ['Sara']})])

    def test_meta_refusals_become_queue_reasons(self):
        for detail, retryable, reason in (('rate_limited', True, 'rate_limited'),
                                          ('daily_limit', True, 'rate_limited'),
                                          ('unauthorized', False, 'unauthorized'),
                                          ('invalid_recipient', False, 'invalid_recipient'),
                                          ('template', False, 'unsupported')):
            result, _sent = self.dispatch(payload(), ('not_sent', detail, 60 if retryable else 0))
            self.assertEqual((result.outcome, result.retryable, result.reason_code),
                             ('definitely_not_sent', retryable, reason))
        result, _sent = self.dispatch(payload(), ('unknown', 'unconfirmed', 0))
        self.assertEqual(result.outcome, 'unknown')
        result, sent = self.dispatch(payload(operation='message.send'), ('accepted', 'wamid.x', 0))
        self.assertEqual((result.outcome, sent), ('definitely_not_sent', []), 'Free text never reaches Meta')
