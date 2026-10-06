"""Read-only, aggregate operations snapshot for a trusted Odoo shell.

No provider calls, notifications, record identifiers, recipients or message content.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError


def collect(env):
    if not env.su:
        message = 'Operations snapshot requires a trusted administrator shell.'
        raise AccessError(message)
    now = fields.Datetime.now()
    old = now - timedelta(minutes=5)
    commands = env['omni.command']
    events = env['omni.webhook.event']
    counts = {
        'unknown_outcomes': commands.search_count([('state', '=', 'unknown')]),
        'expired_worker_leases': commands.search_count([
            ('state', '=', 'dispatching'), ('lease_expires_at', '<=', now),
        ]),
        'queued_older_than_five_minutes': commands.search_count([
            ('state', '=', 'queued'), ('write_date', '<=', old),
        ]),
        'inbox_older_than_five_minutes': events.search_count([
            ('state', 'in', ['received', 'retry']), ('create_date', '<=', old),
        ]),
        'dead_letters': events.search_count([('state', '=', 'dead')]),
        'unresolved_events': events.search_count([('state', '=', 'unresolved')]),
        'open_circuit_breakers': env['omni.channel'].search_count([
            ('failure_count', '>=', 5), ('dispatch_enabled', '=', False),
        ]),
        'selected_unhealthy_senders': env['omni.outbound.sender'].search_count([
            ('is_selected', '=', True), ('health', '=', 'unhealthy'),
        ]),
    }
    critical = ['unknown_outcomes', 'expired_worker_leases', 'open_circuit_breakers']
    severity = 'critical' if any(counts[key] for key in critical) else (
        'warning' if any(counts.values()) else 'ok'
    )
    return {'schema_version': 1, 'checked_at': fields.Datetime.to_string(now),
            'severity': severity, 'counts': counts,
            'scope': 'all Omni companies; restricted infrastructure output'}
