"""WhatsApp through the existing durable inbox and dispatch queue.

Receiving: private text messages, and Meta's reports about messages this number sent (delivered, read, failed).
Sending: one operation only, ``template.send``: a template Meta approved, with its numbered fields filled.
Free text (``message.send``) is refused: WhatsApp allows it only inside a person's 24-hour window, which this
version does not track.
"""
import hashlib
import json
import os

from odoo.addons.omni_channel.providers.base import HealthResult
from odoo.addons.omni_channel.providers.dispatch import DispatchResult
from odoo.addons.omni_channel.providers.inbound import InboundEvent

from . import business, vault
from .connection import GraphReadOnly, select_phone, verify_account
from .webhook import notifications

# What business.send_template reports → the queue's fixed reason codes (retryable, reason).
NOT_SENT = {
    'rate_limited': (True, 'rate_limited'),
    'daily_limit': (True, 'rate_limited'),
    'unauthorized': (False, 'unauthorized'),
    'invalid_recipient': (False, 'invalid_recipient'),
    'template': (False, 'unsupported'),
    'configuration': (False, 'unsupported'),
}


def bundle(config):
    scope = config['adapter']
    return vault.load(config['credential_reference'], database=scope['database'],
                      company_id=scope['company_id'], purpose_id=scope['purpose_id'],
                      business_account_id=scope['business_account_id'],
                      phone_number_id=config['account_key'])


def recipient_number(value):
    """Meta wants digits only; contacts keep the international form with a plus."""
    return value[1:] if isinstance(value, str) and value.startswith('+') else value


class WhatsAppAdapter:
    inbound_release_ready = True
    dispatch_supported = True

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
        self.messages, self.statuses = notifications(
            raw, headers, app_secret=credentials['app_secret'],
            business_account_id=credentials['business_account_id'],
            phone_number_id=credentials['phone_number_id'])
        self.raw_hash = hashlib.sha256(raw).hexdigest()
        return True

    def normalize(self, value, config):
        # Parse ORIGINAL authenticated bytes in verify_request, including duplicate JSON keys.
        events = [InboundEvent(event_key=message.message_id, endpoint_key=config['endpoint_key'],
                               namespace=config['namespace'], kind='message',
                               sender_key=message.sender_id, thread_key=message.sender_id,
                               message_key=message.message_id, body=message.body,
                               occurred_at=message.occurred_at) for message in self.messages]
        # A report about a message we sent: the body is the step reached (delivered, read, failed).
        events += [InboundEvent(event_key=f'{status.message_id}:{status.status}',
                                endpoint_key=config['endpoint_key'], namespace=config['namespace'],
                                kind='receipt', sender_key=status.recipient_id, thread_key=status.recipient_id,
                                message_key=status.message_id, body=status.status,
                                occurred_at=status.occurred_at) for status in self.statuses]
        return tuple(events[:100]) or (
            InboundEvent(event_key='unsupported:' + self.raw_hash, endpoint_key=config['endpoint_key'],
                         namespace=config['namespace'], kind='unsupported'),)

    # ------------------------------------------------------------------ sending

    def _payload_valid(self, payload, config):
        if not isinstance(payload, dict) or payload.get('operation') != 'template.send':
            return False
        phone = config['account_key']
        return (payload.get('account') == phone and payload.get('sender') == phone
                and config['namespace'] == phone and config['sender_key'] == phone
                and business.template_payload(recipient_number(payload.get('recipient')),
                                              payload.get('template')) is not None)

    def validate_command(self, payload, config):
        # Shape only, no network: Meta has no read-only "can this person receive it" check.
        try:
            return self._payload_valid(payload, config)
        except Exception:  # noqa: BLE001
            return False

    def dispatch(self, claim):
        config = {'account_key': claim.account_key, 'namespace': claim.namespace, 'sender_key': claim.sender_key,
                  'credential_reference': claim.credential_reference,
                  'adapter': json.loads(claim.adapter_config_json)}
        try:
            payload = json.loads(claim.payload_json)
            if not self._payload_valid(payload, config):
                return DispatchResult('definitely_not_sent', reason_code='unsupported')
            token = bundle(config)['access_token']
            version = os.environ.get('OMNI_WHATSAPP_GRAPH_VERSION')
        except Exception:  # noqa: BLE001 - nothing was sent yet
            return DispatchResult('definitely_not_sent', reason_code='unauthorized')
        outcome, detail, delay = business.send_template(
            version, claim.account_key, token, recipient_number(payload['recipient']), payload['template'])
        if outcome == 'accepted':
            return DispatchResult('accepted', provider_message_key=detail)
        if outcome == 'not_sent':
            retryable, reason = NOT_SENT.get(detail, (False, 'unsupported'))
            return DispatchResult('definitely_not_sent', retryable=retryable, retry_after=delay,
                                  reason_code=reason)
        return DispatchResult('unknown', reason_code='transport')
