"""Workflows on the Marketing control panel: their runs today, the timeline and what needs attention."""

from datetime import datetime, time

from odoo import _, fields, models


class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    def _flows(self, brands):
        flows = self.env['mi.flow'].search([('brand_id', 'in', brands.ids)])
        return [{'id': f.id, 'name': f.name, 'brand': f.brand_id.name, 'state': f.state,
                 'state_label': dict(f._fields['state']._description_selection(self.env))[f.state],
                 'summary': f.summary, 'runs': f.runs_today, 'sent': f.sent_today, 'skipped': f.skipped_today,
                 'failed': f.failed_today, 'total': f.run_count} for f in flows]

    def _flow_events(self, brands, since):
        Run = self.env['mi.flow.run'].sudo()
        events = []
        rows = Run._read_group([('brand_id', 'in', brands.ids), ('create_date', '>=', since)],
                               ['flow_id', 'create_date:day'], ['__count'])
        for flow, day, count in rows:
            day = day.date() if isinstance(day, datetime) else day
            messages = Run.search([('flow_id', '=', flow.id), ('create_date', '>=', datetime.combine(day, time.min)),
                                   ('create_date', '<=', datetime.combine(day, time.max))]).mapped('message_count')
            events.append({'at': fields.Datetime.to_string(datetime.combine(day, time(12, 0))), 'all_day': True, 'future': False,
                           'kind': 'flow', 'title': _('%(name)s: %(runs)s run(s), %(sent)s message(s)', name=flow.name,
                                                      runs=count, sent=sum(messages)),
                           'subtitle': flow.brand_id.name, 'model': 'mi.flow', 'res_id': flow.id, 'icon': 'flash_on',
                           'recurring': True})
        return events

    def _activity_models(self):
        return super()._activity_models() + ['mi.flow']

    def _approval_target_models(self):
        return super()._approval_target_models() + ['mi.flow']

    def _activity_icon(self, model):
        return 'flash_on' if model == 'mi.flow' else super()._activity_icon(model)

    def _flow_alerts(self, brands):
        return [{'level': 'danger', 'text': _('Workflow “%(name)s”: %(n)s error(s) today', name=f.name, n=f.failed_today),
                 'model': 'mi.flow', 'res_id': f.id}
                for f in self.env['mi.flow'].search([('brand_id', 'in', brands.ids), ('state', '=', 'active')])
                if f.failed_today]
