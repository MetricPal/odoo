"""WhatsApp text intake through the existing durable inbox. No outbound API."""
import hashlib
import os

from odoo.addons.omni_channel.providers.inbound import InboundEvent
from odoo.addons.omni_channel.providers.base import HealthResult

from . import vault
from .webhook import text_messages
from .connection import GraphReadOnly, verify_account, select_phone


def bundle(config):
    scope = config['adapter']
    return vault.load(config['credential_reference'], database=scope['database'],
                      company_id=scope['company_id'], purpose_id=scope['purpose_id'],
                      business_account_id=scope['business_account_id'],
                      phone_number_id=config['account_key'])


class WhatsAppAdapter:
    inbound_release_ready = True
    dispatch_supported = False

    def check_sender_health(self, config):
        credentials = bundle(config)
        numbers = verify_account(GraphReadOnly(os.environ.get('OMNI_WHATSAPP_GRAPH_VERSION')),
                                 credentials['business_account_id'], credentials['access_token'])
        phone = select_phone(numbers, config['account_key'])
        return HealthResult(config['namespace'] == phone.id and config['sender_key'] == phone.id,
                            namespace=phone.id, account_key=phone.id, sender_key=phone.id)

    def check_endpoint(self, config):
        credentials = bundle(config)
        return bool(config.get('whatsapp_callback_verified') and credentials.get('app_secret')
                    and credentials.get('verify_token') and config['endpoint_key'] == config['account_key']
                    and config['namespace'] == config['account_key'])

    def verify_request(self, raw, headers, config):
        credentials = bundle(config)
        self.messages = text_messages(raw, headers, app_secret=credentials['app_secret'],
                                     business_account_id=credentials['business_account_id'],
                                     phone_number_id=credentials['phone_number_id'])
        self.raw_hash = hashlib.sha256(raw).hexdigest()
        return True

    def normalize(self, value, config):
        # Parse ORIGINAL authenticated bytes in verify_request, including duplicate JSON keys.
        return tuple(InboundEvent(event_key=message.message_id, endpoint_key=config['endpoint_key'],
                                  namespace=config['namespace'], kind='message',
                                  sender_key=message.sender_id, thread_key=message.sender_id,
                                  message_key=message.message_id, body=message.body,
                                  occurred_at=message.occurred_at) for message in self.messages) or (
            InboundEvent(event_key='unsupported:' + self.raw_hash, endpoint_key=config['endpoint_key'],
                         namespace=config['namespace'], kind='unsupported'),)
