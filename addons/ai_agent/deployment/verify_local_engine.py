"""Read-only live Hermes verification in the disposable Odoo database.

Creates only test-database configuration. No inference request is submitted.
"""
import os
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

os.environ['AI_AGENT_ENDPOINTS'] = '127.0.0.1:8643,127.0.0.1:9120'
for line in Path('/mnt/agent/profiles/odoo-internal/.env').read_text().splitlines():
    key, sep, value = line.partition('=')
    if sep and key in ('AI_AGENT_SECRET_ODOO_RUN', 'AI_AGENT_SECRET_ODOO_MANAGEMENT'):
        os.environ[key] = shlex.split(value)[0]

from odoo import api, SUPERUSER_ID, Command
from odoo.orm.registry import Registry
from odoo.tools import config
config.parse_config(['--db_host=/tmp/ai-agent-socket', '--db_port=55439', '--db_user=moshkou',
                     '--addons-path=addons', '--data-dir=/tmp/ai-agent-data'], setup_logging=False)
with Registry('ai_agent_test').cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    engine = env['ai.agent.engine'].search([('name', '=', 'Local isolated Hermes')], limit=1)
    if not engine:
        engine = env['ai.agent.engine'].create({'name': 'Local isolated Hermes',
            'url': 'http://127.0.0.1:8643', 'secret_reference': 'AI_AGENT_SECRET_ODOO_RUN',
            'management_url': 'http://127.0.0.1:9120',
            'management_secret_reference': 'AI_AGENT_SECRET_ODOO_MANAGEMENT'})
    engine.action_check()
    print('Live engine readiness:', engine.state)
    print('Readiness summary:', engine.status_message)
    print('Enabled callable toolsets:', sum(bool(t.get('enabled') and t.get('tools')) for t in (engine.toolsets or [])))
    if engine.state != 'ready':
        cr.rollback()
        raise SystemExit('Live verification blocked; no configuration committed.')
    cr.commit()
    print('Verified configuration committed only in ai_agent_test. No inference was requested.')
