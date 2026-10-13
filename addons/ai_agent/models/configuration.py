import io
import json
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.pdf import PdfReader

from ..services import hermes, secrets
from .common import internal, manager, trusted


class CompanyConfiguration(models.AbstractModel):
    _name = 'ai.agent.configuration.mixin'
    _description = 'AI company configuration'

    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        manager(self)
        protected = {'state', 'revision', 'activation_hash', 'extracted_text', 'checked_at',
                     'capabilities', 'toolsets', 'models_catalog', 'status_message'}
        if not trusted(self) and any(protected & vals.keys() for vals in vals_list):
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
    state = fields.Selection([('unchecked', 'Not checked'), ('ready', 'Ready'), ('blocked', 'Needs attention')],
                             default='unchecked', readonly=True)
    revision = fields.Integer(default=1, readonly=True)
    checked_at = fields.Datetime(readonly=True)
    capabilities = fields.Json(readonly=True, groups='ai_agent.group_manager')
    toolsets = fields.Json(readonly=True, groups='ai_agent.group_manager')
    models_catalog = fields.Json(readonly=True, groups='ai_agent.group_manager')
    status_message = fields.Char(readonly=True)

    enabled_model_ids = fields.One2many('ai.agent.engine.model', 'engine_id', domain=[('enabled', '=', True)])
    provider_catalog = fields.Json(compute='_compute_provider_catalog', groups='ai_agent.group_manager')

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
                raise UserError(_('Odoo could not securely save the API key. Ask your system administrator to check private credential storage.')) from None
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

    @api.constrains('url', 'secret_reference', 'management_url', 'management_secret_reference', 'connection_mode', 'management_same_connection')
    def _validate_connection(self):
        for engine in self:
            hermes.target(engine.url, resolve=False)
            hermes.target(engine.url if engine.management_same_connection else (engine.management_url or engine.url), resolve=False)
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
        if not trusted(self) and {'state', 'revision', 'checked_at', 'capabilities', 'toolsets', 'models_catalog', 'status_message'} & vals.keys():
            raise AccessError(_('Use Check connection to update readiness.'))
        if {'url', 'secret_reference', 'management_url', 'management_secret_reference', 'connection_mode', 'management_same_connection'} & vals.keys():
            for engine in self:
                super(Engine, engine).write({**vals, 'state': 'unchecked', 'checked_at': False,
                    'capabilities': False, 'toolsets': False, 'models_catalog': False,
                    'revision': engine.revision + 1})
                engine._save_keys(*keys)
            return True
        result = super().write(vals) if vals else True
        for engine in self:
            engine._save_keys(*keys)
        self.invalidate_recordset(['api_key', 'management_api_key', 'api_key_saved', 'management_key_saved'])
        return result

    def _request(self, method, path, payload=None, headers=None):
        self.ensure_one()
        return hermes.request(self.url, None, method, path, payload, headers, credential_value=self._credential('run'))

    def _inspect(self):
        """Fresh inspection before every submission; discovery never grants execution."""
        health = self._request('GET', '/health/detailed')
        capabilities = self._request('GET', '/v1/capabilities')
        tools = self._request('GET', '/v1/toolsets')
        # Verified local Hermes 6cd2502 wraps discovery in an OpenAI list object.
        # Older documented contracts return a bare list; validate both shapes.
        if isinstance(tools, dict) and tools.get('object') == 'list':
            tools = tools.get('data')
        config = hermes.request(self.url if self.management_same_connection else (self.management_url or self.url), None, 'GET', '/api/config', credential_value=self._credential('management'))
        memory = config.get('memory', {}) if isinstance(config, dict) else {}
        if (memory.get('memory_enabled') is not False or memory.get('user_profile_enabled') is not False
                or memory.get('provider') not in (None, '', 'none')):
            raise UserError(_('Disable persistent memory, user profiles and external memory providers on this dedicated profile.'))
        if not isinstance(health, dict) or health.get('status') != 'ok':
            raise UserError(_('Hermes is not ready.'))
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

    def _model_catalog(self):
        self.ensure_one()
        return self._normalize_model_catalog(self._request('GET', '/api/model/options'))

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
            providers.append({'slug': item['slug'], 'name': str(item.get('name') or item['slug'])[:150],
                'models': list(dict.fromkeys(models)), 'authenticated': item.get('authenticated') is True,
                'total_models': len(models)})
        return {'providers': providers, 'provider': raw.get('provider') if isinstance(raw.get('provider'), str) else '',
                'model': raw.get('model') if isinstance(raw.get('model'), str) else ''}

    def _validate_catalog_model(self, provider, model):
        catalog = self._model_catalog()
        entry = next((p for p in catalog['providers'] if p['slug'] == provider), None)
        if not entry or not entry['authenticated']:
            raise UserError(_('Authenticate this provider in Hermes, then refresh the catalog.'))
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
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'current'}

    def action_provider_setup(self):
        manager(self)
        self.ensure_one()
        url = self.url if self.management_same_connection else (self.management_url or self.url)
        hermes.target(url, resolve=False)
        return {'type': 'ir.actions.act_url', 'url': url.rstrip('/') + '/models', 'target': 'new'}

    def action_check(self):
        manager(self)
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
                values = {'state': 'ready', 'status_message': _('Connection verified; tool-free assistant profile.'),
                          'capabilities': capabilities, 'toolsets': tools, 'models_catalog': catalog}
            except UserError as error:
                values = {'state': 'blocked', 'status_message': str(error), 'capabilities': False,
                          'toolsets': False, 'models_catalog': False}
            internal(engine).write({**values, 'checked_at': fields.Datetime.now()})
        return True


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
            raise AccessError(_('Odoo security settings require a system administrator.'))
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
                    if source.file.size > 5 * 1024 * 1024:
                        raise ValueError('size')
                    raw = source.file.content
                    if not raw or len(raw) > 5 * 1024 * 1024:
                        raise ValueError('size')
                    if raw.startswith(b'%PDF-'):
                        reader = PdfReader(io.BytesIO(raw))
                        if reader.is_encrypted or len(reader.pages) > 100:
                            raise ValueError('pdf limits')
                        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
                    elif (source.filename or '').lower().endswith(('.txt', '.md', '.csv')):
                        text = raw.decode('utf-8')
                    else:
                        raise ValueError('format')
                if not text.strip() or len(text) > 200000:
                    raise ValueError('text limits')
                values = {'state': 'ready', 'extracted_text': text, 'status_message': _('Text prepared for scoped retrieval.')}
            except Exception:
                values = {'state': 'failed', 'extracted_text': False,
                          'status_message': _('Use a readable PDF (up to 100 pages) or UTF-8 text file, up to 5 MB / 200,000 characters.')}
            internal(source).write(values)
        return True
