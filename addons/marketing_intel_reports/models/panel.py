"""The three numbers of the Today page come from the Executive overview, so the page and the report agree."""

from odoo import _, models


class PanelToday(models.AbstractModel):
    _inherit = 'mi.panel'

    def _today_numbers(self, period):
        data = self.env['mi.report.executive'].get_overview(period)
        if data.get('denied'):
            return None
        kpi = {k['key']: k for k in data['kpis']}
        return {'period': period, 'label': data['label'], 'empty': data['empty'], 'tiles': [
            {'label': _('Spend'), 'value': kpi['spend']['value'], 'sub': kpi['spend']['sub']},
            {'label': _('Leads'), 'value': kpi['leads']['value'],
             'sub': _('cost per lead %s', kpi['cpl']['value'])},
            {'label': _('Revenue'), 'value': kpi['revenue']['value'],
             'sub': _('%s revenue per spend', kpi['per_spend']['value']) if kpi['per_spend']['value'] != '—'
             else _('no spend entered')},
        ]}
