"""Tools and services of a Hermes profile (ADR 0012, phase 6; approved mock 2026-11-08, boards 8 and 9).

- Hermes tools: a short list of safe Hermes toolsets, switched on or off per profile. Terminal, files, browser
  control, running code, memory, past-conversation search and messaging apps are never offered.
- Tool servers: the ERP's own server (always on) and outside MCP servers added by AI Agent managers. Their keys go
  to Hermes only.
- Scheduled jobs in Hermes: a read-back of the profile's Hermes jobs, paused and resumed from here.

Switches take effect at the next Sync to Hermes, which writes the profile's run platform (``api_server``) list.
"""

from datetime import UTC, datetime
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.translate import LazyTranslate

from ..services import hermes
from .common import internal, manager, trusted

_lt = LazyTranslate(__name__)

# Hermes toolsets offered on a profile (Hermes v0.21.3 names), with what they do.
TOOLSETS = {
    'web': ('Web search and reading', _lt('Search the public web and read web pages')),
    'vision': ('Image analysis', _lt('Describe and read images, such as a scanned form')),
    'image_gen': ('Image generation', _lt('Create images from a description')),
    'todo': ('Task planning', _lt('Keep a to-do list while working through a longer request')),
}


def hermes_time(value):
    """A Hermes ISO timestamp as a naive UTC datetime, or False."""
    if not value or not isinstance(value, str):
        return False
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return (moment.astimezone(UTC) if moment.tzinfo else moment).replace(tzinfo=None)


class ProfileTool(models.Model):
    _name = 'ai.agent.profile.tool'
    _description = 'Hermes tool of a profile'
    _order = 'sequence, id'

    profile_id = fields.Many2one('ai.agent.profile', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='profile_id.company_id', store=True, index=True)
    toolset = fields.Selection([(key, label) for key, (label, _what) in TOOLSETS.items()], string='Tool',
                               required=True, readonly=True)
    description = fields.Char(string='What it does', compute='_compute_description')
    sequence = fields.Integer(default=10)
    enabled = fields.Boolean()
    status = fields.Selection([('ready', 'Ready'), ('needs_key', 'Needs a key')], readonly=True,
                              help='As Hermes reported it at the last sync.')

    _toolset_unique = models.Constraint('UNIQUE(profile_id, toolset)', 'This tool is already on the profile.')

    @api.depends('toolset')
    def _compute_description(self):
        for tool in self:
            tool.description = str(TOOLSETS[tool.toolset][1]) if tool.toolset else False

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            manager(self)
        return super().create(vals_list)

    def write(self, vals):
        if trusted(self):
            return super().write(vals)
        if vals.keys() - {'enabled'}:
            raise AccessError(_('Only the tool switch can be changed here.'))
        _check_configure(self.profile_id)
        internal(self.sudo()).write(vals)
        self.profile_id._needs_sync()
        return True

    def unlink(self):
        if not trusted(self):
            raise AccessError(_('The tools of a profile are always listed; switch them off instead.'))
        return super().unlink()

    def action_add_key(self):
        """Keys for Hermes tools are added in Hermes (its Keys page), never in the ERP."""
        self.ensure_one()
        return self.profile_id.engine_id.sudo()._dashboard_action('/env')


