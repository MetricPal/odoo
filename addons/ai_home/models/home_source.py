"""Decision sources: one record per app says which of its records wait for the user's decision on Home.

A source is only used when its model is installed and the user is in its group. Records are searched with the user's
own rights. Its buttons may only call public ``action_*`` / ``button_*`` methods of that model, and only on a record the
source currently lists for the user, so the app's own checks (approver, manager, state) still decide.
"""

import re
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import formatLang
from odoo.tools.safe_eval import safe_eval

METHOD_PATTERN = re.compile(r'^(action|button)_[a-z0-9_]+$')
SEARCH_LIMIT = 100


class AiHomeSource(models.Model):
    _name = 'ai.home.source'
    _description = 'Home decision source'
    _order = 'sequence, id'

    name = fields.Char('App', required=True, translate=True, help='Shown as the filter chip and in each row.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_name = fields.Char('Model', required=True, help='Technical name, e.g. hr.leave. Ignored while not installed.')
    domain = fields.Char(default='[]', required=True,
                         help='Records waiting for the user. Available: uid, today, tomorrow (dates as text).')
    check_fields = fields.Char('Must be true (any of)',
                               help='Comma-separated boolean fields; at least one must be true, e.g. can_approve.')
    group_xmlid = fields.Char('Group', help='External ID of the group the user needs, e.g. purchase.group_purchase_manager.')
    title_field = fields.Char(help='Field shown as the title. Empty: the record name.')
    detail_field = fields.Char(help='Field shown after the app name, e.g. employee_id or partner_id.')
    amount_field = fields.Char(help='Monetary field shown in the row, e.g. amount_total.')
    date_field = fields.Char(help='Date the row is sorted and labelled by.')
    date_mode = fields.Selection([('waiting', 'Waiting since'), ('due', 'Due on')], default='waiting', required=True)
    badge = fields.Char(size=2, help='Two letters in the row badge.')
    primary_label = fields.Char(translate=True)
    primary_method = fields.Char(help='Public action_* or button_* method. Empty: the button opens the record.')
    secondary_label = fields.Char(translate=True)
    secondary_method = fields.Char()
    limit = fields.Integer(default=5, help='Rows shown on Home; the rest open with "Open all".')

    @api.constrains('primary_method', 'secondary_method')
    def _check_methods(self):
        for source in self:
            for method in (source.primary_method, source.secondary_method):
                if method and not METHOD_PATTERN.match(method):
                    raise ValidationError(_('Buttons may only call action_* or button_* methods (got %s).', method))
                if method and source.model_name in self.env and not callable(getattr(self.env[source.model_name], method, None)):
                    raise ValidationError(_('%(model)s has no method %(method)s.', model=source.model_name, method=method))

    @api.constrains('domain')
    def _check_domain(self):
        for source in self:
            try:
                domain = safe_eval(source.domain or '[]', source._eval_context())
            except Exception as error:  # noqa: BLE001 - any error means the text is not a domain
                raise ValidationError(_('The domain of %(name)s is not valid: %(error)s', name=source.name, error=error))
            if not isinstance(domain, (list, tuple)):
                raise ValidationError(_('The domain of %s must be a list.', source.name))

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _eval_context(self):
        today = fields.Date.context_today(self)
        return {'uid': self.env.uid, 'today': fields.Date.to_string(today),
                'tomorrow': fields.Date.to_string(today + timedelta(days=1))}

    def _usable(self):
        """The model is installed, the user is in the group and may read the model."""
        self.ensure_one()
        if self.model_name not in self.env or not self.env[self.model_name].has_access('read'):
            return False
        if self.group_xmlid:
            group = self.env.ref(self.group_xmlid, raise_if_not_found=False)
            if not group or group not in self.env.user.all_group_ids:
                return False
        return True

    def _records(self):
        """Every record this source lists for the current user (up to SEARCH_LIMIT), oldest first."""
        self.ensure_one()
        if not self._usable():
            return False
        Model = self.env[self.model_name]
        order = 'id'
        if self.date_field in Model._fields and Model._fields[self.date_field].store:
            order = f'{self.date_field} asc, id asc'
        records = Model.search(safe_eval(self.domain or '[]', self._eval_context()), order=order, limit=SEARCH_LIMIT)
        checks = [name.strip() for name in (self.check_fields or '').split(',') if name.strip() in Model._fields]
        if checks:
            records = records.filtered(lambda record: any(record[name] for name in checks))
        return records

    def _allows(self, record, method):
        """The source offers this method as a button, and lists this record for the user right now."""
        self.ensure_one()
        return method in (self.primary_method, self.secondary_method) and record._name == self.model_name \
            and record in (self._records() or record.browse())

    def _value_text(self, record, name):
        if not name or name not in record._fields:
            return ''
        value = record[name]
        field = record._fields[name]
        if field.type == 'many2one':
            return value.display_name or ''
        if field.type == 'monetary':
            currency = record[field.get_currency_field(record)] if field.get_currency_field(record) else False
            return formatLang(self.env, value or 0.0, currency_obj=currency or self.env.company.currency_id)
        return str(value) if value else ''

    def _date_text(self, value):
        """Label and whether the row is overdue, from the source's date field."""
        if not value:
            return '', False
        today = fields.Date.context_today(self)
        day = fields.Datetime.context_timestamp(self, value).date() if isinstance(value, datetime) else value
        days = (today - day).days
        if self.date_mode == 'due':
            if days > 0:
                return (_('1 day late') if days == 1 else _('%s days late', days)), True
            if days == 0:
                return _('due today'), False
            return (_('due tomorrow') if days == -1 else _('due in %s days', -days)), False
        if days <= 0:
            return _('today'), False
        return (_('waiting 1 day') if days == 1 else _('waiting %s days', days)), False

    def _home_rows(self, make_item):
        """(rows, all records) for Home. ``make_item`` builds a row like the built-in collectors do."""
        self.ensure_one()
        records = self._records()
        if not records:
            return [], self.env[self.model_name].browse() if self.model_name in self.env else []
        rows = []
        for record in records[:max(self.limit, 1)]:
            title = self._value_text(record, self.title_field) or record.display_name
            date_value = record[self.date_field] if self.date_field in record._fields else False
            when, overdue = self._date_text(date_value)
            meta = ' · '.join(part for part in (self.name, self._value_text(record, self.detail_field),
                                                 self._value_text(record, self.amount_field), when) if part)
            primary = {'label': self.primary_label or _('Open'), 'method': self.primary_method} \
                if self.primary_method else {'label': self.primary_label or _('Open'), 'open': True}
            secondary = False
            if self.secondary_label or self.secondary_method:
                secondary = {'label': self.secondary_label or _('Open'), 'method': self.secondary_method} \
                    if self.secondary_method else {'label': self.secondary_label or _('Open'), 'open': True}
            occurred = date_value if isinstance(date_value, datetime) else (
                fields.Datetime.to_datetime(date_value) if date_value else record.create_date)
            item = make_item(f'source_{self.id}', record, title, meta, primary, secondary,
                             tag=_('Overdue') if overdue else '', overdue=overdue, occurred=occurred)
            item['badge'] = (self.badge or self.name[:2]).upper()
            rows.append(item)
        return rows, records
