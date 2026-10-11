import json
from odoo.addons.omni_channel.providers.base import HealthResult
from odoo.addons.omni_channel.providers.inbound import InboundEvent
from odoo.addons.omni_channel.providers.dispatch import DispatchResult
from . import api, vault, webhook


def bundle(config):
    scope=config['adapter']
    return vault.load(config['credential_reference'],database=scope['database'],company_id=scope['company_id'],
                      purpose_id=scope['purpose_id'],app_id=config['account_key'],tenant_id=scope['tenant_id'])


class TeamsAdapter:
    inbound_release_ready=True
    dispatch_supported=True

    def check_sender_health(self, config):
        credentials=bundle(config)
        api.token(credentials['tenant_id'],credentials['app_id'],credentials['secret'])
        good=(config['namespace']==credentials['tenant_id'] and config['sender_key']==credentials['app_id'])
        return HealthResult(good,namespace=config['namespace'],account_key=config['account_key'],sender_key=config['sender_key'])

    def check_endpoint(self, config):
        credentials=bundle(config)
        return bool(config.get('teams_callback_url') and config['endpoint_key']==credentials['app_id']
                    and config['namespace']==credentials['tenant_id'])

    def verify_request(self, raw, headers, config):
        credentials=bundle(config)
        value=webhook.authenticate(raw,headers,credentials['app_id'],credentials['tenant_id'])
        self.key,self.event=webhook.message(value)
        return True

    def normalize(self, value, config):
        base=dict(event_key=self.key,endpoint_key=config['endpoint_key'],namespace=config['namespace'])
        if self.event is None: return (InboundEvent(**base,kind='unsupported'),)
        event=self.event
        return (InboundEvent(**base,kind='message',sender_key=event['user'],thread_key=event['thread'],
                            message_key=self.key,body=event['text'],occurred_at=event['occurred']),)

    def validate_command(self, payload, config):
        credentials=bundle(config)
        if not isinstance(payload,dict): return False
        c=payload.get('conversation');body=payload.get('body')
        if (not isinstance(c,dict) or payload.get('operation')!='message.send' or not api.valid_id(payload.get('recipient'))
                or not isinstance(body,str) or not body.strip() or len(body)>4000 or '\x00' in body
                or payload.get('account')!=credentials['app_id'] or payload.get('sender')!=credentials['app_id']
                or c.get('endpoint')!=credentials['app_id'] or c.get('namespace')!=credentials['tenant_id']
                or c.get('identity')!=payload['recipient'] or c.get('app_id')!=credentials['app_id']
                or not isinstance(c.get('thread'),str) or not c['thread'].startswith('a:') or len(c['thread'])>256
                or not isinstance(c.get('member_id'),str) or not c['member_id'].startswith('29:') or len(c['member_id'])>256): return False
        api.service_url(c.get('service_url'))
        return True

    def dispatch(self, claim):
        config={'account_key':claim.account_key,'namespace':claim.namespace,'sender_key':claim.sender_key,
                'credential_reference':claim.credential_reference,'adapter':json.loads(claim.adapter_config_json)}
        payload=json.loads(claim.payload_json)
        if not self.validate_command(payload,config): return DispatchResult('definitely_not_sent',reason_code='invalid_recipient')
        state,key=api.send_text(bundle(config),payload['conversation'],payload['body'])
        return DispatchResult({'accepted':'accepted','failed':'definitely_not_sent','unknown':'unknown'}[state],
            provider_message_key=key if state=='accepted' else '',reason_code='' if state=='accepted' else 'transport')
