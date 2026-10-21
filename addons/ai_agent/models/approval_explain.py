"""Ask AI to explain an approval request (read-only)."""
from odoo import _, models
from odoo.exceptions import UserError


class ApprovalRequestExplain(models.Model):
    _inherit = 'approval.center.request'

    def _ai_explain_prompt(self):
        """Plain-text summary of what the user can already see on the request."""
        self.ensure_one()
        lines = [
            _('Explain this approval request and what I should check before deciding.'),
            _('Do not approve or refuse anything; only explain and point out risks or missing information.'),
            '',
            _('Subject: %s', self.name),
            _('Category: %s', self.policy_id.display_name),
            _('Requester: %s', self.requester_id.display_name),
            _('Status: %s', dict(self._fields['state']._description_selection(self.env)).get(self.state)),
        ]
        optional = [
            ('amount', _('Amount: %s %s'), lambda r: (r.amount, r.currency_id.name or '')),
            ('partner_id', _('Contact: %s'), lambda r: (r.partner_id.display_name,)),
            ('date', _('Date: %s'), lambda r: (r.date,)),
            ('date_start', _('Period: %s to %s'), lambda r: (r.date_start, r.date_end)),
            ('item', _('Items: %s'), lambda r: (r.item,)),
            ('quantity', _('Quantity: %s'), lambda r: (r.quantity,)),
            ('reference', _('Reference: %s'), lambda r: (r.reference,)),
            ('location', _('Location: %s'), lambda r: (r.location,)),
        ]
        for name, template, values in optional:
            if self[name]:
                lines.append(template % values(self))
        if self.reason:
            lines.append(_('Description: %s', self.reason))
        decisions = ', '.join(
            f"{line.user_id.display_name} ({dict(line._fields['status']._description_selection(self.env)).get(line.status)})"
            for line in self.approver_ids.sorted(lambda line: (line.sequence, line.id))
        )
        if decisions:
            lines.append(_('Approvers: %s', decisions))
        return '\n'.join(str(line) for line in lines)[:12000]

    def action_ai_explain(self):
        """Open the Ask AI dialog prefilled; nothing is sent until the user clicks Send."""
        self.ensure_one()
        self.check_access('read')
        agents = self.env['ai.agent'].search([('state', '=', 'active'), ('can_chat', '=', True)])
        if not agents:
            raise UserError(_('No AI assistant is available to you. Ask an AI Agent manager to give you access.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ai.agent.ask',
            'views': [(False, 'form')],
            'target': 'new',
            'name': _('Ask AI about this request'),
            'context': {
                'default_agent_id': agents[:1].id if len(agents) == 1 else False,
                'default_prompt': self._ai_explain_prompt(),
            },
        }
