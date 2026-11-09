"""Capacity of the shared assistant (ADR 0014): daily limits per source, and models paused after a failure."""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .common import internal, manager, trusted
from .conversation import CALLERS


def _today():
    return fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


class CallerLimit(models.Model):
    _name = 'ai.agent.caller.limit'
    _description = 'AI agent daily limit by source'
    _order = 'caller'

    agent_id = fields.Many2one('ai.agent', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='agent_id.company_id', store=True)
    caller = fields.Selection(CALLERS, string='Asked from', required=True)
    daily_limit = fields.Integer(string='Requests per day', required=True, default=50)
    used_today = fields.Integer(compute='_compute_used_today', string='Used today')
    reached = fields.Boolean(compute='_compute_used_today')
    reached_label = fields.Char(compute='_compute_used_today')

    _unique_caller = models.Constraint('UNIQUE(agent_id, caller)', 'Each source has one daily limit per agent.')

    @api.depends('agent_id', 'caller', 'daily_limit')
    def _compute_used_today(self):
        counts = {}
        if self.agent_id:
            for agent, caller, count in self.env['ai.agent.run'].sudo()._read_group(
                    [('agent_id', 'in', self.agent_id.ids), ('create_date', '>=', _today())],
                    ['agent_id', 'caller'], ['__count']):
                counts[agent.id, caller] = count
        for limit in self:
            limit.used_today = counts.get((limit.agent_id.id, limit.caller), 0)
            limit.reached = bool(limit.daily_limit) and limit.used_today >= limit.daily_limit
            limit.reached_label = _('reached') if limit.reached else False

    @api.constrains('daily_limit')
    def _check_daily_limit(self):
        if any(not 1 <= limit.daily_limit <= 1000 for limit in self):
            raise ValidationError(_('Use 1–1000 requests per day for a source.'))

    def _check_change(self, agents):
        """Same rule as the agent's other request limits: AI Agent managers, on a paused agent."""
        if trusted(self):
            return
        manager(agents)
        if any(agent.state == 'active' for agent in agents):
            raise UserError(_('Pause the agent before changing its configuration.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_change(self.env['ai.agent'].browse({v.get('agent_id') for v in vals_list if v.get('agent_id')}))
        return super().create(vals_list)

    def write(self, vals):
        self._check_change(self.agent_id)
        if 'agent_id' in vals and any(limit.agent_id.id != vals['agent_id'] for limit in self):
            raise AccessError(_('A limit stays with its agent.'))
        return super().write(vals)

    def unlink(self):
        self._check_change(self.agent_id)
        return super().unlink()


class ModelPause(models.Model):
    _name = 'ai.agent.model.pause'
    _description = 'AI model paused after a provider failure'
    _order = 'until desc'

    engine_id = fields.Many2one('ai.agent.engine', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='engine_id.company_id', store=True)
    model_key = fields.Char(required=True, readonly=True, help='provider/model, or default/<profile>.')
    name = fields.Char(string='Model', compute='_compute_name')
    until = fields.Datetime(string='Paused until', required=True, readonly=True)
    until_label = fields.Char(string='Paused until', compute='_compute_until_label')
    reason = fields.Text(string='What Hermes said', readonly=True)
    run_id = fields.Many2one('ai.agent.run', string='Run', readonly=True, ondelete='set null')

    _unique_model = models.Constraint('UNIQUE(engine_id, model_key)', 'One pause per model and connection.')

    @api.depends('model_key')
    def _compute_name(self):
        for pause in self:
            kind, _sep, rest = (pause.model_key or '').partition('/')
            pause.name = (_('Default model (%s)', rest) if rest else _('Default model')) if kind == 'default' \
                else '%s · %s' % (kind, rest)

    @api.depends_context('tz')
    @api.depends('until')
    def _compute_until_label(self):
        now = fields.Datetime.now()
        for pause in self:
            minutes = max(0, int((pause.until - now).total_seconds() // 60)) if pause.until else 0
            local = fields.Datetime.context_timestamp(pause, pause.until) if pause.until else None
            pause.until_label = _('%(time)s (in %(minutes)s min)', time=local.strftime('%H:%M'), minutes=minutes) \
                if local else ''

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            raise AccessError(_('Models are paused by the runs job only.'))
        return super().create(vals_list)

    def write(self, vals):
        if not trusted(self):
            raise AccessError(_('Use Resume.'))
        return super().write(vals)

    @api.model
    def _pause(self, engine, model_key, minutes, reason, run):
        until = fields.Datetime.now() + timedelta(minutes=minutes)
        pause = self.sudo().search([('engine_id', '=', engine.id), ('model_key', '=', model_key)], limit=1)
        values = {'until': until, 'reason': reason, 'run_id': run.id}
        if pause:
            internal(pause).write(values)
        else:
            pause = internal(self.sudo()).create({**values, 'engine_id': engine.id, 'model_key': model_key})
        return pause

    @api.model
    def _active(self, engine, model_key):
        return self.sudo().search([('engine_id', '=', engine.id), ('model_key', '=', model_key),
                                   ('until', '>', fields.Datetime.now())], limit=1)

    def action_resume(self):
        """End the pause now (AI Agent managers), recorded on the run that caused it."""
        manager(self.engine_id)
        for pause in self:
            internal(pause.sudo()).write({'until': fields.Datetime.now()})
            if pause.run_id:
                pause.run_id.sudo()._event('model_resumed', _('%(model)s resumed by %(user)s.', model=pause.name,
                                                              user=self.env.user.name))
        return True

    def action_open_run(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ai.agent.run', 'res_id': self.run_id.id,
                'view_mode': 'form', 'target': 'current'}
