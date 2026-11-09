"""Hermes profiles managed from Odoo (ADR 0012, phase 2).

One profile per department, one company profile, and optionally one for a single agent. Odoo creates the profile
through the Hermes management API, keeps memory off and only the tools switched on here (phase 6), writes its persona
and default model, gives it its own run key, and checks that the multiplexing gateway serves it at ``/p/<name>``.
Agents send their own instructions and model with each run, so several agents share a profile.
"""

import json
import re
import secrets as token_generator
import shlex
import time
import unicodedata

from odoo import Command, _, api, fields, models
from odoo.modules import module as odoo_module
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services import hermes, secrets
from .common import internal, manager, trusted
from .profile_tools import TOOLSETS, hermes_time

PROFILE_NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')
DEFAULT_PERSONA = ('You are an assistant of {company}. You help people at work, you state uncertainty, and you never '
                   'claim to have changed anything: you prepare drafts and proposals for a person to approve.')
# Memory stays off on these profiles. Runs through the API server get the ERP's own tools (the MCP server named "erp")
# plus the Hermes tools and outside tool servers switched on in the profile's Tools and services tab; the command
# line and dashboard get nothing. Profiles synced before were given the server "odoo": the next sync replaces it.
MCP_SERVER = 'erp'
LEGACY_MCP_SERVERS = ('odoo',)
# Names Hermes keeps for itself or refuses (Hermes v0.21.3, hermes_cli/profiles.py); never used here.
RESERVED_NAMES = {'default', 'hermes', 'test', 'tmp', 'root', 'sudo'}
SAFE_CONFIG = {'memory': {'memory_enabled': False, 'user_profile_enabled': False, 'provider': ''},
               'platform_toolsets': {'api_server': [MCP_SERVER], 'cli': [], 'dashboard': []}}
# Provider keys (``*_API_KEY``) live once, in the main Hermes profile's .env. Each ERP profile reads them from there
# through a Hermes command secret source, never as copies; the gateway key and the dashboard token are not shared,
# and a profile's own .env value still wins (Hermes: website/docs/user-guide/secrets/command.md).
SHARED_KEYS_COMMAND = "grep -E '^[A-Z0-9_]+_API_KEY=' {env} | grep -v '^API_SERVER_KEY='"

# Sync asks the profile's model one tiny question and waits this long for the answer (owner, 2026-11-09).
MODEL_TEST_PROMPT = 'Reply with the single word: OK'
MODEL_TEST_SECONDS = 30

# What department managers may change on their department's profile.
DEPARTMENT_PROFILE_FIELDS = {'persona', 'engine_model_id'}


def profile_name(text, taken=()):
    """A Hermes-safe version of *text* (lowercase letters, digits, '-'), with a number added when it is *taken*."""
    ascii_text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_text.lower()).strip('-')[:60].rstrip('-') or 'profile'
    taken = set(taken) | RESERVED_NAMES
    name, number = slug, 1
    while name in taken:
        number += 1
        name = f'{slug}-{number}'
    return name


