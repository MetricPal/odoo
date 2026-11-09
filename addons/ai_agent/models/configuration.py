import json
import re
import subprocess
import sys
import time
from pathlib import Path

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services import hermes, secrets
from .common import FILE_MAX_BYTES, TEXT_MAX_CHARS, extract_text, internal, loading_demo, manager, trusted


# Providers suggested for company data (your own key), in this order; key names Hermes does not report; the
# keyless provider offered for trying it out (data goes to an outside service).
KEY_PROVIDERS = ('openrouter', 'openai-api', 'anthropic', 'gemini')
KEY_ENV_FALLBACK = {'openrouter': 'OPENROUTER_API_KEY'}
FREE_PROVIDER = 'opencode-free'
ENV_NAME = re.compile(r'[A-Z][A-Z0-9_]{1,80}')
# Models page of the ERP's local Hermes (its dashboard; deployment/erp_hermes.py).
LOCAL_MODELS_URL = 'http://127.0.0.1:9120/models'
# The fixed command that starts the ERP's local Hermes (approved mock 2026-11-08, board 13).
ERP_HERMES_SCRIPT = Path(__file__).resolve().parent.parent / 'deployment' / 'erp_hermes.py'
START_WAIT_SECONDS = 20

class CompanyConfiguration(models.AbstractModel):
    _name = 'ai.agent.configuration.mixin'
    _description = 'AI company configuration'

    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            manager(self)
        protected = {'state', 'revision', 'activation_hash', 'extracted_text', 'checked_at',
                     'capabilities', 'toolsets', 'models_catalog', 'status_message', 'hermes_runtime'}
        if not trusted(self) and not loading_demo(self) and any(protected & vals.keys() for vals in vals_list):
            raise AccessError(_('Create a draft, then use the review and verification buttons.'))
        if any(v.get('company_id', self.env.company.id) not in self.env.companies.ids for v in vals_list):
            raise AccessError(_('Use a selected company.'))
        return super().create(vals_list)

    def write(self, vals):
        if not trusted(self):
            manager(self)
        if 'company_id' in vals and any(r.company_id.id != vals['company_id'] for r in self):
            raise AccessError(_('Company ownership cannot be reassigned.'))
        return super().write(vals)

    def unlink(self):
        manager(self)
        return super().unlink()


