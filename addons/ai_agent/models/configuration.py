import io
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.pdf import PdfReader

from ..services import hermes
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

    name = fields.Char(required=True)
    url = fields.Char(string='Hermes address', required=True, help='HTTPS origin of a dedicated Hermes profile.')
    secret_reference = fields.Char(required=True, groups='ai_agent.group_manager',
                                   help='Provisioned credential reference; never paste a key here.')
    management_url = fields.Char(required=True, groups='ai_agent.group_manager', string='Hermes management address')
    management_secret_reference = fields.Char(required=True, groups='ai_agent.group_manager', string='Management credential reference')
    state = fields.Selection([('unchecked', 'Not checked'), ('ready', 'Ready'), ('blocked', 'Needs attention')],
                             default='unchecked', readonly=True)
    revision = fields.Integer(default=1, readonly=True)
    checked_at = fields.Datetime(readonly=True)
    capabilities = fields.Json(readonly=True, groups='ai_agent.group_manager')
    toolsets = fields.Json(readonly=True, groups='ai_agent.group_manager')
    models_catalog = fields.Json(readonly=True, groups='ai_agent.group_manager')
    status_message = fields.Char(readonly=True)

    @api.constrains('url', 'secret_reference', 'management_url', 'management_secret_reference')
    def _validate_connection(self):
        for engine in self:
            hermes.target(engine.url, resolve=False)
            hermes.target(engine.management_url, resolve=False)
            if any(not re.fullmatch(r'AI_AGENT_SECRET_[A-Z0-9_]{1,80}', value or '')
                   for value in (engine.secret_reference, engine.management_secret_reference)):
                raise ValidationError(_('Use a provisioned credential reference, not a secret.'))

    def write(self, vals):
        if not trusted(self) and {'state', 'revision', 'checked_at', 'capabilities', 'toolsets', 'models_catalog', 'status_message'} & vals.keys():
            raise AccessError(_('Use Check connection to update readiness.'))
        if {'url', 'secret_reference', 'management_url', 'management_secret_reference'} & vals.keys():
            for engine in self:
                super(Engine, engine).write({**vals, 'state': 'unchecked', 'checked_at': False,
                    'capabilities': False, 'toolsets': False, 'models_catalog': False,
                    'revision': engine.revision + 1})
            return True
        return super().write(vals)

    def _request(self, method, path, payload=None, headers=None):
        self.ensure_one()
        return hermes.request(self.url, self.secret_reference, method, path, payload, headers)

    def _inspect(self):
        """Fresh inspection before every submission; discovery never grants execution."""
        health = self._request('GET', '/health/detailed')
        capabilities = self._request('GET', '/v1/capabilities')
        tools = self._request('GET', '/v1/toolsets')
        # Verified local Hermes 6cd2502 wraps discovery in an OpenAI list object.
        # Older documented contracts return a bare list; validate both shapes.
        if isinstance(tools, dict) and tools.get('object') == 'list':
            tools = tools.get('data')
        config = hermes.request(self.management_url, self.management_secret_reference, 'GET', '/api/config')
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

    def action_check(self):
        manager(self)
        for engine in self:
            try:
                capabilities, tools = engine._inspect()
                catalog = engine._request('GET', '/api/model/options')
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
    extracted_text = fields.Text(readonly=True, groups='ai_agent.group_manager')
    state = fields.Selection([('draft', 'Draft'), ('ready', 'Ready'), ('failed', 'Needs attention')], default='draft', readonly=True)
    active = fields.Boolean(default=True)
    user_ids = fields.Many2many('res.users', string='Allowed readers', required=True)
    revision = fields.Integer(default=1, readonly=True)
    status_message = fields.Char(readonly=True)

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
