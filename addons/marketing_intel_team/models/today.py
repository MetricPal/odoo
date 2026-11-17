"""The Today page by role (approved boards 18.1 to 18.3): the Head of department and the Senior see what needs them,
their numbers, what is running and the team; a Junior sees "My day"."""

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.tools import format_date

from .team import ROLES as ROLE_LABELS, user_role

PER_KIND = 8


class PanelToday(models.AbstractModel):
    _inherit = 'mi.panel'

    @api.model
    def get_today(self, period='quarter'):
        data = super().get_today(period)
        role = user_role(self.env.user) if self._team() else False
        if not role:
            return data
        data.update(role=role, role_label=dict(ROLE_LABELS).get(role, ''))
        if role == 'junior':
            data['title'] = _('My day')
            data['numbers'] = None
            data['junior'] = self._today_junior()
        return data

    # ------------------------------------------------------------------ what needs the person

    def _today_role(self):
        return user_role(self.env.user) if self._team() else False

    def _today_plans(self, active):
        active = super()._today_plans(active)
        if self._today_role() == 'senior':
            users = self._team_users()
            return active.filtered(lambda p: p.user_id in users)
        if self._today_role() == 'junior':
            return active.browse()
        return active

    def _today_attention(self, brands, plans, active):
        role = self._today_role()
        if role == 'junior' or not role:
            return super()._today_attention(brands, plans, active)
        users = self._team_users()
        mine = self._today_plans(active)
        today = fields.Date.context_today(self)
        items = []
        for request in self._my_requests()[:PER_KIND]:
            record = self.env[request.target_model].sudo().browse(request.target_res_id).exists()
            old = request.create_date < fields.Datetime.now() - timedelta(days=2)
            items.append(self._line(
                'approvals', record.display_name if record else request.name,
                _('%(type)s · %(who)s, since %(when)s', type=request.policy_id.name,
                  who=request.requester_id.name or '', when=format_date(self.env, request.create_date)),
                _('Review'), model=request.target_model if record else 'approval.center.request',
                res_id=record.id if record else request.id, tone='danger' if old else 'warn'))
        for task in self._late_tasks(users).sorted('date_deadline')[:PER_KIND]:
            days = max((today - task.date_deadline.date()).days, 1) if task.date_deadline else 1
            items.append(self._line('late', task.name, _('%(who)s · late %(n)s day(s)', who=task.user_ids[:1].name or '-',
                                                          n=days), _('Open'), model='project.task', res_id=task.id,
                                    tone='danger'))
        for plan in mine:
            for item in plan.item_ids.filtered(lambda i: i.stage in ('blocked', 'failed')):
                label = dict(item._fields['channel']._description_selection(self.env))[item.channel]
                items.append(self._line('channels', _('%(channel)s needs fixing in “%(plan)s”', channel=label,
                                                      plan=plan.name), item.next_step or '', _('Fix'),
                                        model='mi.plan', res_id=plan.id, tone='danger'))
        for row in self._automation_rows(brands):
            if row.get('danger'):
                items.append(self._line('automations', _('Automation failing: %s', row['title']), row['subtitle'],
                                        _('See why'), model=row['model'], res_id=row['res_id'], tone='danger'))
        if role == 'hod':
            setup = self._block_setup(brands, plans)
            for row in (setup or {}).get('rows', []):
                items.append(self._line('setup', row['title'], '', row['value'], model=row.get('model', False),
                                        res_id=row.get('res_id', False), action=row.get('action', False), tone='info'))
        return items

    # ------------------------------------------------------------------ the side column

    def _today_side(self, brands, plans, active, now):
        side = super()._today_side(brands, plans, active, now)
        role = self._today_role()
        if not role or role == 'junior':
            return side
        users = self._team_users()
        employees = self._team().sudo().member_ids.filtered('user_id')
        employees = employees.filtered(lambda e: e.user_id in users)
        order = {'hod': 0, 'senior': 1}
        roles = dict(ROLE_LABELS)
        side['team'] = [{'name': e.name, 'role': roles.get(user_role(e.user_id), ''),
                         'open': len(self._open_tasks(e.user_id)), 'late': len(self._late_tasks(e.user_id))}
                        for e in employees.sorted(lambda e: (order.get(user_role(e.user_id), 2), e.name or ''))]
        flows = self._automation_rows(brands)
        usage = self._ai_usage()
        side['assistant'] = {'workflows': len(flows), 'failing': len([f for f in flows if f.get('danger')]),
                             'questions': usage['total'] if usage else None,
                             'failed': usage['failed'] if usage else None}
        if role == 'hod':
            side['setup'] = self._today_setup(brands, plans)
        return side

    def _today_setup(self, brands, plans):
        """"Setup 5 of 8": the checks the setup block makes, how many pass, and what is left."""
        rows = (self._block_setup(brands, plans) or {}).get('rows', [])
        total = 1 + len(brands)
        if 'mm.list' in self.env:
            total += 1
        if 'mm.whatsapp.template' in self.env:
            numbers = self.env['omni.channel'].sudo().search_count([
                ('channel_type_id.code', '=', 'whatsapp'), ('company_id', 'in', self.env.companies.ids)])
            total += numbers + (1 if numbers else 0)
        if 'omni.social.connection' in self.env:
            total += 1
        total = max(total, len(rows))
        return {'done': total - len(rows), 'total': total, 'left': list(dict.fromkeys(row.get('short') or row['title'] for row in rows))[:4],
                'action': 'marketing_intel_team.action_mi_department' if rows else False}

    # ------------------------------------------------------------------ "My day"

    def _today_junior(self):
        brands = self.env['mi.brand'].search([])
        plans = self.env['mi.plan'].search([('brand_id', 'in', brands.ids), ('is_template', '=', False)])
        prepared = self._block_prepared(brands, plans)
        going = self._block_going_out(brands, plans)
        review = self._block_my_reviews(brands, plans)
        results = self._block_my_results(brands, plans)
        make = self._block_make(brands, plans)
        return {'prepared': prepared.get('rows', []), 'going_out': going.get('rows', []),
                'in_review': review.get('rows', []), 'results': results.get('tiles', []),
                'make': make.get('buttons', [])}
