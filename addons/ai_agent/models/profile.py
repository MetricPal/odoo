"""Hermes profiles managed from Odoo (ADR 0012, phase 2).

One profile per department, one company profile, and optionally one for a single agent. Odoo creates the profile
through the Hermes management API, keeps memory and toolsets off, writes its persona and default model, gives it its
own run key, and checks that the multiplexing gateway serves it at ``/p/<name>``. Agents send their own instructions
and model with each run, so several agents share a profile.
"""

import json
import re
import secrets as token_generator
import unicodedata

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services import hermes, secrets
from .common import internal, manager, trusted

PROFILE_NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')
DEFAULT_PERSONA = ('You are an assistant of {company}. You help people at work, you state uncertainty, and you never '
                   'claim to have changed anything: you prepare drafts and proposals for a person to approve.')
# Memory and every Hermes toolset stay off on Odoo profiles; Odoo's own tools come in phase 3.
SAFE_CONFIG = {'memory': {'memory_enabled': False, 'user_profile_enabled': False, 'provider': ''},
               'platform_toolsets': {'api_server': [], 'cli': [], 'dashboard': []}}
# What department managers and AI admins may change on their department's profile.
DEPARTMENT_PROFILE_FIELDS = {'persona', 'engine_model_id'}


def profile_name(text):
    """``odoo-`` plus a Hermes-safe version of *text* (lowercase letters, digits, '-')."""
    ascii_text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_text.lower()).strip('-') or 'profile'
    return f'odoo-{slug}'[:64].rstrip('-_')


