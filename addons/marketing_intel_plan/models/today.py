"""The Marketing home page, "Today" (approved boards 18.1 to 18.3, 2026-11-17): what needs the person first, a few
numbers, what is running, and the side column. One call; read-only; the people and roles come from the team module,
the numbers from the reports module, the assistant button from the AI module (each adds its part here).
"""

from datetime import datetime

from odoo import _, api, fields, models
from odoo.tools import format_date, formatLang

from .plan import ACTIVE, STAGES
from .portfolio import health_of

# The kinds of line in "Needs your attention", in the order they are shown, with the chip each has.
KINDS = [('approvals', 'Approvals'), ('late', 'Late'), ('todo', 'To do'), ('channels', 'Channels'),
         ('alerts', 'Alerts'), ('automations', 'Automations'), ('setup', 'Setup')]
RUNNING_LIMIT = 6
COMING_LIMIT = 4
ATTENTION_LIMIT = 30


class PanelToday(models.AbstractModel):
    _inherit = 'mi.panel'

    @api.model
    def get_today(self, period='quarter'):
        period = period if period in ('month', 'quarter', 'year') else 'quarter'
        brands = self.env['mi.brand'].search([])
        plans = self.env['mi.plan'].search([('brand_id', 'in', brands.ids), ('is_template', '=', False)])
        active = plans.filtered(lambda p: p.state in ACTIVE)
        now = fields.Datetime.now()
        items = self._today_attention(brands, plans, active)
        counts = {kind: len([i for i in items if i['kind'] == kind]) for kind, _label in KINDS}
        return {
            'role': 'default', 'role_label': '', 'title': _('Marketing'),
            'today': format_date(self.env, fields.Date.context_today(self)),
            'assistant': False, 'period': period,
            'attention': {'items': items[:ATTENTION_LIMIT], 'total': len(items),
                          'chips': [{'kind': k, 'label': dict(KINDS_LABELS(self))[k], 'count': counts[k]}
                                    for k, _label in KINDS if counts[k]]},
            'numbers': self._today_numbers(period),
            'running': self._today_running(self._today_plans(active)),
            'side': self._today_side(brands, plans, active, now),
            'junior': None,
        }

    # ------------------------------------------------------------------ the parts (the other modules extend them)

    def _today_plans(self, active):
        """The campaigns "Running now" lists (a Senior: their team's)."""
        return active

    def _today_attention(self, brands, plans, active):
        items = []
        for todo in self._todos(brands, plans):
            items.append(self._line('late' if todo['late'] else 'todo', todo['title'], todo['subtitle'],
                                    _('Open'), model=todo['model'], res_id=todo['res_id'],
                                    tone='danger' if todo['late'] else 'info'))
        for alert in self._alerts(brands, active):
            items.append(self._line('alerts', alert['text'], '', _('Open'), model=alert['model'],
                                    res_id=alert['res_id'], tone='danger' if alert['level'] == 'danger' else 'warn'))
        return items

    def _today_numbers(self, period):
        """The three numbers (Spend, Leads, Revenue); the reports module fills them."""
        return None

    def _today_side(self, brands, plans, active, now):
        return {'setup': None, 'team': [], 'assistant': None, 'coming': self._today_coming(plans, now)}

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _line(kind, title, detail, label, model=False, res_id=False, action=False, tone='warn'):
        return {'kind': kind, 'title': title, 'detail': detail, 'label': label, 'tone': tone,
                'target': {'model': model, 'res_id': res_id, 'action': action}}

    def _today_money(self, amount, plan=None):
        currency = plan.currency_id if plan else self.env.company.currency_id
        return formatLang(self.env, amount or 0.0, currency_obj=currency, digits=0)

    def _today_running(self, plans):
        stages = dict(STAGES)
        rows = []
        for plan in plans:
            fix = len(plan.item_ids.filtered(lambda i: i.stage in ('blocked', 'failed')))
            health, _reasons = health_of(plan.budget, plan.budget, plan.spent, 0, fix)
            rows.append({
                'id': plan.id, 'name': plan.name, 'brand': plan.brand_id.name, 'owner': plan.user_id.sudo().name or '',
                'stage': stages.get(plan.state, plan.state), 'health': health,
                'ends': format_date(self.env, plan.date_end, date_format='d MMM') if plan.date_end else '',
                'spent': self._today_money(plan.spent, plan), 'budget': self._today_money(plan.budget, plan),
                '_sort': (('off_track', 'at_risk', 'on_track').index(health), plan.date_end or datetime.max.date()),
            })
        rows.sort(key=lambda r: r['_sort'])
        for row in rows:
            del row['_sort']
        return rows[:RUNNING_LIMIT]

    def _today_coming(self, plans, now):
        events = self._timeline(plans, now)['upcoming'][:COMING_LIMIT]
        out = []
        for event in events:
            at = fields.Datetime.to_datetime(event['at'])
            out.append({'when': format_date(self.env, at, date_format='EEE d'), 'title': event['title'],
                        'subtitle': event['subtitle'], 'model': event['model'], 'res_id': event['res_id']})
        return out


def KINDS_LABELS(panel):
    """The chip labels, translated."""
    return [('approvals', _('Approvals')), ('late', _('Late')), ('todo', _('To do')), ('channels', _('Channels')),
            ('alerts', _('Alerts')), ('automations', _('Automations')), ('setup', _('Setup'))]
