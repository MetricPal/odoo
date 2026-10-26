"""Work on the control panel's to-do list: my campaign tasks due soon, proofs to review, requests to answer."""

from datetime import timedelta

from odoo import _, fields, models
from odoo.tools import format_date


class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    def _activity_models(self):
        return super()._activity_models() + ['mi.proof', 'mi.request']

    def _activity_icon(self, model):
        return {'mi.proof': 'edit', 'mi.request': 'forum'}.get(model) or super()._activity_icon(model)

    def _extra_todos(self, brands, plans):
        """My campaign tasks due within a week (Project tasks, not activities)."""
        todos = super()._extra_todos(brands, plans)
        soon = fields.Datetime.now() + timedelta(days=7)
        tasks = self.env['project.task'].search([
            ('mi_plan_id.brand_id', 'in', brands.ids), ('user_ids', 'in', self.env.user.ids), ('is_closed', '=', False),
            ('mi_plan_id.is_template', '=', False), '|', ('date_deadline', '=', False), ('date_deadline', '<=', soon)],
            order='date_deadline', limit=20)
        for task in tasks:
            when = fields.Datetime.context_timestamp(self, task.date_deadline).strftime('%d %b') \
                if task.date_deadline else _('no due date')
            todos.append({'title': _('Task: %s', task.name), 'subtitle': '%s · %s' % (task.mi_plan_id.name, when),
                          'model': 'project.task', 'res_id': task.id, 'icon': 'checklist'})
        return todos

    def _extra_blocks(self, keys, brands, plans):
        data = super()._extra_blocks(keys, brands, plans)
        if 'workload' in keys:
            rows = {}
            for line in self.env['mi.workload'].search([('brand_id', 'in', brands.ids)]):
                row = rows.setdefault(line.user_id, {'tasks': 0, 'hours': 0.0, 'late': 0, 'campaigns': 0, 'proofs': 0})
                row['tasks' if line.kind == 'task' else ('campaigns' if line.kind == 'campaign' else 'proofs')] += 1
                row['hours'] += line.hours
                row['late'] += int(line.late)
            data['workload'] = {
                'title': _('Team workload'), 'icon': 'group', 'empty': _('Nobody has open marketing work.'),
                'action': 'marketing_intel_work.action_workload', 'action_label': _('Details'),
                'rows': [{'title': user.name, 'subtitle': _('%(c)s campaign(s) · %(t)s task(s) · %(p)s proof(s) to review',
                                                            c=row['campaigns'], t=row['tasks'], p=row['proofs']),
                          'value': _('%(late)s late', late=row['late']) if row['late'] else
                          _('%(h)s h planned', h=round(row['hours'], 1)), 'danger': bool(row['late']),
                          'model': 'res.users', 'res_id': False}
                         for user, row in sorted(rows.items(), key=lambda pair: -(pair[1]['tasks'] + pair[1]['campaigns']))],
            }
        if 'requests' in keys:
            requests_ = self.env['mi.request'].search([('brand_id', 'in', brands.ids), ('state', 'in', ('new', 'accepted'))],
                                                      limit=15)
            data['requests'] = {
                'title': _('Open requests'), 'icon': 'inbox', 'empty': _('No open requests.'),
                'action': 'marketing_intel_work.action_requests', 'action_label': _('All requests'),
                'rows': [{'title': r.name, 'subtitle': '%s · %s' % (r.brand_id.name, r.requested_by.name or '-'),
                          'value': format_date(self.env, r.wanted_by) if r.wanted_by else '',
                          'danger': bool(r.wanted_by and r.wanted_by < fields.Date.context_today(self)),
                          'model': 'mi.request', 'res_id': r.id} for r in requests_],
            }
        return data


class PanelLayout(models.Model):
    _inherit = 'mi.panel.layout'

    def _catalogue(self):
        catalogue = super()._catalogue()
        catalogue.update({'workload': _('Team workload'), 'requests': _('Open requests')})
        return catalogue

    def _default_blocks(self, role):
        blocks = super()._default_blocks(role)
        if role == 'manager':
            blocks.insert(2, {'key': 'workload', 'width': 'half'})
        blocks.insert(len(blocks) - 1, {'key': 'requests', 'width': 'half'})
        return blocks