class Profile(models.Model):
    _name = 'ai.agent.profile'
    _description = 'Hermes profile'
    _inherit = ['mail.thread']
    _order = 'kind, name'

    name = fields.Char(required=True, tracking=True)
    hermes_name = fields.Char(string='Name in Hermes', required=True, copy=False, tracking=True,
                              help='Lowercase letters, digits, "-" or "_". Fixed once the profile exists in Hermes.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    engine_id = fields.Many2one('ai.agent.engine', string='Hermes connection', required=True, ondelete='restrict',
                                check_company=True)
    kind = fields.Selection([('company', 'Company'), ('department', 'Department'), ('agent', 'One agent')],
                            required=True, default='department')
    department_id = fields.Many2one('hr.department', check_company=True, index='btree_not_null')
    persona = fields.Text(tracking=True, help='Shared by every agent on this profile. Agents add their own '
                                              'instructions.')
    engine_model_id = fields.Many2one('ai.agent.engine.model', string='Default model', ondelete='restrict',
                                      check_company=True, domain="[('engine_id', '=', engine_id), ('enabled', '=', True)]")
    state = fields.Selection([('draft', 'Not created'), ('needs_sync', 'Needs sync'), ('in_sync', 'In sync'),
                              ('failed', 'Failed')], default='draft', required=True, readonly=True, tracking=True)
    synced_at = fields.Datetime(string='Last synced', readonly=True)
    sync_message = fields.Char(readonly=True)
    secret_reference = fields.Char(default='AI_AGENT_SECRET_UNSET', groups=fields.NO_ACCESS, copy=False)
    agent_ids = fields.One2many('ai.agent', 'profile_id', string='Agents')
    assistant_user_id = fields.Many2one('res.users', string='Acts as', compute='_compute_assistant_user_id')
    can_configure = fields.Boolean(compute='_compute_can_configure', search='_search_can_configure')
    can_manage = fields.Boolean(compute='_compute_can_configure')

    _hermes_name_unique = models.Constraint('UNIQUE(engine_id, hermes_name)',
                                            'Another profile on this connection already has this name in Hermes.')

    @api.constrains('hermes_name', 'kind', 'department_id')
    def _check_profile(self):
        for profile in self:
            if not PROFILE_NAME.fullmatch(profile.hermes_name or '') or not profile.hermes_name.startswith('odoo-'):
                raise ValidationError(_('The name in Hermes starts with "odoo-" and uses lowercase letters, digits, '
                                        '"-" or "_" (at most 64).'))
            if profile.kind == 'department' and not profile.department_id:
                raise ValidationError(_('Choose the department of this profile.'))

    @api.depends('kind', 'department_id.ai_assistant_user_id', 'company_id.ai_assistant_user_id', 'agent_ids')
    def _compute_assistant_user_id(self):
        for profile in self:
            source = profile.sudo()
            if source.kind == 'company':
                user = source.company_id.ai_assistant_user_id
            elif source.kind == 'department':
                user = source.department_id.ai_assistant_user_id
            else:
                user = source.agent_ids[:1].department_id.ai_assistant_user_id
            profile.assistant_user_id = user.id

    def _is_manager(self):
        return self.env.user.has_group('ai_agent.group_manager')

    @api.depends_context('uid')
    def _compute_can_configure(self):
        is_manager = self._is_manager()
        managed = set() if is_manager else set(self.env.user._ai_admin_department_ids())
        for profile in self:
            profile.can_manage = is_manager
            profile.can_configure = is_manager or (profile.kind == 'department'
                                                   and profile.sudo().department_id.id in managed)

    def _search_can_configure(self, operator, value):
        if operator not in ('=', 'in') or value not in (True, [True], {True}):
            return NotImplemented
        if self._is_manager():
            return []
        return [('kind', '=', 'department'), ('department_id', 'in', self.env.user._ai_admin_department_ids())]

    # -- writing -------------------------------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            manager(self)
        for vals in vals_list:
            if not vals.get('hermes_name'):
                vals['hermes_name'] = profile_name(vals.get('name'))
        profiles = super().create(vals_list)
        profiles._reassign_agents()
        return profiles

    def _reassign_agents(self):
        agents = self.env['ai.agent'].sudo().with_context(active_test=False).search(
            [('engine_id', 'in', self.engine_id.ids)])
        agents._assign_profiles()

    def write(self, vals):
        if trusted(self):
            return super().write(vals)
        if {'state', 'synced_at', 'sync_message', 'secret_reference'} & vals.keys():
            raise AccessError(_('Use Sync to Hermes.'))
        if 'hermes_name' in vals and any(p.state != 'draft' for p in self):
            raise UserError(_('The name in Hermes is fixed once the profile exists there.'))
        if not self._is_manager():
            if vals.keys() - DEPARTMENT_PROFILE_FIELDS or not all(p.can_configure for p in self):
                raise AccessError(_('Department managers and AI admins change the persona and default model of '
                                    'their department\'s profile. Ask an AI Agent manager for anything else.'))
            self.check_access('read')
            internal(self.sudo()).write(vals)
        else:
            manager(self)
            super().write(vals)
        if 'active' in vals:
            self._reassign_agents()
        # A change waits for the next sync; the profile in Hermes keeps working meanwhile.
        if vals.keys() & {'persona', 'engine_model_id', 'name'}:
            internal(self.sudo().filtered(lambda p: p.state == 'in_sync')).write({'state': 'needs_sync'})
        return True

    def unlink(self):
        manager(self)
        if any(p.state != 'draft' for p in self):
            raise UserError(_('Remove the profile from Hermes first, or archive it.'))
        return super().unlink()

    # -- the run key -------------------------------------------------------------------------------------------
    def _binding(self):
        return {'database': self.env.cr.dbname, 'engine_id': self.engine_id.id, 'company_id': self.company_id.id,
                'purpose': f'profile:{self.hermes_name}', 'url': self.engine_id.url}

    def _run_key(self):
        self.ensure_one()
        reference = self.sudo().secret_reference
        if not (reference or '').startswith(secrets.PREFIX):
            raise UserError(_('Sync the Hermes profile "%s" first.', self.name))
        try:
            bundle = json.loads(secrets.load(reference, self.env.cr.dbname))
            if any(bundle.get(k) != v for k, v in self._binding().items()):
                raise ValueError('credential binding mismatch')
            return bundle['token']
        except Exception:
            raise UserError(_('The key of the Hermes profile "%s" does not match. Sync it again.', self.name)) from None

    # -- sync --------------------------------------------------------------------------------------------------
    def _persona_text(self):
        return (self.persona or '').strip() or DEFAULT_PERSONA.format(company=self.company_id.name)

    def _sync(self):
        """Create or update the profile in Hermes and check that the gateway serves it."""
        self.ensure_one()
        engine = self.engine_id.sudo()
        name = self.hermes_name
        listing = engine._management('GET', '/api/profiles')
        existing = {p.get('name') for p in (listing or {}).get('profiles', []) if isinstance(p, dict)}
        if name not in existing:
            engine._management('POST', '/api/profiles', {'name': name, 'description': self.name, 'no_skills': True})
        engine._management('PUT', '/api/config', {'config': SAFE_CONFIG}, query={'profile': name})
        engine._management('PUT', f'/api/profiles/{name}/soul', {'content': self._persona_text()})
        option = self.sudo().engine_model_id
        if option:
            engine._management('PUT', f'/api/profiles/{name}/model', {'provider': option.provider, 'model': option.model})
        reference = self.sudo().secret_reference
        if not (reference or '').startswith(secrets.PREFIX):
            key = token_generator.token_hex(32)
            engine._management('PUT', '/api/env', {'key': 'API_SERVER_KEY', 'value': key}, query={'profile': name})
            try:
                reference = secrets.store({**self._binding(), 'token': key})
            except (ValueError, OSError):
                raise UserError(_('The profile key could not be saved securely. Ask your system administrator to '
                                  'check private credential storage.')) from None
            internal(self.sudo()).write({'secret_reference': reference})
        # Read back: memory off, toolsets off, and the gateway serves the profile with its own key.
        config = engine._management('GET', '/api/config', query={'profile': name})
        memory = config.get('memory', {}) if isinstance(config, dict) else {}
        if memory.get('memory_enabled') is not False or memory.get('user_profile_enabled') is not False:
            raise UserError(_('Hermes did not keep memory off on this profile.'))
        try:
            capabilities = engine._request('GET', '/v1/capabilities', profile=self)
        except UserError:
            raise UserError(_('The Hermes gateway does not serve this profile. Turn on multiplexing on the Hermes '
                              'connection (gateway.multiplex_profiles) and restart its gateway.')) from None
        features = capabilities.get('features', {}) if isinstance(capabilities, dict) else {}
        if not features.get('run_submission') or not features.get('run_status'):
            raise UserError(_('This Hermes version does not support durable runs.'))

    def action_sync(self):
        """Sync to Hermes: managers, and department managers and AI admins for their department's profile."""
        for profile in self:
            if not profile.can_configure:
                raise AccessError(_('Only AI Agent managers and the department\'s managers and AI admins sync it.'))
            if profile.engine_id.sudo().state != 'ready':
                raise UserError(_('Check the Hermes connection first.'))
            try:
                profile._sync()
                values = {'state': 'in_sync', 'sync_message': _('In sync with Hermes.')}
            except UserError as error:
                values = {'state': 'failed', 'sync_message': str(error)}
            internal(profile.sudo()).write({**values, 'synced_at': fields.Datetime.now()})
        return True

    def action_create_company_assistant(self):
        self.ensure_one()
        self.company_id._ai_create_company_assistant()
        return True

    def action_create_department_assistant(self):
        self.ensure_one()
        self.department_id.action_create_ai_assistant()
        return True

    def action_remove_from_hermes(self):
        manager(self)
        for profile in self:
            if profile.agent_ids.filtered(lambda a: a.state == 'active'):
                raise UserError(_('Pause the agents that use this profile first.'))
            if profile.state != 'draft':
                profile.engine_id.sudo()._management('DELETE', f'/api/profiles/{profile.hermes_name}')
            reference = profile.sudo().secret_reference
            if (reference or '').startswith(secrets.PREFIX):
                secrets.remove(reference, self.env.cr.dbname)
            internal(profile.sudo()).write({'state': 'draft', 'secret_reference': 'AI_AGENT_SECRET_UNSET',
                                            'sync_message': _('Removed from Hermes.'), 'active': False})
        self._reassign_agents()
        return True
