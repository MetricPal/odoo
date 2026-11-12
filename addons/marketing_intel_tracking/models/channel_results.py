"""Results by channel and source (owner, 2026-11-12, board 10): a block of the Marketing panel.

One row per channel (the UTM medium of the tracked links: Email, SMS, WhatsApp, Telegram, Social Media), opened into
its sources: the mailing for Email, SMS and Messaging (Odoo ties leads, sales and links to it with utm_reference),
the platform for Social. Clicks from Link Tracker, leads and won deals from CRM, revenue from confirmed sales (or won
deals' expected revenue without Sales), spend from the campaigns' spend lines that name their channel. A last row
counts what came without a marketing medium, so shares add up to every lead. A donut chart shows the shares of
leads, revenue or clicks. Every number, slice and legend line opens its list.
"""

from collections import defaultdict

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import formatLang

from odoo.addons.marketing_intel_plan.models.evaluation import _arcs
from odoo.addons.messaging_marketing.models.mailing import CHANNELS as MESSAGING_CHANNELS

# (key, colour); colours differ in lightness, not only in hue. Labels: Panel._cr_labels().
CHANNEL_ROWS = [
    ('email', '#71639e'),
    ('sms', '#a99bc9'),
    ('whatsapp', '#2f7d6d'),
    ('telegram', '#7fbfb0'),
    ('social', '#d9822b'),
]
OTHER_COLOR = '#b9bfc6'
MEASURES = ('clicks', 'leads', 'won', 'revenue', 'spend')
BY_REFERENCE = ('email', 'sms', 'whatsapp', 'telegram')  # their sources are mailings (utm_reference)


