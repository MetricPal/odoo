"""Insights overview and app reports (administrators for now): every insight rule, and per app the cards, charts and
records behind its insights. Read with the viewer's own rights, like Home."""

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

REPORT_ROWS = 50


class AiHomeInsight(models.Model):
    _inherit = 'ai.home.insight'

    def _check_report_access(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Insight reports are for administrators for now.'))

    def _history(self, days=30):
        """The viewer's daily values for the rule, oldest first, one per day (missing days repeat the last value)."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        start = today - timedelta(days=days - 1)
        values = {snap.date: snap.value for snap in self.env['ai.home.insight.snapshot'].sudo().search(
            [('insight_id', '=', self.id), ('user_id', '=', self.env.uid), ('date', '>=', start)])}
        series, last = [], None
        for offset in range(days):
            day = start + timedelta(days=offset)
            last = values.get(day, last)
            series.append(last)
        return series

    def _now(self):
        """(number shown, numeric value) for the viewer."""
        self.ensure_one()
        if self.measure == 'completeness':
            scored = self._completeness()
            return f"{scored['percent']}%", len(scored['under'])
        if self.measure == 'check':
            count = self._run_check()[0]
            return str(count), count
        count = self._measure()[0]
        return str(count), count

    @api.model
    def get_insights_overview(self):
        self._check_report_access()
        rows = []
        for rule in self.search([]):
            if not rule._usable():
                continue
            try:
                shown, value = rule._now()
            except AccessError:
                continue
            history = rule._history()
            before = history[0] if rule.measure != 'completeness' else None  # completeness: now is a percent
            rows.append({
                'key': f'insight-{rule.id}', 'insightId': rule.id, 'name': rule.name, 'app': rule.app_label,
                'priority': rule.priority, 'tone': rule.tone, 'now': shown, 'value': value,
                'before': '' if before is None else str(int(before)),
                'spark': [v or 0 for v in history],
            })
        order = {'act_soon': 0, 'incomplete': 1, 'going_well': 2, 'system': 3}
        rows.sort(key=lambda row: (order.get(row['priority'], 9), row['value'] == 0, row['app']))
        labels = dict(self._fields['priority'].selection)
        groups = [{'key': key, 'label': labels[key], 'count': sum(1 for r in rows if r['priority'] == key and r['value'])}
                  for key in order]
        decisions = len(self.env['ai.home.item']._home_attention()[0])
        return {'rows': rows, 'groups': groups, 'decisions': decisions}

    @api.model
    def get_app_report(self, app_label, insight_id=False):
        """Cards for the app's insights, charts for the selected one, and the records behind it."""
        self._check_report_access()
        rules = self.search([('app_label', '=', app_label)]).filtered(lambda rule: rule._usable())
        if not rules:
            raise AccessError(_('No insights for %s.', app_label))
        cards = []
        for rule in rules:
            shown, value = rule._now()
            cards.append({'insightId': rule.id, 'name': rule.name, 'now': shown, 'value': value,
                          'tone': rule.tone, 'measure': rule.measure})
        selected = rules.filtered(lambda r: r.id == int(insight_id)) if insight_id else self.browse()
        if not selected:
            # The first rule with something to show, else the first.
            selected = next((rule for rule, card in zip(rules, cards) if card['value']), rules[:1])
        return {'app': app_label, 'cards': cards, 'selected': selected._report_detail()}

    def _report_detail(self):
        self.ensure_one()
        Model = self.env[self.model_name]
        detail = {'insightId': self.id, 'name': self.name, 'measure': self.measure, 'threshold': self.threshold,
                  'trend': [v or 0 for v in self._history()], 'bands': [], 'missingCounts': [], 'columns': [],
                  'rows': [], 'total': 0}
        if self.measure == 'completeness':
            scored = self._completeness()
            lines = self.field_ids.filtered(lambda line: line.field_name in Model._fields and line.weight > 0)
            detail.update(bands=scored['bands'], missingCounts=scored['missingCounts'], total=len(scored['under']))
            detail['columns'] = [{'key': line.field_name, 'label': line.label or Model._fields[line.field_name].string}
                                 for line in lines[:6]]
            records = Model.browse(sorted(scored['under'], key=lambda rid: scored['scores'].get(rid, 0))[:REPORT_ROWS])
            for record in records:
                empty = scored['empty'].get(record.id, [])
                detail['rows'].append({
                    'id': record.id, 'name': record.display_name, 'score': scored['scores'].get(record.id, 0),
                    'cells': [{'key': c['key'], 'missing': c['key'] in empty,
                               'value': self._cell(record, c['key'])} for c in detail['columns']],
                })
        else:
            if self.measure == 'check':
                _count, _detail, model, domain = self._run_check()
                Model = self.env[model].sudo()
            else:
                domain = self._domain()
            detail['total'] = Model.search_count(domain)
            extra = [name for name in ('user_id', 'partner_id', 'date_deadline', 'create_date') if name in Model._fields][:3]
            detail['columns'] = [{'key': name, 'label': Model._fields[name].string} for name in extra]
            for record in Model.search(domain, limit=REPORT_ROWS):
                detail['rows'].append({'id': record.id, 'name': record.display_name, 'score': None,
                                       'cells': [{'key': name, 'missing': False, 'value': self._cell(record, name)}
                                                 for name in extra]})
        detail['model'] = Model._name
        return detail

    def _cell(self, record, name):
        value = record[name]
        field = record._fields[name]
        if not value:
            return ''
        if field.type in ('many2one',):
            return value.display_name
        if field.type in ('one2many', 'many2many'):
            return ', '.join(value[:3].mapped('display_name')) + ('…' if len(value) > 3 else '')
        if field.type == 'datetime':
            return fields.Date.to_string(fields.Datetime.context_timestamp(record, value).date())
        if field.type in ('html', 'text', 'binary'):
            return '✓'
        return str(value)

    @api.model
    def report_apps(self):
        """App labels that have insights the viewer can use (for linking the Apps table to reports)."""
        return sorted({rule.app_label for rule in self.search([]) if rule._usable()})
