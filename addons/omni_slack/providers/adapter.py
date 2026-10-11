from odoo.addons.omni_channel.providers.base import HealthResult
from odoo.addons.omni_channel.providers.inbound import InboundEvent
from . import api, vault, webhook

def bundle(config):
    scope = config['adapter']
    return vault.load(config['credential_reference'], database=scope['database'],
        company_id=scope['company_id'], purpose_id=scope['purpose_id'],
        bot_id=config['account_key'], workspace_id=scope['workspace_id'])

class SlackAdapter:
    inbound_release_ready = True
    dispatch_supported = True

    def check_sender_health(self, config):
        credentials = bundle(config)
        profile = api.verify(credentials['token'])
        good = (config['namespace'] == credentials['workspace_id'] and config['account_key'] == credentials['bot_id']
                and profile['team_id'] == credentials['workspace_id'] and profile['bot_id'] == credentials['bot_id']
                and profile['user_id'] == credentials['user_id'] and config['sender_key'] == credentials['bot_id'])
        return HealthResult(good, namespace=config['namespace'], account_key=config['account_key'], sender_key=config['sender_key'])

    def check_endpoint(self, config):
        credentials = bundle(config)
        return bool(config.get('slack_verified') and credentials['signing_secret']
            and config['endpoint_key'] == credentials['bot_id'] and config['namespace'] == credentials['workspace_id'])

    def verify_request(self, raw, headers, config):
        credentials = bundle(config)
        value = webhook.authenticated(raw, headers, credentials['signing_secret'])
        self.key, self.event = webhook.message(value, credentials['workspace_id'], credentials['app_id'])
        return True

    def normalize(self, value, config):
        base = dict(event_key=self.key, endpoint_key=config['endpoint_key'], namespace=config['namespace'])
        if self.event is None:
            return (InboundEvent(**base, kind='unsupported'),)
        event = self.event
        return (InboundEvent(**base, kind='message', sender_key=event['user'], thread_key=event['channel'],
                message_key=event['stamp'], body=event['text'], occurred_at=event['occurred']),)

    def validate_command(self, payload, config):
        credentials = bundle(config)
        conversation = payload.get('conversation', {}) if isinstance(payload, dict) else {}
        recipient = payload.get('recipient') if isinstance(payload, dict) else None
        body = payload.get('body') if isinstance(payload, dict) else None
        if (not isinstance(conversation, dict) or payload.get('operation') != 'message.send'
                or not api.valid_id(recipient, 'U') or not api.valid_id(conversation.get('thread'), 'D')
                or not isinstance(body, str) or not body.strip() or len(body) > 4000 or '\x00' in body
                or payload.get('account') != credentials['bot_id'] or payload.get('sender') != credentials['bot_id']
                or conversation.get('endpoint') != credentials['bot_id']
                or conversation.get('namespace') != credentials['workspace_id'] or conversation.get('identity') != recipient):
            return False
        data = api.call('conversations.info', credentials['token'], {'channel': conversation['thread']})
        channel = data.get('channel', {})
        return bool(data.get('ok') is True and isinstance(channel, dict)
                    and channel.get('id') == conversation['thread'] and channel.get('is_im') is True
                    and channel.get('user') == recipient)

    def dispatch(self, claim):
        import json
        from odoo.addons.omni_channel.providers.dispatch import DispatchResult
        config = {'account_key': claim.account_key, 'namespace': claim.namespace, 'sender_key': claim.sender_key,
                  'credential_reference': claim.credential_reference, 'adapter': json.loads(claim.adapter_config_json)}
        # Repeat the read-only recipient binding at the execution boundary.
        payload = json.loads(claim.payload_json)
        if not self.validate_command(payload, config):
            return DispatchResult('definitely_not_sent', reason_code='invalid_recipient')
        credentials = bundle(config)
        state, detail = api.send_text(credentials['token'], payload['conversation']['thread'], payload['body'])
        return DispatchResult({'accepted':'accepted','failed':'definitely_not_sent','unknown':'unknown'}[state],
                              provider_message_key=detail if state == 'accepted' else '',
                              reason_code='' if state == 'accepted' else 'transport')