class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    # ------------------------------------------------------------------ what counts

    @api.model
    def _cr_labels(self):
        return {'email': _('Email'), 'sms': _('SMS'), 'whatsapp': _('WhatsApp'), 'telegram': _('Telegram'),
                'social': _('Social Media')}

    @api.model
    def _cr_mediums(self):
        """{row key: utm.medium} for the marketing channels that exist (a channel never used has no medium yet)."""
        Medium = self.env['utm.medium'].sudo()
        mediums = {
            'email': self.env.ref('utm.utm_medium_email', raise_if_not_found=False),
            'sms': self.env.ref('mass_mailing_sms.utm_medium_sms', raise_if_not_found=False),
            'social': self.env.ref('utm.utm_medium_social_media', raise_if_not_found=False),
        }
        for key in ('whatsapp', 'telegram'):
            mediums[key] = Medium.search([('name', '=', dict(MESSAGING_CHANNELS)[key])], limit=1)
        return {key: medium for key, medium in mediums.items() if medium}

    @api.model
    def _cr_scope(self, brand_id=False):
        """(start of the period, UTM campaigns to keep or None for all, all brands?)."""
        start = self._period_start()
        brands = self.env['mi.brand'].search([])
        selected = brands.filtered(lambda b: b.id == brand_id) or brands
        if selected == brands:
            return start, None, True
        # sudo: mi.plan - only the selected brands' tracking campaigns are read, to scope the numbers.
        plans = self.env['mi.plan'].sudo().search([('brand_id', 'in', selected.ids), ('is_template', '=', False)])
        return start, plans.utm_campaign_id, False

    @api.model
    def _cr_domain(self, measure, start, campaigns, mediums, row, sub=None):
        """Domain on the model of `measure` for one row ('all', 'other' or a channel key), and one of its sources."""
        if measure == 'clicks':
            domain = [('create_date', '>=', start)]
            prefix = 'link_id.'
        elif measure == 'spend':
            return [('date', '>=', start.date())] + (
                [('plan_id.utm_campaign_id', 'in', campaigns.ids)] if campaigns is not None else [])
        else:
            date_field = 'date_order' if measure == 'revenue' and 'sale.order' in self.env else 'create_date'
            domain = [(date_field, '>=', start)]
            if measure == 'won' or (measure == 'revenue' and 'sale.order' not in self.env):
                domain.append(('won_status', '=', 'won'))
            if measure == 'revenue' and 'sale.order' in self.env:
                domain.append(('state', '=', 'sale'))
            prefix = ''
        if campaigns is not None:
            domain.append((prefix + 'campaign_id', 'in', campaigns.ids))
        marketing = [m.id for m in mediums.values()]
        if row == 'other':
            domain.append('|') if marketing else None
            domain += [(prefix + 'medium_id', '=', False)] + (
                [(prefix + 'medium_id', 'not in', marketing)] if marketing else [])
        elif row == 'all' and measure == 'clicks':
            domain.append((prefix + 'medium_id', 'in', marketing))
        elif row in mediums:
            domain.append((prefix + 'medium_id', '=', mediums[row].id))
        elif row != 'all':
            domain.append(('id', '=', False))
        if sub:
            kind, value = sub
            domain.append((prefix + ('utm_reference' if kind == 'reference' else 'source_id'), '=', value))
        return domain

    @api.model
    def _cr_model(self, measure):
        if measure == 'clicks':
            return 'link.tracker.click'
        if measure == 'spend':
            return 'mi.plan.spend'
        if measure == 'revenue' and 'sale.order' in self.env:
            return 'sale.order'
        return 'crm.lead' if 'crm.lead' in self.env else None

    # ------------------------------------------------------------------ the numbers

    @api.model
    def _cr_spend(self, start, campaigns, mediums):
        """Spend per channel (lines that name their channel) and in all."""
        # sudo: mi.plan.spend - amounts only, summed per channel for the panel.
        lines = self.env['mi.plan.spend'].sudo().search(self._cr_domain('spend', start, campaigns, mediums, 'all'))
        per = defaultdict(float)
        for line in lines:
            key = self._cr_spend_key(line)
            if key:
                per[key] += line.amount
        return per, sum(lines.mapped('amount'))

    @api.model
    def _cr_group(self, model, domain, by_reference, field_prefix='', amount=None):
        """{row key: {sub key: (value)}}: counts (or sums of `amount`) per medium and per source or mailing."""
        records = self.env[model].sudo().with_context(active_test=False).search(domain)
        out = defaultdict(lambda: defaultdict(float))
        for record in records:
            utm = record.link_id if field_prefix else record
            medium = utm.medium_id.id or False
            ref = utm.utm_reference  # a Reference field: a record, kept as "model,id"
            ref = f'{ref._name},{ref.id}' if isinstance(ref, models.BaseModel) and ref else (ref or False)
            sub = ('reference', ref) if medium in by_reference and ref else ('source', utm.source_id.id or False)
            out[medium][sub] += (record[amount] if amount else 1)
        return out

    @api.model
    def _cr_label(self, sub):
        kind, value = sub
        if kind == 'reference' and value:
            model, _sep, res_id = value.partition(',')
            if model in self.env and res_id.isdigit():
                record = self.env[model].sudo().browse(int(res_id)).exists()
                if record:
                    return record.display_name
        if kind == 'source' and value:
            return self.env['utm.source'].sudo().browse(value).name
        return _('Without a source')

    @api.model
    def _channel_results(self, brand_id=False):
        start, campaigns, all_brands = self._cr_scope(brand_id)
        mediums = self._cr_mediums()
        medium_key = {medium.id: key for key, medium in mediums.items()}
        by_reference = {mediums[k].id for k in BY_REFERENCE if k in mediums}
        currency = self.env.company.currency_id

        def money(amount):
            return formatLang(self.env, amount or 0.0, currency_obj=currency, digits=0)

        crm = 'crm.lead' in self.env
        sale = 'sale.order' in self.env
        everything = 'all' if all_brands else None
        clicks = self._cr_group('link.tracker.click', self._cr_domain('clicks', start, campaigns, mediums, 'all'),
                                by_reference, field_prefix='link_id.')
        leads = self._cr_group('crm.lead', self._cr_domain('leads', start, campaigns, mediums, everything or 'all'),
                               by_reference) if crm else {}
        won = self._cr_group('crm.lead', self._cr_domain('won', start, campaigns, mediums, everything or 'all'),
                             by_reference) if crm else {}
        revenue = self._cr_group(self._cr_model('revenue'), self._cr_domain('revenue', start, campaigns, mediums,
                                                                             everything or 'all'),
                                 by_reference, amount='amount_untaxed' if sale else 'expected_revenue') \
            if (sale or crm) else {}
        spend, spend_total = self._cr_spend(start, campaigns, mediums)

        def total(grouped, medium_id):
            return sum(grouped.get(medium_id, {}).values())

        def ratios(row_spend, row_leads, row_revenue):
            return (money(row_spend / row_leads) if row_spend and row_leads else '—',
                    ('%.1f×' % (row_revenue / row_spend)) if row_spend else '—',
                    bool(row_spend and row_revenue < row_spend))

        labels = self._cr_labels()
        rows = []
        for key, color in CHANNEL_ROWS:
            medium = mediums.get(key)
            mid = medium.id if medium else -1
            row_leads, row_revenue = total(leads, mid), total(revenue, mid)
            cpl, roi, roi_bad = ratios(spend.get(key, 0), row_leads, row_revenue)
            subs = set(clicks.get(mid, {})) | set(leads.get(mid, {})) | set(won.get(mid, {})) | set(revenue.get(mid, {}))
            sources = sorted(({
                'label': self._cr_label(sub), 'sub': list(sub),
                'clicks': int(clicks.get(mid, {}).get(sub, 0)), 'leads': int(leads.get(mid, {}).get(sub, 0)),
                'won': int(won.get(mid, {}).get(sub, 0)),
                'revenue': money(revenue.get(mid, {}).get(sub, 0)) if revenue.get(mid, {}).get(sub) else '—',
            } for sub in subs), key=lambda s: (-s['leads'], -s['clicks'], s['label']))
            rows.append({
                'key': key, 'label': labels[key], 'color': color, 'sources': sources,
                'clicks': int(total(clicks, mid)), 'leads': int(row_leads), 'won': int(total(won, mid)),
                'revenue': money(row_revenue), 'revenue_value': row_revenue,
                'spend': money(spend[key]) if spend.get(key) else '—', 'cpl': cpl, 'roi': roi, 'roi_bad': roi_bad,
            })
        other = None
        if all_brands and crm:
            marketing = set(medium_key)
            other_leads = sum(v for m, g in leads.items() if m not in marketing for v in g.values())
            other_won = sum(v for m, g in won.items() if m not in marketing for v in g.values())
            other_revenue = sum(v for m, g in revenue.items() if m not in marketing for v in g.values())
            other = {'key': 'other', 'label': _('Not from a marketing link'), 'color': OTHER_COLOR,
                     'leads': int(other_leads), 'won': int(other_won), 'revenue': money(other_revenue),
                     'revenue_value': other_revenue}

        all_leads = sum(r['leads'] for r in rows) + (other['leads'] if other else 0)
        all_revenue = sum(r['revenue_value'] for r in rows) + (other['revenue_value'] if other else 0)
        all_clicks = sum(r['clicks'] for r in rows)
        cpl, roi, roi_bad = ratios(spend_total, all_leads, all_revenue)
        totals = {'clicks': all_clicks, 'leads': all_leads,
                  'won': sum(r['won'] for r in rows) + (other['won'] if other else 0),
                  'revenue': money(all_revenue) if all_revenue else '—',
                  'spend': money(spend_total) if spend_total else '—',
                  'cpl': cpl, 'roi': roi, 'roi_bad': roi_bad}
        for row in rows + ([other] if other else []):
            row['share'] = round(row['leads'] / all_leads * 100) if all_leads else 0

        def donut(measure, value_of, display_of):
            parts = [r for r in rows + ([other] if other and measure != 'clicks' else []) if value_of(r) > 0]
            values = [value_of(r) for r in parts]
            whole = sum(values)
            paths = _arcs(values) if whole else []
            return {'total': display_of(whole), 'slices': [{
                'key': r['key'], 'label': r['label'], 'color': r['color'], 'path': paths[i],
                'value': display_of(values[i]), 'pct': round(values[i] / whole * 100) if whole else 0,
            } for i, r in enumerate(parts)]}

        charts = {
            'leads': donut('leads', lambda r: r['leads'], lambda v: str(int(v))),
            'revenue': donut('revenue', lambda r: r['revenue_value'], money),
            'clicks': donut('clicks', lambda r: r.get('clicks', 0), lambda v: str(int(v))),
        }
        quarter = (start.month - 1) // 3 + 1
        return {'period': _('Q%(quarter)s %(year)s', quarter=quarter, year=start.year), 'rows': rows, 'other': other,
                'totals': totals, 'charts': charts, 'crm': crm, 'brand_id': brand_id or False,
                'can_open': {m: bool(self._cr_model(m)) and self.env[self._cr_model(m)].has_access('read')
                             for m in MEASURES}}

    # ------------------------------------------------------------------ the block

    def _extra_blocks(self, keys, brands, plans):
        data = super()._extra_blocks(keys, brands, plans)
        if 'channel_results' in keys:
            all_brands = self.env['mi.brand'].search([])
            brand_id = brands.id if len(brands) == 1 and brands != all_brands else False
            results = self._channel_results(brand_id)
            # columns / table_rows feed "Explain this"; the block draws its own table.
            table = [[r['label'], str(r['clicks']), str(r['leads']), str(r['won']), r['revenue'], r['spend'], r['cpl'],
                      r['roi']] for r in results['rows']]
            if results['other']:
                o = results['other']
                table.append([o['label'], '—', str(o['leads']), str(o['won']), o['revenue'], '—', '—', '—'])
            data['channel_results'] = {
                'title': _('Results by channel and source · %s', results['period']), 'icon': 'donut_large',
                'explain': True, 'rows': [], 'empty': '', 'channel_results': results,
                'columns': [_('Channel'), _('Clicks'), _('Leads'), _('Won'), _('Revenue'), _('Spend'),
                            _('Cost per lead'), _('Revenue ÷ spend')],
                'table_rows': table,
                'note': _('From tracked links, CRM and Sales.'),
            }
        return data

    @api.model
    def open_channel_results(self, measure, row, sub=None, brand_id=False):
        """The list behind one number, slice or legend line of the block."""
        if measure not in MEASURES:
            raise UserError(_('Unknown measure.'))
        model = self._cr_model(measure)
        if not model:
            raise UserError(_('This app is not installed.'))
        start, campaigns, _all = self._cr_scope(brand_id)
        mediums = self._cr_mediums()
        domain = self._cr_domain(measure, start, campaigns, mediums, row, tuple(sub) if sub else None)
        if measure == 'spend' and row not in ('all', 'other'):
            ids = [line.id for line in self.env['mi.plan.spend'].search(domain)
                   if self._cr_spend_key(line) == row]
            domain = [('id', 'in', ids)]
        names = {'clicks': _('Link clicks'), 'leads': _('Leads'), 'won': _('Won deals'),
                 'revenue': _('Sales') if model == 'sale.order' else _('Won deals'), 'spend': _('Spend')}
        return {'type': 'ir.actions.act_window', 'name': names[measure], 'res_model': model,
                'views': [(False, 'list'), (False, 'form')], 'domain': domain, 'target': 'current',
                'context': {'active_test': False, 'create': False}}

    @api.model
    def _cr_spend_key(self, line):
        """The channel row a spend line counts in: its campaign channel, WhatsApp or Telegram for Messaging."""
        item = line.sudo().item_id
        if not item:
            return False
        if item.channel == 'messaging':
            # sudo: mm.mailing - only its channel is read, to split Messaging spend.
            record = self.env['mm.mailing'].sudo().browse(item.res_id).exists() \
                if item.res_model == 'mm.mailing' and item.res_id else None
            return record.channel if record else False
        return item.channel if item.channel in dict(CHANNEL_ROWS) else False


class PanelLayout(models.Model):
    _inherit = 'mi.panel.layout'

    @api.model
    def _catalogue(self):
        catalogue = super()._catalogue()
        catalogue['channel_results'] = _('Results by channel and source')
        return catalogue

    @api.model
    def _default_blocks(self, role):
        """On by default for the head of department (Department) and seniors (My team), after their tiles."""
        blocks = super()._default_blocks(role)
        if role in ('hod', 'senior') and not any(b['key'] == 'channel_results' for b in blocks):
            after = 'dept_tiles' if role == 'hod' else 'team_tiles'
            index = next((i + 1 for i, b in enumerate(blocks) if b['key'] == after), len(blocks))
            blocks.insert(index, {'key': 'channel_results', 'width': 'full'})
        return blocks