class Engine(models.Model):
    _name = 'ai.agent.engine'
    _description = 'Hermes Engine'
    _inherit = 'ai.agent.configuration.mixin'

    name = fields.Char(required=True, string='Connection name')
    connection_mode = fields.Selection([('local', 'Local Hermes'), ('remote', 'Remote Hermes')], default='remote', required=True)
    url = fields.Char(string='Hermes URL', required=True, help='HTTPS for remote servers; HTTP is permitted only on numeric loopback addresses.')
    secret_reference = fields.Char(required=True, default='AI_AGENT_SECRET_UNSET', groups=fields.NO_ACCESS, copy=False)
    management_same_connection = fields.Boolean(string='Management uses the same URL and API key',
        help='Use the Hermes URL and API key above for management requests as well.')
    management_url = fields.Char(groups='ai_agent.group_manager', string='Management URL',
                                 help='Leave blank when management uses the same URL.')
    management_secret_reference = fields.Char(required=True, default='AI_AGENT_SECRET_UNSET', groups=fields.NO_ACCESS, copy=False)
    api_key = fields.Char(string='API key', compute='_compute_keys', inverse='_inverse_keys', groups='ai_agent.group_manager', copy=False)
    management_api_key = fields.Char(string='Management API key', compute='_compute_keys', inverse='_inverse_keys', groups='ai_agent.group_manager', copy=False)
    api_key_saved = fields.Boolean(compute='_compute_keys', groups='ai_agent.group_manager')
    management_key_saved = fields.Boolean(compute='_compute_keys', groups='ai_agent.group_manager')
    state = fields.Selection([('unchecked', 'Not checked'), ('needs_model', 'Needs a model'), ('ready', 'Ready'),
                              ('blocked', 'Needs attention')],
                             default='unchecked', readonly=True)
    revision = fields.Integer(default=1, readonly=True)
    checked_at = fields.Datetime(readonly=True)
    capabilities = fields.Json(readonly=True, groups='ai_agent.group_manager')
    toolsets = fields.Json(readonly=True, groups='ai_agent.group_manager')
    models_catalog = fields.Json(readonly=True, groups='ai_agent.group_manager')
    status_message = fields.Char(readonly=True)
    hermes_runtime = fields.Selection([('running', 'Running'), ('stopped', 'Stopped'),
                                       ('gateway_stopped', 'Gateway stopped'), ('unreachable', 'Cannot be reached')],
                                      string='Hermes', readonly=True,
                                      help='What the last check found: whether Hermes itself is running.')
    runs_on = fields.Char(compute='_compute_runs_on')
    can_start_hermes = fields.Boolean(compute='_compute_can_start_hermes')
    demo = fields.Boolean(readonly=True, copy=False,
                          help='Created by demo data: a local loopback connection allowed without the deployment allowlist.')
    max_concurrent = fields.Integer(string='Runs at the same time', default=10, required=True,
                                    help='Runs sent to this Hermes at once, all agents and profiles together (Hermes '
                                         'caps runs per gateway: keep this at or below its max_concurrent_runs). '
                                         'More questions wait in the queue.')
    load_summary = fields.Char(string='Now', compute='_compute_load', groups='ai_agent.group_manager')
    paused_model_ids = fields.Many2many('ai.agent.model.pause', string='Paused models', compute='_compute_load',
                                        groups='ai_agent.group_manager')

    enabled_model_ids = fields.One2many('ai.agent.engine.model', 'engine_id', domain=[('enabled', '=', True)])
    provider_catalog = fields.Json(compute='_compute_provider_catalog', groups='ai_agent.group_manager')

    model_settings_url = fields.Char(compute='_compute_model_settings_url', groups='ai_agent.group_manager')

    @api.depends('connection_mode', 'url', 'management_url', 'management_same_connection')
    def _compute_model_settings_url(self):
        for engine in self:
            if engine.connection_mode == 'local':
                engine.model_settings_url = LOCAL_MODELS_URL
            else:
                base = engine.url if engine.management_same_connection else (engine.management_url or engine.url)
                engine.model_settings_url = base.rstrip('/') + '/models' if base else False

    @api.depends('models_catalog', 'enabled_model_ids', 'enabled_model_ids.enabled')
    def _compute_provider_catalog(self):
        for engine in self:
            raw = engine.models_catalog or {'providers': []}
            catalog = engine._normalize_model_catalog(raw)
            for provider in catalog['providers']:
                provider['enabled_models'] = engine.enabled_model_ids.filtered(
                    lambda m: m.provider == provider['slug'] and m.enabled).mapped('model')
            engine.provider_catalog = catalog

    @api.depends('secret_reference', 'management_secret_reference')
    def _compute_keys(self):
        for engine in self:
            engine.api_key = False
            engine.management_api_key = False
            engine.api_key_saved = bool(engine.sudo().secret_reference and engine.sudo().secret_reference != 'AI_AGENT_SECRET_UNSET')
            engine.management_key_saved = bool(engine.sudo().management_secret_reference and engine.sudo().management_secret_reference != 'AI_AGENT_SECRET_UNSET')

    def _inverse_keys(self):
        # create/write consume the submitted values before the ORM can store them.
        pass

    @api.onchange('connection_mode')
    def _onchange_connection_mode(self):
        if self.connection_mode == 'local':
            self.name = self.name or _('Local Hermes')
            self.url = 'http://127.0.0.1:8643'
            self.management_url = 'http://127.0.0.1:9120'
            self.management_same_connection = False
        else:
            if self.url == 'http://127.0.0.1:8643':
                self.url = False
            if self.management_url == 'http://127.0.0.1:9120':
                self.management_url = False
                self.management_same_connection = True

    @api.model_create_multi
    def create(self, vals_list):
        pending = []
        clean = []
        for values in vals_list:
            values = dict(values)
            if not trusted(self) and not loading_demo(self):
                values.pop('demo', None)  # only demo data files may mark a connection as demo
            pending.append((values.pop('api_key', False), values.pop('management_api_key', False)))
            if values.get('connection_mode') == 'local':
                values.setdefault('url', 'http://127.0.0.1:8643')
                values.setdefault('management_url', 'http://127.0.0.1:9120')
            else:
                values.setdefault('management_same_connection', not values.get('management_url') and not values.get('management_secret_reference'))
            clean.append(values)
        engines = super().create(clean)
        for engine, keys in zip(engines, pending):
            engine._save_keys(*keys)
        return engines

    def _demo_loopback(self):
        """Demo connections on the local loopback profile skip the deployment allowlist (and only those)."""
        self.ensure_one()
        return bool(self.sudo().demo and self.connection_mode == 'local')

    def _save_keys(self, api_key=False, management_api_key=False):
        self.ensure_one()
        for purpose, token in (('run', api_key), ('management', management_api_key)):
            if not token:
                continue
            if not isinstance(token, str) or len(token) > 4096 or '\n' in token or '\r' in token:
                raise UserError(_('Enter a valid API key.'))
            try:
                if self._credential(purpose) == token:
                    continue
            except UserError:
                pass
            try:
                reference = secrets.store({'database': self.env.cr.dbname, 'engine_id': self.id,
                    'company_id': self.company_id.id, 'purpose': purpose,
                    'url': self.url if purpose == 'run' else (self.management_url or self.url), 'token': token})
            except (ValueError, OSError):
                raise UserError(_('The API key could not be saved securely. Ask your system administrator to check private credential storage.')) from None
            internal(self.sudo()).write({'secret_reference' if purpose == 'run' else 'management_secret_reference': reference})

    def _credential(self, purpose):
        self.ensure_one()
        engine = self.sudo()
        reference = engine.secret_reference if purpose == 'run' else engine.management_secret_reference
        if purpose == 'management' and self.management_same_connection:
            return self._credential('run')
        if purpose == 'management' and reference == 'AI_AGENT_SECRET_UNSET' and (self.management_url or self.url) == self.url:
            return self._credential('run')
        if reference.startswith(secrets.PREFIX):
            try:
                bundle = json.loads(secrets.load(reference, self.env.cr.dbname))
                expected = {'database': self.env.cr.dbname, 'engine_id': self.id,
                            'company_id': self.company_id.id, 'purpose': purpose,
                            'url': self.url if purpose == 'run' else (self.management_url or self.url)}
                if any(bundle.get(k) != v for k, v in expected.items()):
                    raise ValueError('credential binding mismatch')
                return bundle['token']
            except Exception:
                raise UserError(_('Saved credentials do not match this connection. Enter the API key again.')) from None
        return hermes.credential(reference)

    def _compute_load(self):
        Run = self.env['ai.agent.run'].sudo()
        now = fields.Datetime.now()
        for engine in self:
            if not engine.id:
                engine.load_summary, engine.paused_model_ids = False, False
                continue
            mine = [('agent_id.engine_id', '=', engine.id)]
            running = Run.search_count(mine + [('state', 'in', ['submitting', 'running', 'stop_requested'])])
            waiting = Run.search(mine + [('state', '=', 'queued')], order='create_date')
            summary = _('%(running)s running · %(queued)s queued', running=running, queued=len(waiting))
            if waiting:
                minutes, seconds = divmod(max(0, int((now - waiting[0].create_date).total_seconds())), 60)
                summary += ' · ' + _('oldest waiting %s', '%d:%02d' % (minutes, seconds))
            engine.load_summary = summary
            engine.paused_model_ids = self.env['ai.agent.model.pause'].sudo().search(
                [('engine_id', '=', engine.id), ('until', '>', now)])

    def action_view_activity(self):
        """Activity (questions queued and running) on this Hermes connection."""
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('ai_agent.action_activity')
        action['domain'] = [('agent_id.engine_id', '=', self.id)]
        action['display_name'] = _('Activity: %s', self.name)
        return action

    @api.constrains('max_concurrent')
    def _check_max_concurrent(self):
        if any(not 1 <= engine.max_concurrent <= 100 for engine in self):
            raise ValidationError(_('Use 1–100 runs at the same time for a Hermes connection.'))

    @api.constrains('url', 'secret_reference', 'management_url', 'management_secret_reference', 'connection_mode', 'management_same_connection')
    def _validate_connection(self):
        for engine in self:
            demo = engine._demo_loopback()
            hermes.target(engine.url, resolve=False, demo=demo)
            hermes.target(engine.url if engine.management_same_connection else (engine.management_url or engine.url),
                          resolve=False, demo=demo)
            if engine.connection_mode == 'local' and engine.management_same_connection:
                raise ValidationError(_('The local profile uses a separate management connection.'))
            if engine.connection_mode == 'local' and (engine.url != 'http://127.0.0.1:8643' or engine.management_url != 'http://127.0.0.1:9120'):
                raise ValidationError(_('Local Hermes uses the provisioned loopback connection. Select Remote Hermes for another server.'))
            if any(not re.fullmatch(r'AI_AGENT_SECRET_[A-Z0-9_]{1,80}', value or '')
                   for value in (engine.sudo().secret_reference, engine.sudo().management_secret_reference)):
                raise ValidationError(_('Use a provisioned credential reference, not a secret.'))

    def write(self, vals):
        if not trusted(self):
            manager(self)
        vals = dict(vals)
        keys = (vals.pop('api_key', False), vals.pop('management_api_key', False))
        if not trusted(self) and not loading_demo(self) and \
                {'state', 'revision', 'checked_at', 'capabilities', 'toolsets', 'models_catalog', 'status_message',
                 'hermes_runtime'} & vals.keys():
            raise AccessError(_('Use Check connection to update readiness.'))
        if not loading_demo(self) and \
                {'url', 'secret_reference', 'management_url', 'management_secret_reference', 'connection_mode', 'management_same_connection'} & vals.keys():
            for engine in self:
                super(Engine, engine).write({**vals, 'state': 'unchecked', 'checked_at': False, 'hermes_runtime': False,
                    'capabilities': False, 'toolsets': False, 'models_catalog': False, 'status_message': False,
                    'revision': engine.revision + 1})
                engine._save_keys(*keys)
            return True
        result = super().write(vals) if vals else True
        for engine in self:
            engine._save_keys(*keys)
        self.invalidate_recordset(['api_key', 'management_api_key', 'api_key_saved', 'management_key_saved'])
        return result

    def _request(self, method, path, payload=None, headers=None, profile=None, query=None):
        """A run API call. With ``profile`` (an Odoo-managed Hermes profile) it goes to that profile on the
        multiplexing gateway, ``/p/<name>``, with the profile's own key (ADR 0012)."""
        self.ensure_one()
        if profile:
            return hermes.request(self.url, None, method, f'/p/{profile.hermes_name}{path}', payload, headers,
                                  credential_value=profile._run_key(), demo=self._demo_loopback(), query=query)
        return hermes.request(self.url, None, method, path, payload, headers, credential_value=self._credential('run'),
                              demo=self._demo_loopback(), query=query)

    def _management(self, method, path, payload=None, query=None):
        """A Hermes management API call (profiles, config, keys)."""
        self.ensure_one()
        url = self.url if self.management_same_connection else (self.management_url or self.url)
        return hermes.request(url, None, method, path, payload, credential_value=self._credential('management'),
                              demo=self._demo_loopback(), query=query)

    def _inspect(self, profile=None):
        """Fresh inspection before every submission; discovery never grants execution.

        With ``profile`` (an Odoo-managed profile, ADR 0012) the profile is inspected: its only enabled toolset may be
        Odoo's own MCP server."""
        health = self._request('GET', '/health/detailed')
        if profile:
            return self._inspect_profile(profile, health)
        capabilities = self._request('GET', '/v1/capabilities')
        tools = self._request('GET', '/v1/toolsets')
        # Verified local Hermes 6cd2502 wraps discovery in an OpenAI list object.
        # Older documented contracts return a bare list; validate both shapes.
        if isinstance(tools, dict) and tools.get('object') == 'list':
            tools = tools.get('data')
        config = hermes.request(self.url if self.management_same_connection else (self.management_url or self.url), None, 'GET', '/api/config', credential_value=self._credential('management'),
                                demo=self._demo_loopback())
        memory = config.get('memory', {}) if isinstance(config, dict) else {}
        if (memory.get('memory_enabled') is not False or memory.get('user_profile_enabled') is not False
                or memory.get('provider') not in (None, '', 'none')):
            raise UserError(_('Disable persistent memory, user profiles and external memory providers on this dedicated profile.'))
        self._check_health(health)
        features = capabilities.get('features', {}) if isinstance(capabilities, dict) else {}
        if not features.get('run_submission') or not features.get('run_status'):
            raise UserError(_('This Hermes version does not support durable runs.'))
        if not isinstance(tools, list) or any(not isinstance(t, dict)
                or not isinstance(t.get('enabled'), bool) or not isinstance(t.get('tools'), list) for t in tools):
            raise UserError(_('Hermes tool discovery is invalid.'))
        # v1 supplies bounded context from Odoo. No Hermes terminal/file/browser/MCP bypass.
        if any(t.get('enabled') and t.get('tools') for t in tools):
            raise UserError(_('Use a dedicated profile with all agent-callable toolsets disabled for this release.'))
        return capabilities, tools

    @api.model
    def _check_health(self, health):
        """Hermes must report ok; otherwise say which of its checks is not."""
        if isinstance(health, dict) and health.get('status') == 'ok':
            return
        checks = ((health or {}).get('readiness') or {}).get('checks') or {} if isinstance(health, dict) else {}
        failing = sorted(name for name, check in checks.items()
                         if isinstance(check, dict) and check.get('status') not in ('ok', None))
        if failing == ['model']:
            error = UserError(_('Hermes is connected but has no AI model yet. Choose one below; agents can answer as '
                                'soon as it is set.'))
            error.needs_model = True
            raise error
        if failing:
            raise UserError(_('Hermes is not ready: %s. Check Hermes.', ', '.join(failing)))
        raise UserError(_('Hermes is not ready.'))

    def _inspect_profile(self, profile, health):
        from .profile import MCP_SERVER
        self._check_health(health)
        capabilities = self._request('GET', '/v1/capabilities', profile=profile)
        tools = self._request('GET', '/v1/toolsets', profile=profile)
        if isinstance(tools, dict) and tools.get('object') == 'list':
            tools = tools.get('data')
        config = self._management('GET', '/api/config', query={'profile': profile.hermes_name})
        memory = config.get('memory', {}) if isinstance(config, dict) else {}
        if memory.get('memory_enabled') is not False or memory.get('user_profile_enabled') is not False:
            raise UserError(_('Memory is on in the Hermes profile "%s". Sync it again.', profile.name))
        features = capabilities.get('features', {}) if isinstance(capabilities, dict) else {}
        if not features.get('run_submission') or not features.get('run_status'):
            raise UserError(_('This Hermes version does not support durable runs.'))
        if not isinstance(tools, list) or any(not isinstance(t, dict) for t in tools):
            raise UserError(_('Hermes tool discovery is invalid.'))
        allowed = {MCP_SERVER, f'mcp-{MCP_SERVER}', f'mcp_{MCP_SERVER}', f'mcp:{MCP_SERVER}'}
        if any(t.get('enabled') and t.get('tools') and t.get('name') not in allowed for t in tools):
            raise UserError(_('The Hermes profile "%s" has tools other than the ERP\'s. Sync it again.', profile.name))
        return capabilities, tools

    def _model_catalog(self):
        self.ensure_one()
        # Every provider, set up or not, so Add model can offer to set one up (approved mock 2026-11-07, board 7).
        return self._normalize_model_catalog(self._request('GET', '/api/model/options',
                                                           query={'include_unconfigured': 'true'}))

    def _normalize_model_catalog(self, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get('providers'), list) or len(raw['providers']) > 200:
            raise UserError(_('Hermes returned an invalid provider catalog.'))
        providers = []
        for item in raw['providers']:
            if not isinstance(item, dict) or not isinstance(item.get('slug'), str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}', item['slug']):
                raise UserError(_('Hermes returned an invalid provider catalog.'))
            models = item.get('models') or []
            if not isinstance(models, list) or any(not isinstance(m, str) or len(m) > 300 for m in models):
                raise UserError(_('Hermes returned an invalid model catalog.'))
            key_env = item.get('key_env') or KEY_ENV_FALLBACK.get(item['slug'], '')
            providers.append({'slug': item['slug'], 'name': str(item.get('name') or item['slug'])[:150],
                'models': list(dict.fromkeys(models)), 'authenticated': item.get('authenticated') is True,
                'total_models': len(models),
                'key_env': key_env if isinstance(key_env, str) and ENV_NAME.fullmatch(key_env) else ''})
        return {'providers': providers, 'provider': raw.get('provider') if isinstance(raw.get('provider'), str) else '',
                'model': raw.get('model') if isinstance(raw.get('model'), str) else ''}

    def _validate_catalog_model(self, provider, model):
        catalog = self._model_catalog()
        entry = next((p for p in catalog['providers'] if p['slug'] == provider), None)
        if not entry or not entry['authenticated']:
            raise UserError(_('Set up this provider first: add its key on the Hermes connection, or sign in in Hermes.'))
        if model not in entry['models']:
            raise UserError(_('Select a model returned by this provider in the current Hermes catalog.'))
        return catalog

    def set_model_enabled(self, provider, model, enabled):
        manager(self)
        self.ensure_one()
        if not isinstance(enabled, bool):
            raise UserError(_('Choose whether to enable this model.'))
        # Serialize double clicks and concurrent configuration on this engine.
        self.env.cr.execute('SELECT id FROM ai_agent_engine WHERE id = %s FOR UPDATE', [self.id])
        records = self.env['ai.agent.engine.model']
        record = records.search([('engine_id', '=', self.id), ('provider', '=', provider), ('model', '=', model)], limit=1)
        if enabled:
            catalog = self._validate_catalog_model(provider, model)
            if record:
                internal(record).write({'enabled': True})
            else:
                internal(records).create({'engine_id': self.id, 'provider': provider, 'model': model})
            internal(self).write({'models_catalog': catalog})
        elif record:
            record.write({'enabled': False})
        return True

    def action_refresh_models(self):
        manager(self)
        self.ensure_one()
        internal(self).write({'models_catalog': self._model_catalog()})
        return True

    def action_models(self):
        self.action_refresh_models()
        picker = self.env['ai.agent.model.picker'].create({'engine_id': self.id, 'catalog': self.provider_catalog})
        return {'type': 'ir.actions.act_window', 'res_model': picker._name, 'res_id': picker.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Add model')}

    def action_provider_setup(self):
        manager(self)
        self.ensure_one()
        return self._dashboard_action('/models')

    def _dashboard_action(self, page, close=False):
        """Open a page of this connection's Hermes dashboard (its Models, Keys or tool servers page)."""
        self.ensure_one()
        if self.connection_mode == 'local':
            # The ERP's own Hermes home serves its dashboard on 9120 (deployment/erp_hermes.py).
            url = LOCAL_MODELS_URL.removesuffix('/models')
        else:
            url = self.url if self.management_same_connection else (self.management_url or self.url)
            hermes.target(url, resolve=False, demo=self._demo_loopback())
        return {'type': 'ir.actions.act_url', 'url': url.rstrip('/') + page, 'target': 'new', 'close': close}

    def _unreachable(self, error):
        """Hermes could not be reached at all: the connection needs attention until it is checked again."""
        if getattr(error, 'unreachable', False):
            internal(self.sudo()).write({'state': 'blocked', 'status_message': str(error),
                                         'checked_at': fields.Datetime.now(),
                                         'hermes_runtime': self.sudo()._probe_runtime()})

    # -- starting Hermes (approved mocks 2026-11-08, boards 13 and 14) -----------------------------------------
    @api.depends('connection_mode', 'url')
    def _compute_runs_on(self):
        for engine in self:
            engine.runs_on = _('This server') if engine.connection_mode == 'local' else \
                _('Another machine · %s', engine.url or '')

    @api.depends_context('uid')
    @api.depends('state', 'connection_mode', 'hermes_runtime')
    def _compute_can_start_hermes(self):
        is_admin = self.env.user.has_group('base.group_system')
        for engine in self:
            startable = ('stopped', 'gateway_stopped') if engine.connection_mode == 'local' else ('gateway_stopped',)
            engine.can_start_hermes = is_admin and engine.state == 'blocked' and engine.hermes_runtime in startable

    def _answers(self, call):
        """True when Hermes answered the call at all (any HTTP answer counts; only "not reachable" does not)."""
        try:
            call()
        except (hermes.HermesRejected, hermes.HermesUnavailable, hermes.HermesUncertain) as error:
            return not getattr(error, 'unreachable', False)
        except UserError:
            return False  # For example no saved key yet: not known to be running.
        return True

    def _probe_runtime(self):
        """Is Hermes running? Its dashboard (management API) and its gateway (run API) are asked separately."""
        self.ensure_one()
        dashboard = self._answers(lambda: self._management('GET', '/api/status'))
        gateway = self._answers(lambda: self._request('GET', '/health'))
        if dashboard and gateway:
            return 'running'
        if dashboard:
            return 'gateway_stopped'
        if self.connection_mode == 'remote':
            return 'unreachable'
        return 'stopped'

    def action_start_hermes(self):
        """Start Hermes: on this server with the fixed deployment command, on another machine through its own
        management API (its gateway). Settings administrators only."""
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only Settings administrators start Hermes.'))
        engine = self.sudo()
        if engine.connection_mode == 'local':
            engine._start_local_hermes()
        else:
            engine._management('POST', '/api/gateway/start')
        deadline = time.monotonic() + START_WAIT_SECONDS
        while time.monotonic() < deadline and engine._probe_runtime() != 'running':
            time.sleep(1)
        engine._check_connection()
        return True

    def _start_local_hermes(self):
        # A fixed command: this Python, the deployment script shipped with the module, the "start" action.
        try:
            result = subprocess.run([sys.executable, str(ERP_HERMES_SCRIPT), 'start'], capture_output=True,
                                    text=True, timeout=30, stdin=subprocess.DEVNULL, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise UserError(_('Hermes could not be started on this server. Ask your system administrator to start '
                              'it with ai_agent/deployment/erp_hermes.py.')) from None
        if result.returncode:
            detail = (result.stderr or result.stdout or '').strip().splitlines()[-1:] or ['']
            raise UserError(_('Hermes could not be started on this server: %s', detail[0][:2000]))

    def action_check(self):
        manager(self)
        return self._check_connection()

    def _check_connection(self):
        for engine in self:
            try:
                if engine.connection_mode == 'local':
                    try:
                        keys = secrets.local_keys()
                    except (OSError, ValueError):
                        raise UserError(_('Local Hermes credentials are unavailable. Ask your system administrator to provision the isolated local profile.')) from None
                    engine._save_keys(keys['API_SERVER_KEY'], keys['HERMES_DASHBOARD_SESSION_TOKEN'])
                capabilities, tools = engine._inspect()
                catalog = engine._model_catalog()
                values = {'state': 'ready', 'status_message': _('Connection verified.'), 'hermes_runtime': 'running',
                          'capabilities': capabilities, 'toolsets': tools, 'models_catalog': catalog}
            except UserError as error:
                state = 'needs_model' if getattr(error, 'needs_model', False) else 'blocked'
                values = {'state': state, 'status_message': str(error), 'capabilities': False,
                          'toolsets': False, 'models_catalog': False,
                          'hermes_runtime': engine._probe_runtime() if state == 'blocked' else 'running'}
            internal(engine).write({**values, 'checked_at': fields.Datetime.now()})
        return True

    # -- the default model (approved mock 2026-11-07, boards 5 and 6) ------------------------------------------
    def _provider_options(self):
        """Every provider Hermes offers, ready or not, with its models and the name of its key."""
        raw = self._management('GET', '/api/model/options', query={'include_unconfigured': 'true'})
        if not isinstance(raw, dict) or not isinstance(raw.get('providers'), list) or len(raw['providers']) > 300:
            raise UserError(_('Hermes returned an invalid provider list.'))
        providers = []
        for item in raw['providers']:
            if not isinstance(item, dict) or not isinstance(item.get('slug'), str) \
                    or not re.fullmatch(r'[a-z0-9][a-z0-9_.:-]{0,99}', item['slug']) or item.get('source') == 'virtual':
                continue
            models = [m for m in (item.get('models') or []) if isinstance(m, str) and len(m) <= 300]
            key_env = item.get('key_env') or KEY_ENV_FALLBACK.get(item['slug'], '')
            providers.append({
                'slug': item['slug'], 'name': str(item.get('name') or item['slug'])[:150],
                'ready': item.get('authenticated') is True, 'models': list(dict.fromkeys(models))[:500],
                'key_env': key_env if isinstance(key_env, str) and ENV_NAME.fullmatch(key_env) else '',
            })
        current = {'provider': raw.get('provider') if isinstance(raw.get('provider'), str) else '',
                   'model': raw.get('model') if isinstance(raw.get('model'), str) else ''}
        return providers, current

    def default_model_data(self):
        """What the Choose the default model section shows."""
        manager(self)
        self.ensure_one()
        providers, current = self._provider_options()
        by_slug = {p['slug']: p for p in providers}
        current['name'] = by_slug.get(current['provider'], {}).get('name', current['provider'])
        return {'state': self.state, 'current': current,
                'key_providers': [by_slug[s] for s in KEY_PROVIDERS if s in by_slug],
                'free': by_slug.get(FREE_PROVIDER) or False,
                'providers': sorted(providers, key=lambda p: (not p['ready'], p['name'].lower())),
                'setup_url': self.action_provider_setup()['url']}

    def provider_models(self, slug):
        """The models of a ready provider and the one Hermes recommends."""
        manager(self)
        self.ensure_one()
        entry = self._provider_entry(slug)
        recommended = self._management('GET', '/api/model/recommended-default', query={'provider': slug})
        model = recommended.get('model') if isinstance(recommended, dict) else ''
        return {'models': entry['models'], 'recommended': model if model in entry['models'] else
                (entry['models'][0] if entry['models'] else '')}

    def _provider_entry(self, slug):
        providers, _current = self._provider_options()
        entry = next((p for p in providers if p['slug'] == slug), None)
        if not entry:
            raise UserError(_('Hermes does not offer this provider.'))
        return entry

    def set_default_model(self, slug, model=False, key=False):
        """Use a provider's model as Hermes's default: with a key the provider needs (saved only in Hermes), or a
        provider that is ready. Profiles without a model of their own follow it."""
        manager(self)
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM ai_agent_engine WHERE id = %s FOR UPDATE', [self.id])
        entry = self._provider_entry(slug)
        if key:
            self._save_provider_key(entry, key)
            entry = self._provider_entry(slug)
        if not entry['ready']:
            raise UserError(_('Add the key of %s first.', entry['name']))
        if not model:
            model = self.provider_models(slug)['recommended']
        if not model or model not in entry['models']:
            raise UserError(_('Choose a model that %s offers.', entry['name']))
        result = self._management('POST', '/api/model/set', {'scope': 'main', 'provider': slug, 'model': model,
                                                              'confirm_expensive_model': True})
        if isinstance(result, dict) and result.get('ok') is False:
            raise UserError(str(result.get('error') or result.get('detail') or _('Hermes did not accept this model.'))[:2000])
        self.action_check()
        if self.state == 'ready':
            self.set_model_enabled(slug, model, True)
            self._follow_default_model(slug, model)
        return self.default_model_data()

    def _save_provider_key(self, entry, key):
        """Check a provider's key with Hermes and save it there only; the ERP never stores it."""
        key = key.strip() if isinstance(key, str) else ''
        if not key or len(key) > 4096 or any(c in key for c in '\r\n\0'):
            raise UserError(_('Enter a valid API key.'))
        if not entry['key_env']:
            raise UserError(_('%s is set up with a sign-in in Hermes, not with a key.', entry['name']))
        check = self._management('POST', '/api/providers/validate', {'key': entry['key_env'], 'value': key})
        if isinstance(check, dict) and not check.get('ok') and check.get('reachable'):
            raise UserError(str(check.get('message') or _('%s refused this key.', entry['name']))[:2000])
        self._management('PUT', '/api/env', {'key': entry['key_env'], 'value': key})

    def save_provider_key(self, slug, key):
        """Set up a provider with its key from Add model; its models can then be enabled."""
        manager(self)
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM ai_agent_engine WHERE id = %s FOR UPDATE', [self.id])
        self._save_provider_key(self._provider_entry(slug), key)
        internal(self).write({'models_catalog': self._model_catalog()})
        return self.provider_catalog

    def _follow_default_model(self, provider, model):
        """Profiles in Hermes without a model of their own use the default model."""
        profiles = self.env['ai.agent.profile'].sudo().search([('engine_id', '=', self.id), ('in_hermes', '=', True),
                                                               ('engine_model_id', '=', False)])
        for profile in profiles:
            try:
                self._management('PUT', f'/api/profiles/{profile.hermes_name}/model',
                                 {'provider': provider, 'model': model})
            except UserError:
                internal(profile).write({'state': 'needs_sync'})


class Skill(models.Model):
    _name = 'ai.agent.skill'
    _description = 'AI Skill'
    _inherit = ['ai.agent.configuration.mixin', 'mail.thread']

    name = fields.Char(required=True)
    description = fields.Char()
    instructions = fields.Text(required=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved')], default='draft', readonly=True, tracking=True)
    revision = fields.Integer(default=1, readonly=True)

    def write(self, vals):
        if not trusted(self) and {'state', 'revision'} & vals.keys():
            raise AccessError(_('Use Approve skill to authorize this revision.'))
        if {'name', 'instructions', 'description'} & vals.keys():
            for skill in self:
                super(Skill, skill).write({**vals, 'state': 'draft', 'revision': skill.revision + 1})
            return True
        return super().write(vals)

    def action_approve(self):
        manager(self)
        internal(self).write({'state': 'approved'})
        return True


class Source(models.Model):
    _name = 'ai.agent.source'
    _description = 'AI Knowledge Source'
    _inherit = 'ai.agent.configuration.mixin'

    name = fields.Char(required=True)
    kind = fields.Selection([('text', 'Text'), ('file', 'File')], default='text', required=True)
    text = fields.Text(string='Content')
    file = fields.Binary(attachment=False)
    filename = fields.Char()
    extracted_text = fields.Text(readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('ready', 'Ready'), ('failed', 'Needs attention')], default='draft', readonly=True)
    active = fields.Boolean(default=True)
    # Retained only to preserve existing per-reader grants during migration.
    # Current access is evaluated by native ir.access, not a retrieval allowlist.
    user_ids = fields.Many2many('res.users', string='Legacy readers', copy=False)
    revision = fields.Integer(default=1, readonly=True)
    status_message = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda s: s.text or s.file).action_prepare()
        return records

    def action_access_rights(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Security settings require a system administrator.'))
        action = self.env['ir.actions.actions']._for_xml_id('base.ir_access_action')
        model = self.env['ir.model']._get(self._name)
        action.update({'domain': [('model_id', '=', model.id)],
                       'context': {'default_model_id': model.id, 'default_operation': 'r',
                                   'default_domain': "[('id', '=', %s)]" % self.id}})
        return action

    @api.constrains('user_ids')
    def _check_users(self):
        for source in self:
            if any(u.share or source.company_id not in u.company_ids for u in source.user_ids):
                raise ValidationError(_('Sources can be shared only with internal users in their company.'))

    def write(self, vals):
        if not trusted(self) and {'state', 'extracted_text', 'revision', 'status_message'} & vals.keys():
            raise AccessError(_('Use Prepare source to update readiness.'))
        if {'text', 'file', 'filename', 'kind', 'user_ids'} & vals.keys():
            for source in self:
                super(Source, source).write({**vals, 'state': 'draft', 'extracted_text': False,
                                           'revision': source.revision + 1})
                if {'text', 'file', 'filename', 'kind'} & vals.keys() and (source.text or source.file):
                    source.action_prepare()
            return True
        return super().write(vals)

    def action_prepare(self):
        manager(self)
        for source in self:
            try:
                text = source.text or ''
                if source.kind == 'file':
                    if source.file.size > FILE_MAX_BYTES:
                        raise ValueError('size')
                    text = extract_text(source.file.content, source.filename)
                if not text.strip() or len(text) > TEXT_MAX_CHARS:
                    raise ValueError('text limits')
                values = {'state': 'ready', 'extracted_text': text, 'status_message': _('Text prepared for scoped retrieval.')}
            except Exception:
                values = {'state': 'failed', 'extracted_text': False,
                          'status_message': _('Use a readable PDF (up to 100 pages) or UTF-8 text file, up to 5 MB / 200,000 characters.')}
            internal(source).write(values)
        return True