class Profile(models.Model):
    _name = 'ai.agent.profile'
    _description = 'Hermes profile'
    _inherit = ['mail.thread']
    _order = 'kind, name'

    name = fields.Char(required=True, tracking=True)
    hermes_name = fields.Char(string='Name in Hermes', required=True, copy=False, readonly=True,
                              help='Made from the name. Fixed once the profile exists in Hermes.')
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
    in_hermes = fields.Boolean(readonly=True, copy=False, help='The profile was created in Hermes from here.')
    sync_message = fields.Char(readonly=True)
    secret_reference = fields.Char(default='AI_AGENT_SECRET_UNSET', groups=fields.NO_ACCESS, copy=False)
    mcp_token_hash = fields.Char(groups=fields.NO_ACCESS, copy=False, index='btree_not_null',
                                 help='Hash of the bearer token Hermes uses for this profile on the tools endpoint.')
    agent_ids = fields.One2many('ai.agent', 'profile_id', string='Agents')
    tool_ids = fields.One2many('ai.agent.profile.tool', 'profile_id', string='Hermes tools')
    server_ids = fields.One2many('ai.agent.tool.server', 'profile_id', string='Tool servers')
    job_ids = fields.One2many('ai.agent.profile.job', 'profile_id', string='Scheduled jobs in Hermes')
    assistant_user_id = fields.Many2one('res.users', string='Acts as', compute='_compute_assistant_user_id')
    can_configure = fields.Boolean(compute='_compute_can_configure', search='_search_can_configure')
    can_manage = fields.Boolean(compute='_compute_can_configure')

    _hermes_name_unique = models.Constraint('UNIQUE(engine_id, hermes_name)',
                                            'Another profile on this connection already has this name in Hermes.')

    @api.constrains('hermes_name', 'kind', 'department_id')
    def _check_profile(self):
        for profile in self:
            if not PROFILE_NAME.fullmatch(profile.hermes_name or ''):
                # Names are always made here (profile_name); this only guards against a programming error.
                raise ValidationError(_('This profile has no valid name in Hermes.'))
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
            # The name in Hermes is always made from the name; nobody types it.
            engine_id = vals.get('engine_id')
            vals['hermes_name'] = profile_name(vals.get('name'), self._names_taken(engine_id) | {
                v.get('hermes_name') for v in vals_list if v is not vals and v.get('engine_id') == engine_id})
        profiles = super().create(vals_list)
        profiles._ensure_assistant_users()
        profiles._ensure_tools()
        profiles._reassign_agents()
        return profiles

    def _ensure_assistant_users(self):
        """A department's (or the company's) Hermes profile comes with its AI assistant user (owner, 2026-11-09)."""
        self.filtered(lambda p: p.kind == 'company').company_id._ai_ensure_company_assistant()
        self.filtered(lambda p: p.kind in ('department', 'agent')).department_id._ai_ensure_assistant()

    def _ensure_tools(self):
        """Every offered Hermes tool (off until switched on) and the ERP's own tool server on each profile."""
        for profile in self.sudo():
            have = set(profile.tool_ids.mapped('toolset'))
            internal(self.env['ai.agent.profile.tool'].sudo()).create([
                {'profile_id': profile.id, 'toolset': key, 'sequence': index}
                for index, key in enumerate(TOOLSETS) if key not in have])
            if not profile.server_ids.filtered(lambda s: s.kind == 'erp'):
                internal(self.env['ai.agent.tool.server'].sudo()).create({
                    'profile_id': profile.id, 'kind': 'erp', 'name': 'ERP', 'hermes_name': MCP_SERVER})

    def _needs_sync(self):
        """A change waits for the next sync; the profile in Hermes keeps working meanwhile."""
        internal(self.sudo().filtered(lambda p: p.state == 'in_sync')).write({'state': 'needs_sync'})

    def _names_taken(self, engine_id, hermes=()):
        """Names in Hermes already used on this connection: by other profiles here, and in Hermes itself."""
        others = self.sudo().with_context(active_test=False).search(
            [('engine_id', '=', engine_id), ('id', 'not in', self.ids)])
        return set(others.mapped('hermes_name')) | set(hermes)

    def _reassign_agents(self):
        agents = self.env['ai.agent'].sudo().with_context(active_test=False).search(
            [('engine_id', 'in', self.engine_id.ids)])
        agents._assign_profiles()

    def write(self, vals):
        if trusted(self):
            return super().write(vals)
        vals = self._write_switches(vals)
        if not vals:
            return True
        if {'state', 'synced_at', 'sync_message', 'secret_reference'} & vals.keys():
            raise AccessError(_('Use Sync to Hermes.'))
        if 'hermes_name' in vals:
            raise AccessError(_('The name in Hermes is made from the name.'))
        if not self._is_manager():
            if vals.keys() - DEPARTMENT_PROFILE_FIELDS or not all(p.can_configure for p in self):
                raise AccessError(_('Department managers change the persona and default model of '
                                    'their department\'s profile. Ask an AI Agent manager for anything else.'))
            self.check_access('read')
            internal(self.sudo()).write(vals)
        else:
            manager(self)
            super().write(vals)
        if 'name' in vals:
            # Until the profile exists in Hermes, its name there follows the name.
            for profile in self.sudo().filtered(lambda p: not p.in_hermes):
                internal(profile).write({'hermes_name': profile_name(
                    profile.name, profile._names_taken(profile.engine_id.id))})
        if 'active' in vals:
            self._reassign_agents()
        if vals.keys() & {'kind', 'department_id', 'company_id'}:
            self._ensure_assistant_users()
        if vals.keys() & {'persona', 'engine_model_id', 'name'}:
            self._needs_sync()
        return True

    def _write_switches(self, vals):
        """The Tools and services tab saves its switches through the profile: apply them on the tools and tool
        servers themselves (which check who may change them). Nothing else is changed there."""
        vals = dict(vals)
        for field, model in (('tool_ids', 'ai.agent.profile.tool'), ('server_ids', 'ai.agent.tool.server')):
            for command in vals.pop(field, None) or ():
                if command[0] == Command.UPDATE and set(command[2]) <= {'enabled'}:
                    line = self.env[model].browse(command[1])
                    if line.profile_id not in self:
                        raise AccessError(_('This line belongs to another profile.'))
                    line.write(command[2])
                elif command[0] != Command.LINK:
                    raise AccessError(_('Only the switches of the tools and tool servers are changed here.'))
        vals.pop('job_ids', None)
        return vals

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

    # Steps shown while Sync to Hermes runs (approved mock 2026-11-08, board 15).
    def _sync_steps(self):
        return [_('Profile created in Hermes'), _('Persona and model written'), _('Keys and ERP tools set up'),
                _('Gateway serves the profile'), _('Tools and scheduled jobs read back'),
                _('Testing the model %s', self._model_label()) if self.sudo().engine_model_id
                else _("Testing the connection's default model")]

    def _sync_progress(self, step, state='running'):
        """Tell the person syncing which step is running, at once: the sync is one transaction, so the
        notification is sent from its own short transaction (in tests, the test transaction)."""
        steps = self._sync_steps()
        payload = {'profile_id': self.id, 'step': step, 'total': len(steps), 'steps': steps, 'state': state}
        if odoo_module.current_test:
            self.env.user._bus_send('ai_agent/sync_progress', payload)
            return
        with self.env.registry.cursor() as cr:
            api.Environment(cr, self.env.uid, {}).user._bus_send('ai_agent/sync_progress', payload)

    def _sync(self):
        """Create or update the profile in Hermes and check that the gateway serves it."""
        self.ensure_one()
        self._sync_progress(1)
        engine = self.engine_id.sudo()
        listing = engine._management('GET', '/api/profiles')
        rows = [p for p in (listing or {}).get('profiles', []) if isinstance(p, dict)]
        existing = {p.get('name') for p in rows}
        main_home = next((p.get('path') for p in rows if p.get('is_default') and p.get('path')), None)
        if not self.in_hermes and self.hermes_name in existing:
            # A profile of that name was made in Hermes by someone else: never take it over, use the next free name.
            internal(self.sudo()).write({'hermes_name': profile_name(
                self.name, self._names_taken(self.engine_id.id, existing))})
        name = self.hermes_name
        if name not in existing:
            engine._management('POST', '/api/profiles', {'name': name, 'description': self.name, 'no_skills': True})
        if not self.in_hermes:
            internal(self.sudo()).write({'in_hermes': True})
        self._sync_progress(2)
        engine._management('PUT', '/api/config', {'config': self._safe_config(main_home)}, query={'profile': name})
        engine._management('PUT', f'/api/profiles/{name}/soul', {'content': self._persona_text()})
        option = self.sudo().engine_model_id
        if option:
            engine._management('PUT', f'/api/profiles/{name}/model', {'provider': option.provider, 'model': option.model})
        else:
            # No model of its own: the connection's default model.
            _providers, default = engine._provider_options()
            if default['provider'] and default['model']:
                engine._management('PUT', f'/api/profiles/{name}/model',
                                   {'provider': default['provider'], 'model': default['model']})
        self._sync_progress(3)
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
        self._sync_mcp()
        # Read back: memory off, the tools' and tool servers' state, and the gateway serves the profile with its key.
        config = engine._management('GET', '/api/config', query={'profile': name})
        memory = config.get('memory', {}) if isinstance(config, dict) else {}
        if memory.get('memory_enabled') is not False or memory.get('user_profile_enabled') is not False:
            raise UserError(_('Hermes did not keep memory off on this profile.'))
        self._sync_progress(4)
        try:
            capabilities = engine._request('GET', '/v1/capabilities', profile=self)
        except UserError:
            raise UserError(_('The Hermes gateway does not serve this profile. Turn on multiplexing on the Hermes '
                              'connection (gateway.multiplex_profiles) and restart its gateway.')) from None
        features = capabilities.get('features', {}) if isinstance(capabilities, dict) else {}
        if not features.get('run_submission') or not features.get('run_status'):
            raise UserError(_('This Hermes version does not support durable runs.'))
        self._sync_progress(5)
        self._refresh_tools()
        self._refresh_jobs()
        self._sync_progress(6)
        self._test_model()

    def _model_label(self):
        option = self.sudo().engine_model_id
        if option:
            return f'{option.provider} / {option.model}'
        return _('the connection default model')

    def _test_model(self):
        """Ask the profile's model one tiny question through the gateway, as an agent run would: a model that does
        not answer (retired, no quota, key refused) fails the sync with the provider's reason."""
        self.ensure_one()
        engine = self.engine_id.sudo()
        label = self._model_label()
        try:
            started = engine._request('POST', '/v1/runs', {'input': MODEL_TEST_PROMPT}, profile=self)
        except hermes.HermesRejected as error:
            if error.status == 429:
                return  # Hermes is busy with other questions: the model is not tested this time.
            raise
        run_id = (started or {}).get('run_id') if isinstance(started, dict) else None
        if not run_id:
            raise UserError(_('Hermes did not start a test question for %s.', label))
        deadline = time.monotonic() + MODEL_TEST_SECONDS
        while True:
            result = engine._request('GET', f'/v1/runs/{run_id}', profile=self)
            status = result.get('status') if isinstance(result, dict) else None
            if status == 'completed':
                return
            if status in ('failed', 'cancelled', 'interrupted'):
                reason = result.get('error')
                reason = reason.get('message') if isinstance(reason, dict) else reason
                raise UserError(_('The model %(model)s does not answer: %(reason)s', model=label,
                                  reason=(reason or _('no reason given')).strip()[:500]))
            if time.monotonic() >= deadline:
                try:
                    engine._request('POST', f'/v1/runs/{run_id}/stop', {}, profile=self)
                except UserError:
                    pass
                raise UserError(_('The model %(model)s did not answer within %(seconds)s seconds. It may be out of '
                                  'quota or rate limited; Hermes keeps retrying in that case. Choose another model or '
                                  'check the provider account.', model=label, seconds=MODEL_TEST_SECONDS))
            time.sleep(2)

    def _safe_config(self, main_home=None):
        """Memory off; on the run platform the ERP tools plus what is switched on in Tools and services; provider
        keys read from the main Hermes profile (``main_home``, as Hermes reports it) instead of copied."""
        self.ensure_one()
        profile = self.sudo()
        api_server = [MCP_SERVER] + profile.tool_ids.filtered('enabled').mapped('toolset') + profile.server_ids.filtered(
            lambda s: s.kind == 'external' and s.enabled).mapped('hermes_name')
        config = {**SAFE_CONFIG, 'platform_toolsets': {**SAFE_CONFIG['platform_toolsets'], 'api_server': api_server}}
        if main_home:
            env_file = shlex.quote(f"{main_home.rstrip('/')}/.env")
            config['secrets'] = {'command': {'enabled': True, 'command': SHARED_KEYS_COMMAND.format(env=env_file)}}
        return config

    def _refresh_tools(self):
        """Read back from Hermes whether each tool has what it needs, and whether each tool server answers."""
        self.ensure_one()
        profile = self.sudo()
        engine = profile.engine_id
        listing = engine._management('GET', '/api/tools/toolsets', query={'profile': profile.hermes_name})
        configured = {row.get('name'): row.get('configured') for row in (listing if isinstance(listing, list) else [])
                      if isinstance(row, dict)}
        for tool in profile.tool_ids:
            internal(tool).write({'status': 'ready' if configured.get(tool.toolset) else 'needs_key'})
        for server in profile.server_ids:
            if server.kind == 'erp':
                internal(server).write({'status': 'ready', 'status_message': False})
            elif not server.enabled:
                internal(server).write({'status': 'off', 'status_message': False})
            else:
                internal(server).write(server._probe())

    def _refresh_jobs(self):
        """The profile's scheduled jobs as Hermes lists them now."""
        self.ensure_one()
        profile = self.sudo()
        listing = profile.engine_id._management('GET', '/api/cron/jobs', query={'profile': profile.hermes_name})
        rows = listing if isinstance(listing, list) else (listing or {}).get('jobs', [])
        values = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get('id'):
                continue
            last = row.get('last_status')
            values[str(row['id'])] = {
                'name': row.get('name') or str(row['id']),
                'schedule': row.get('schedule_display') or '',
                'next_run': hermes_time(row.get('next_run_at')),
                'last_run': hermes_time(row.get('last_run_at')),
                'last_result': 'failed' if last == 'error' else ('done' if last else False),
                'state': 'paused' if row.get('state') == 'paused' or row.get('enabled') is False else 'active'}
        for job in profile.job_ids:
            if job.hermes_id in values:
                internal(job).write(values.pop(job.hermes_id))
            else:
                internal(job).unlink()
        internal(self.env['ai.agent.profile.job'].sudo()).create([
            {'profile_id': profile.id, 'hermes_id': hermes_id, **job} for hermes_id, job in values.items()])

    def _odoo_url(self):
        """The Odoo address Hermes uses to call the tools: ``ai_agent.odoo_url``, else ``web.base.url``."""
        params = self.env['ir.config_parameter'].sudo()
        return (params.get_str('ai_agent.odoo_url') or params.get_str('web.base.url') or '').rstrip('/')

    def _sync_mcp(self):
        """Register Odoo's MCP server on the profile, with a new bearer token when it is missing in Hermes."""
        from .tools import key_hash
        engine = self.engine_id.sudo()
        listing = engine._management('GET', '/api/mcp/servers', query={'profile': self.hermes_name})
        servers = listing if isinstance(listing, list) else (listing or {}).get('servers', [])
        names = {s.get('name') for s in servers if isinstance(s, dict)}
        for legacy in names & set(LEGACY_MCP_SERVERS):
            engine._management('DELETE', f'/api/mcp/servers/{legacy}', query={'profile': self.hermes_name})
        if MCP_SERVER in names and self.sudo().mcp_token_hash:
            return
        if MCP_SERVER in names:
            engine._management('DELETE', f'/api/mcp/servers/{MCP_SERVER}', query={'profile': self.hermes_name})
        token = token_generator.token_urlsafe(32)
        engine._management('POST', '/api/mcp/servers', {
            'name': MCP_SERVER, 'url': f'{self._odoo_url()}/ai_agent/mcp', 'auth': 'header', 'bearer_token': token},
            query={'profile': self.hermes_name})
        internal(self.sudo()).write({'mcp_token_hash': key_hash(token)})

    def action_sync(self):
        """Sync to Hermes: managers, and department managers for their department's profile."""
        for profile in self:
            if not profile.can_configure:
                raise AccessError(_('Only AI Agent managers and the department\'s manager sync it.'))
            if profile.engine_id.sudo().state not in ('ready', 'needs_model'):
                raise UserError(_('Check the Hermes connection first.'))
        return self._sync_to_hermes()

    def _sync_to_hermes(self):
        """Sync each profile and record how it went (the caller checked who may). The company profile, once in
        Hermes, brings the company agent."""
        for profile in self:
            try:
                profile._sync()
                values = {'state': 'in_sync', 'sync_message': _('In sync with Hermes.')}
            except UserError as error:
                values = {'state': 'failed', 'sync_message': str(error)}
                profile.engine_id._unreachable(error)
            internal(profile.sudo()).write({**values, 'synced_at': fields.Datetime.now()})
            profile._sync_progress(len(profile._sync_steps()), state='done')
            if profile.kind == 'company' and profile.state == 'in_sync':
                profile._ensure_company_agent()
        return True

    def _ensure_company_agent(self):
        """The company agent: for everyone in the company, on the company profile, acting as the company's AI
        assistant (owner, 2026-11-09: made automatically). An agent the company already has for everyone counts."""
        self.ensure_one()
        Agent = internal(self.env['ai.agent'].sudo().with_context(active_test=False))
        if Agent.search_count([('company_id', '=', self.company_id.id), ('engine_id', '=', self.engine_id.id),
                               ('access_scope', '=', 'company'), ('department_id', '=', False)]):
            return Agent.browse()
        agent = Agent.create({'name': _('%s Assistant', self.company_id.name), 'engine_id': self.engine_id.id,
                              'company_id': self.company_id.id, 'access_scope': 'company',
                              'description': _('Made with the company\'s Hermes profile, for everyone in the '
                                               'company.')})
        if self.engine_id.state == 'ready':
            internal(agent).write({'state': 'active', 'activation_hash': agent._configuration_hash()})
        return agent

    def action_add_tool_server(self):
        """Add a tool server dialog (approved mock 2026-11-08, board 9): AI Agent managers only."""
        self.ensure_one()
        manager(self)
        return {'type': 'ir.actions.act_window', 'res_model': 'ai.agent.tool.server.add', 'view_mode': 'form',
                'target': 'new', 'name': _('Add a tool server'), 'context': {'default_profile_id': self.id}}

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
            if profile.in_hermes:
                try:
                    profile.engine_id.sudo()._management('DELETE', f'/api/profiles/{profile.hermes_name}')
                except hermes.HermesRejected as error:
                    if error.status != 404:  # 404: already gone from Hermes, nothing to remove.
                        raise
            reference = profile.sudo().secret_reference
            if (reference or '').startswith(secrets.PREFIX):
                secrets.remove(reference, self.env.cr.dbname)
            internal(profile.sudo()).write({'state': 'draft', 'in_hermes': False, 'secret_reference': 'AI_AGENT_SECRET_UNSET',
                                            'sync_message': _('Removed from Hermes.'), 'active': False})
        self._reassign_agents()
        return True
