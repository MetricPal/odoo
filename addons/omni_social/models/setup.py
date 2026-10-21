"""Guided account setup: Platform → Connect → Who approves → Receiving → Ready.

Each step is a plain form section with Back / Continue buttons that check only
what that step needs, so a person always knows the one thing left to do.
Accounts created before this flow keep ``setup_step = 'done'``.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.omni_channel.models.foundation import boolean_search_values
from .social import internal
from ..providers.registry import capabilities, installed

STEPS = [
    ('platform', 'Platform'),
    ('connect', 'Connect'),
    ('approval', 'Who approves'),
    ('receiving', 'Receiving'),
    ('done', 'Ready'),
]
ORDER = [key for key, _label in STEPS]


class Connection(models.Model):
    _inherit = 'omni.social.connection'

    setup_step = fields.Selection(STEPS, default='done', required=True, copy=False, string='Setup step')
    approval_problem = fields.Char(compute='_compute_approval_problem')
    platform_note = fields.Char(compute='_compute_platform_note')

    @api.depends('provider')
    def _compute_platform_note(self):
        for row in self:
            caps = capabilities(row.provider)
            row.platform_note = caps.summary() if caps else ''

    @api.depends(
        'approval_type_id', 'approval_type_id.active', 'approval_type_id.manager_approval',
        'approval_type_id.approver_ids', 'approval_type_id.approval_minimum', 'purpose_id', 'company_id',
    )
    def _compute_approval_problem(self):
        for row in self:
            row.approval_problem = row._approval_problem() or ''

    def _approval_problem(self):
        """Why the chosen approval type cannot review this account's posts, in plain words."""
        self.ensure_one()
        policy = self.approval_type_id.sudo()
        if not policy:
            return _('Choose who approves posts from this account.')
        if not policy.active:
            return _('This approval type is archived.')
        if policy.company_id and policy.company_id != self.company_id:
            return _('This approval type belongs to another company.')
        if policy.manager_approval:
            return _("Turn off \"Requester's manager approves\": social posts need named approvers.")
        if policy.model:
            return _('Choose an approval type without a backend action.')
        lines = policy.approver_ids
        if not lines:
            return _('Add at least one approver to this approval type.')
        if policy.approval_minimum > len(lines):
            return _('This approval type needs more approvers than it lists.')
        outside = lines.user_id.filtered(
            lambda u: u not in self.purpose_id.user_ids
            or not u.has_group('approval_center.group_approval_center_approver')
            or u.share
        )
        if outside:
            return _(
                '%(names)s must be in the team "%(team)s" and allowed to approve.',
                names=', '.join(outside.mapped('name')), team=self.purpose_id.display_name or '',
            )
        if len(lines) == 1 and len(self.purpose_id.user_ids) <= 1:
            return _('Authors cannot approve their own posts; add a second person to the team.')
        return False

    # ---- navigation ------------------------------------------------------

    def _go(self, step):
        internal(self.sudo()).write({'setup_step': step})
        return self._setup_action()

    def _setup_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('omni_social.connection_setup_form').id, 'form')],
            'target': 'current',
        }

    def action_setup_back(self):
        self.ensure_one()
        self._require_manager()
        index = ORDER.index(self.setup_step)
        return self._go(ORDER[max(index - 1, 0)])

    def action_setup_next(self):
        self.ensure_one()
        self._require_manager()
        step = self.setup_step
        if step == 'platform':
            if self.provider == 'unavailable' or self.provider not in installed(self.env):
                raise UserError(_('Choose a platform.'))
            if not self.purpose_id:
                raise UserError(_('Choose the team that will use this account.'))
        elif step == 'connect' and not self.connected:
            raise UserError(_('Connect the account first: sign in with the platform or paste a token.'))
        elif step == 'approval':
            problem = self._approval_problem()
            if problem:
                raise UserError(problem)
        if step == 'done':
            return self.action_setup_finish()
        return self._go(ORDER[ORDER.index(step) + 1])

    def action_setup_finish(self):
        self.ensure_one()
        self._require_manager()
        internal(self.sudo()).write({'setup_step': 'done'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('omni_social.connection_form').id, 'form')],
            'target': 'current',
        }

    def action_open_setup(self):
        """Resume (or reopen) the guided setup for this account."""
        self.ensure_one()
        self._require_manager()
        if self.setup_step == 'done' and not self.connected:
            return self._go('connect')
        return self._setup_action()

    def action_new_approval_type(self):
        """Open a new approval type prefilled for this account, in a dialog."""
        self.ensure_one()
        self._require_manager()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New approval type'),
            'res_model': 'approval.center.policy',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_name': _('%(account)s posts', account=self.name),
                'default_company_id': self.company_id.id,
                'default_manager_approval': False,
                'social_connection_id': self.id,
            },
        }


class ApprovalPolicy(models.Model):
    _inherit = 'approval.center.policy'

    @api.model_create_multi
    def create(self, values):
        records = super().create(values)
        connection_id = self.env.context.get('social_connection_id')
        if connection_id and len(records) == 1:
            connection = self.env['omni.social.connection'].browse(connection_id).exists()
            if connection and not connection.approval_type_id:
                connection.approval_type_id = records
        return records


class ChannelType(models.Model):
    _inherit = 'omni.channel.type'

    social_rules = fields.Char(compute='_compute_social_rules')

    def _search_social_ready(self, operator, value):
        values = boolean_search_values(operator, value)
        if values is None:
            return NotImplemented
        if values == {True, False}:
            return []
        if not values:
            return [('id', 'in', [])]
        return [('code', 'in' if True in values else 'not in', installed(self.env))]

    def _compute_social_rules(self):
        for row in self:
            caps = capabilities(row.code) if row.social_ready else None
            row.social_rules = caps.summary().split(': ', 1)[-1] if caps else ''

    def action_social_connect(self):
        """Start the guided setup for this platform."""
        self.ensure_one()
        if not self.social_ready:
            raise UserError(_('This platform needs its connector module first.'))
        self.env['omni.social.connection']._require_manager()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'omni.social.connection',
            'view_mode': 'form',
            'views': [(self.env.ref('omni_social.connection_setup_form').id, 'form')],
            'target': 'current',
            'context': {
                'default_provider': self.code,
                'default_name': self.name,
                'default_setup_step': 'platform',
            },
        }