class ToolServer(models.Model):
    _name = 'ai.agent.tool.server'
    _description = 'Tool server of a Hermes profile'
    _order = 'kind, name, id'  # The ERP's own server ('erp') first.

    profile_id = fields.Many2one('ai.agent.profile', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='profile_id.company_id', store=True, index=True)
    kind = fields.Selection([('erp', 'This ERP'), ('external', 'Outside service')], required=True,
                            default='external', readonly=True)
    name = fields.Char(required=True)
    hermes_name = fields.Char(string='Name in Hermes', required=True, readonly=True)
    url = fields.Char(string='Server URL', readonly=True)
    address = fields.Char(compute='_compute_address')
    auth = fields.Selection([('none', 'None'), ('key', 'Key'), ('oauth', 'Sign in in Hermes')], string='Sign-in',
                            default='none', required=True, readonly=True)
    enabled = fields.Boolean(default=True)
    status = fields.Selection([('ready', 'Ready'), ('sign_in', 'Sign in in Hermes'), ('unreachable', 'Not reachable'),
                               ('off', 'Off')], readonly=True)
    status_message = fields.Char(readonly=True)

    _hermes_name_unique = models.Constraint('UNIQUE(profile_id, hermes_name)',
                                            'Another tool server on this profile already has this name in Hermes.')

    @api.depends('kind', 'url')
    def _compute_address(self):
        for server in self:
            server.address = _('This ERP') if server.kind == 'erp' else server.url

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            manager(self)
        return super().create(vals_list)

    def write(self, vals):
        if trusted(self):
            return super().write(vals)
        if vals.keys() - {'enabled'}:
            raise AccessError(_('Only the switch of a tool server can be changed here.'))
        if any(server.kind == 'erp' for server in self):
            raise UserError(_('The ERP tools are always on.'))
        _check_configure(self.profile_id)
        internal(self.sudo()).write({**vals, 'status': False if vals['enabled'] else 'off', 'status_message': False})
        self.profile_id._needs_sync()
        return True

    def unlink(self):
        if not trusted(self):
            raise AccessError(_('Use Remove: it removes the tool server from Hermes too.'))
        return super().unlink()

    def _probe(self):
        """Ask Hermes to connect to the server and list its tools: the status to show."""
        self.ensure_one()
        profile = self.profile_id.sudo()
        try:
            result = profile.engine_id._management('POST', f'/api/mcp/servers/{self.hermes_name}/test',
                                                   query={'profile': profile.hermes_name})
        except UserError as error:
            return {'status': 'unreachable', 'status_message': str(error)}
        result = result if isinstance(result, dict) else {}
        if result.get('ok'):
            return {'status': 'ready', 'status_message': False}
        error = str(result.get('error') or '')
        if self.auth == 'oauth' and 'oauth' in error.lower():
            return {'status': 'sign_in', 'status_message': False}
        return {'status': 'unreachable', 'status_message': error[:500] or _('Hermes could not reach this server.')}

    def action_sign_in(self):
        """Outside sign-ins (OAuth) happen in Hermes, on its tool servers page."""
        self.ensure_one()
        return self.profile_id.engine_id.sudo()._dashboard_action('/mcp')

    def action_remove(self):
        """Remove an outside tool server here and in Hermes at once: AI Agent managers only."""
        manager(self.profile_id)
        for server in self:
            if server.kind == 'erp':
                raise UserError(_('The ERP tools cannot be removed.'))
            profile = server.profile_id.sudo()
            if profile.in_hermes:
                try:
                    profile.engine_id._management('DELETE', f'/api/mcp/servers/{server.hermes_name}',
                                                  query={'profile': profile.hermes_name})
                except hermes.HermesRejected as error:
                    if error.status != 404:  # 404: already gone from Hermes.
                        raise
            profile.message_post(body=_('Tool server "%s" removed.', server.name))
            internal(server.sudo()).unlink()
        return True


class ProfileJob(models.Model):
    _name = 'ai.agent.profile.job'
    _description = 'Scheduled job in Hermes'
    _order = 'name, id'

    profile_id = fields.Many2one('ai.agent.profile', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='profile_id.company_id', store=True, index=True)
    hermes_id = fields.Char(required=True, readonly=True)
    name = fields.Char(string='Job', readonly=True)
    schedule = fields.Char(string='Runs', readonly=True)
    next_run = fields.Datetime(string='Next run', readonly=True)
    last_run = fields.Datetime(string='Last run', readonly=True)
    last_result = fields.Selection([('done', 'Done'), ('failed', 'Failed')], string='Last run result', readonly=True)
    state = fields.Selection([('active', 'Active'), ('paused', 'Paused')], required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            raise AccessError(_('Scheduled jobs are read from Hermes. Scheduled work for the ERP is set up in '
                                'Workflows.'))
        return super().create(vals_list)

    def write(self, vals):
        if not trusted(self):
            raise AccessError(_('Use Pause or Resume.'))
        return super().write(vals)

    def unlink(self):
        if not trusted(self):
            raise AccessError(_('Scheduled jobs are read from Hermes.'))
        return super().unlink()

    def _act(self, verb):
        for job in self:
            _check_configure(job.profile_id)
            profile = job.profile_id.sudo()
            profile.engine_id._management('POST', f'/api/cron/jobs/{job.hermes_id}/{verb}',
                                          query={'profile': profile.hermes_name})
        self.profile_id.sudo()._refresh_jobs()
        return True

    def action_pause(self):
        return self._act('pause')

    def action_resume(self):
        return self._act('resume')


def _check_configure(profiles):
    """Department managers switch tools on their department's profile; managers on every profile."""
    profiles.check_access('read')
    if not all(p.can_configure for p in profiles):
        raise AccessError(_('Only AI Agent managers and the department\'s manager change the tools '
                            'of this profile.'))


def check_server_url(url):
    """The address of an outside tool server: http(s) with a host."""
    parts = urlsplit((url or '').strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise UserError(_('Enter the address of the tool server, starting with https://.'))
    return parts.geturl()
