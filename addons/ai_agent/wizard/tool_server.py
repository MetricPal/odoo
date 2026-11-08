from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.common import internal, manager
from ..models.profile import LEGACY_MCP_SERVERS, MCP_SERVER, profile_name
from ..models.profile_tools import check_server_url

# Hermes's sign-in mode for each choice.
HERMES_AUTH = {'none': 'none', 'key': 'header', 'oauth': 'oauth'}


class AddToolServer(models.TransientModel):
    """Add a tool server (approved mock 2026-11-08, board 9). The key goes to Hermes only: it is a field that is
    never stored, handed to the button in its context."""

    _name = 'ai.agent.tool.server.add'
    _description = 'Add a tool server'

    profile_id = fields.Many2one('ai.agent.profile', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    url = fields.Char(string='Address', required=True)
    auth = fields.Selection([('none', 'None'), ('key', 'Key'), ('oauth', 'Sign in in Hermes')], string='Sign-in',
                            default='none', required=True)
    key = fields.Char(store=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.pop('key', None)  # Never stored, even on the wizard.
        return super().create(vals_list)

    def action_add(self):
        self.ensure_one()
        profile = self.profile_id
        manager(profile)
        if not profile.in_hermes:
            raise UserError(_('Sync the profile to Hermes first.'))
        url = check_server_url(self.url)
        key = (self.env.context.get('tool_server_key') or '').strip()
        if self.auth == 'key' and not key:
            raise UserError(_('Enter the key of the tool server.'))
        engine = profile.engine_id.sudo()
        listing = engine._management('GET', '/api/mcp/servers', query={'profile': profile.hermes_name})
        servers = listing if isinstance(listing, list) else (listing or {}).get('servers', [])
        taken = {s.get('name') for s in servers if isinstance(s, dict)} | set(profile.sudo().server_ids.mapped(
            'hermes_name')) | {MCP_SERVER, *LEGACY_MCP_SERVERS}
        hermes_name = profile_name(self.name, taken)
        payload = {'name': hermes_name, 'url': url, 'auth': HERMES_AUTH[self.auth]}
        if self.auth == 'key':
            payload['bearer_token'] = key
        engine._management('POST', '/api/mcp/servers', payload, query={'profile': profile.hermes_name})
        server = internal(self.env['ai.agent.tool.server'].sudo()).create({
            'profile_id': profile.id, 'name': self.name, 'hermes_name': hermes_name, 'url': url, 'auth': self.auth})
        internal(server).write(server._probe())
        profile.sudo().message_post(body=_('Tool server "%(name)s" added (%(url)s).', name=self.name, url=url))
        profile._needs_sync()
        if self.auth == 'oauth':
            return server.action_sign_in() | {'close': True}
        return {'type': 'ir.actions.act_window_close'}
