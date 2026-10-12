import hashlib
import json

from odoo import _
from odoo.exceptions import AccessError

TOKEN = object()


def internal(records):
    return records.with_context(_ai_agent_token=TOKEN)


def trusted(records):
    return records.env.context.get('_ai_agent_token') is TOKEN


def manager(records):
    if not records.env.user.has_group('ai_agent.group_manager'):
        raise AccessError(_('Only AI Agent managers can configure assistants.'))
    records.check_access('write' if records else 'create')
    if records and any(r.company_id not in records.env.companies for r in records):
        raise AccessError(_('Select the authorized company first.'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
