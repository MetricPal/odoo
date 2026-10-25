"""Data for the Marketing control panel: one call, everything the home screen shows.

Read-only. Everything is read with the user's own rights for campaigns and brands
(record rules decide which brands they see); numbers from the channel apps are
read with sudo but only for the campaigns the user can see.
"""

from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.tools import format_date

from .plan import ACTIVE, ITEM_STAGES

WEEKS = 8
TIMELINE_PAST_DAYS = 14
TIMELINE_NEXT_DAYS = 45
CHANNEL_ICONS = {'email': 'mail', 'sms': 'smartphone', 'messaging': 'chat_bubble', 'social': 'share',
                 'event_virtual': 'videocam', 'event_physical': 'calendar_today', 'content': 'edit',
                 'ads': 'campaign', 'partnership': 'handshake'}


class Panel(models.AbstractModel):
    _name = 'mi.panel'
    _description = 'Marketing control panel'

    @api.model
    def get_panel(self, brand_id=False):
        brands = self.env['mi.brand'].search([])
        selected = brands.filtered(lambda b: b.id == brand_id) or brands
        plans = self.env['mi.plan'].search([('brand_id', 'in', selected.ids), ('is_template', '=', False)])
        active = plans.filtered(lambda p: p.state in ACTIVE).sorted(lambda p: (p.date_start, p.id))
        now = fields.Datetime.now()
        return {
            'brands': [{'id': b.id, 'name': b.name, 'group': b.portfolio or ''} for b in brands],
            'brand_id': brand_id if brand_id in brands.ids else False,
            'currency': selected[:1].currency_id.symbol or '',
            'kpis': self._kpis(selected, plans, now),
            'timeline': self._timeline(plans, now),
            'campaigns': [self._campaign_row(plan) for plan in active[:30]],
            'flows': self._flows(selected),
            'todos': self._todos(selected, plans),
            'alerts': self._alerts(selected, active),
            'counts': {'active': len(active), 'templates': self.env['mi.plan'].search_count(
                [('is_template', '=', True)]), 'brands': len(selected)},
        }

    # ------------------------------------------------------------------ KPIs

    def _weeks(self, now):
        start = datetime.combine((now - timedelta(days=now.weekday())).date(), time.min)
        return [(start - timedelta(weeks=WEEKS - 1 - i), start - timedelta(weeks=WEEKS - 2 - i)) for i in range(WEEKS)]

    def _series(self, model, date_field, domain, now, measure=None):
        if model not in self.env:
            return [0] * WEEKS
        Model = self.env[model].sudo()
        values = []
        for begin, end in self._weeks(now):
            rows = domain + [(date_field, '>=', begin), (date_field, '<', end)]
            if measure:
                values.append(sum(Model.search(rows).mapped(measure)))
            else:
                values.append(Model.search_count(rows))
        return values

    def _kpi(self, key, label, series, icon, money=False, action=False):
        last, previous = sum(series[-4:]), sum(series[-8:-4])
        delta = round(100 * (last - previous) / previous) if previous else (100 if last else 0)
        return {'key': key, 'label': label, 'value': last, 'trend': series, 'delta': delta, 'icon': icon,
                'money': money, 'action': action, 'hint': _('last 4 weeks')}

    def _kpis(self, brands, plans, now):
        utm = plans.utm_campaign_id.ids
        mailings = [i.res_id for i in plans.item_ids if i.res_model == 'mailing.mailing' and i.res_id]
        mm = [i.res_id for i in plans.item_ids if i.res_model == 'mm.mailing' and i.res_id]
        sent = self._series('mailing.trace', 'sent_datetime', [('mass_mailing_id', 'in', mailings)], now)
        if 'mm.trace' in self.env:
            mm_sent = self._series('mm.trace', 'sent_at', [('mailing_id', 'in', mm), ('state', '=', 'sent')], now)
            sent = [a + b for a, b in zip(sent, mm_sent)]
        if 'mi.flow.run' in self.env:
            flow_msgs = self._series('omni.command', 'create_date',
                                     [('mi_flow_run_id.brand_id', 'in', brands.ids), ('state', '!=', 'cancelled')], now)
            sent = [a + b for a, b in zip(sent, flow_msgs)]
        kpis = [
            self._kpi('sent', _('Messages sent'), sent, 'send'),
            self._kpi('clicks', _('Link clicks'),
                      self._series('link.tracker.click', 'create_date', [('campaign_id', 'in', utm)], now),
                      'mouse'),
            self._kpi('leads', _('Leads'), self._series('crm.lead', 'create_date', [('campaign_id', 'in', utm)], now),
                      'person_add', action='leads'),
            self._kpi('revenue', _('Won revenue'), self._series(
                'crm.lead', 'date_closed', [('campaign_id', 'in', utm), ('won_status', '=', 'won')], now,
                measure='expected_revenue'), 'show_chart', money=True),
        ]
        budget = sum(brands.mapped('monthly_budget'))
        planned = sum(brands.mapped('budget_month'))
        kpis.append({'key': 'budget', 'label': _('Budget this month'), 'value': planned, 'money': True,
                     'icon': 'payments', 'trend': [], 'delta': 0,
                     'pct': round(100 * planned / budget) if budget else 0,
                     'hint': _('planned, of %(cur)s%(amount)s monthly budget', cur=brands[:1].currency_id.symbol or '',
                               amount='{:,.0f}'.format(budget)) if budget else _('no monthly budget set')})
        goals = brands.goal_ids
        behind = sum(brands.mapped('goals_behind_count'))
        kpis.append({'key': 'goals', 'label': _('Goals on track'), 'value': len(goals) - behind, 'icon': 'flag',
                     'trend': [], 'delta': 0, 'pct': round(100 * (len(goals) - behind) / len(goals)) if goals else 0,
                     'hint': _('of %s goals', len(goals)) if goals else _('no goals yet: add them on a brand'),
                     'action': 'goals'})
        return kpis

    # ------------------------------------------------------------------ timeline

    def _event(self, at, kind, title, plan=None, subtitle='', model=None, res_id=None, icon='check',
               recurring=False, now=None):
        if not at:
            return None
        all_day = not isinstance(at, datetime)
        if all_day:
            # A day, not a moment: noon UTC stays on the same calendar day in nearly every time zone.
            at = datetime.combine(at, time(12, 0))
        return {'at': fields.Datetime.to_string(at), 'all_day': all_day, 'future': bool(now and at > now), 'kind': kind,
                'title': title, 'subtitle': subtitle or (plan and '%s · %s' % (plan.name, plan.brand_id.name)) or '',
                'model': model or (plan and 'mi.plan'), 'res_id': res_id or (plan and plan.id), 'icon': icon,
                'recurring': recurring or bool(plan and plan.repeat != 'none')}

    def _timeline(self, plans, now):
        past, nxt = now - timedelta(days=TIMELINE_PAST_DAYS), now + timedelta(days=TIMELINE_NEXT_DAYS)
        events = []
        add = events.append
        for plan in plans.filtered(lambda p: p.state != 'cancelled'):
            start = datetime.combine(plan.date_start, time(12, 0))
            if past <= start <= nxt:
                add(self._event(plan.date_start, 'start', _('Campaign starts') if start > now else
                                _('Campaign started'), plan, icon='flag', now=now))
            end = datetime.combine(plan.date_end, time(12, 0))
            if now <= end <= nxt and plan.state in ACTIVE:
                add(self._event(plan.date_end, 'end', _('Campaign ends'), plan, icon='sports_score', now=now))
            if plan.next_run_date:
                add(self._event(plan.next_run_date, 'repeat', _('Next run (repeats %s)', dict(
                    plan._fields['repeat']._description_selection(self.env))[plan.repeat].lower()), plan,
                    icon='repeat', recurring=True, now=now))
            request = plan.sudo().review_request_id
            if request.state == 'submitted':
                add(self._event(request.create_date, 'review', _('Waiting for review'), plan, icon='hourglass_top',
                                now=now))
            elif request.state == 'approved' and request.approved_at and request.approved_at >= past:
                add(self._event(request.approved_at, 'approved', _('Approved by %s', request.approver_id.name or '-'),
                                plan, icon='check_circle', now=now))
            for item in plan.item_ids.filtered('res_id'):
                record = item._record()
                if not record:
                    continue
                for event in self._item_events(item, record.sudo(), plan, now):
                    if event and past <= fields.Datetime.to_datetime(event['at']) <= nxt:
                        add(event)
        events += [e for e in self._flow_events(plans.brand_id, past) if e]
        events = [e for e in events if e]
        events.sort(key=lambda e: e['at'])
        upcoming = [e for e in events if e['future']][:25]
        recent = [e for e in events if not e['future']][-25:][::-1]
        return {'upcoming': upcoming, 'recent': recent}

    def _item_events(self, item, record, plan, now):
        label = dict(item._fields['channel']._description_selection(self.env))[item.channel]
        icon = CHANNEL_ICONS.get(item.channel, 'check')
        if record._name == 'mailing.mailing':
            if record.state == 'done' and record.sent_date:
                yield self._event(record.sent_date, 'sent', _('%(channel)s sent · %(n)s', channel=label, n=record.sent),
                                  plan, model=record._name, res_id=record.id, icon=icon, now=now)
            elif record.state == 'in_queue' and record.schedule_date:
                yield self._event(record.schedule_date, 'scheduled', _('%s goes out', label), plan,
                                  model=record._name, res_id=record.id, icon=icon, now=now)
        elif record._name == 'mm.mailing':
            if record.sent_at:
                yield self._event(record.sent_at, 'sent', _('%(channel)s sent · %(n)s', channel=label,
                                                            n=record.sent_count), plan, model=record._name,
                                  res_id=record.id, icon=icon, now=now)
            elif record.state == 'approved' and record.scheduled_at:
                yield self._event(record.scheduled_at, 'scheduled', _('%s goes out', label), plan,
                                  model=record._name, res_id=record.id, icon=icon, now=now)
        elif record._name == 'omni.social.campaign':
            for post in record.publication_ids:
                if post.state == 'sent' and post.published_at:
                    yield self._event(post.published_at, 'sent', _('Post published on %s', post.connection_id.name),
                                      plan, model=record._name, res_id=record.id, icon=icon, now=now)
                elif post.state == 'approved' and post.scheduled_at:
                    yield self._event(post.scheduled_at, 'scheduled', _('Post on %s', post.connection_id.name),
                                      plan, model=record._name, res_id=record.id, icon=icon, now=now)
        elif record._name == 'event.event' and record.date_begin:
            yield self._event(record.date_begin, 'event', _('Event: %s', record.name), plan, model=record._name,
                              res_id=record.id, icon=icon, now=now)

    def _flow_events(self, brands, since):
        """Hook for workflows."""
        return []

    # ------------------------------------------------------------------ progress, to-dos, alerts

    def _campaign_row(self, plan):
        labels = dict(ITEM_STAGES)
        groups = {'out': 0, 'scheduled': 0, 'waiting': 0, 'fix': 0, 'todo': 0}
        items = []
        for item in plan.item_ids:
            stage = item.stage
            group = ('out' if stage in ('out', 'todo_done') else 'scheduled' if stage in ('scheduled', 'approved')
                     else 'waiting' if stage == 'needs_review' else 'fix' if stage in ('blocked', 'failed')
                     else 'todo')
            if stage != 'unavailable':
                groups[group] += 1
            items.append({'channel': dict(item._fields['channel']._description_selection(self.env))[item.channel],
                          'icon': CHANNEL_ICONS.get(item.channel, 'check'), 'stage': stage,
                          'stage_label': labels.get(stage, stage), 'group': group, 'next': item.next_step or ''})
        return {'id': plan.id, 'name': plan.name, 'brand': plan.brand_id.name, 'status': plan.status,
                'status_label': dict(plan._fields['status']._description_selection(self.env))[plan.status],
                'out': plan.channels_out, 'total': plan.channel_count, 'groups': groups, 'items': items,
                'day': plan.day_label or '', 'next': plan.next_step or '', 'needs_me': plan.needs_me,
                'worker': plan.worker, 'repeat': plan.repeat != 'none',
                'dates': '%s → %s' % (format_date(self.env, plan.date_start), format_date(self.env, plan.date_end))}

    def _flows(self, brands):
        """Hook for workflows."""
        return []

    def _todos(self, brands, plans):
        todos = []
        for plan in plans.filtered(lambda p: p.state in ACTIVE and p.needs_me):
            todos.append({'title': plan.my_todo, 'subtitle': '%s · %s' % (plan.name, plan.brand_id.name),
                          'model': 'mi.plan', 'res_id': plan.id,
                          'icon': 'checklist' if plan.can_review else 'edit'})
        return todos + self._flow_todos(brands)

    def _flow_todos(self, brands):
        return []

    def _alerts(self, brands, active):
        alerts = []
        for plan in active:
            fix = [i for i in plan.item_ids if i.stage in ('blocked', 'failed')]
            if fix and not plan.needs_me:
                alerts.append({'level': 'danger', 'text': _('%(n)s channel(s) need fixing in “%(name)s”', n=len(fix),
                                                           name=plan.name), 'model': 'mi.plan', 'res_id': plan.id})
        for brand in brands:
            if brand.monthly_budget and brand.budget_month_pct > 100:
                alerts.append({'level': 'warning', 'text': _('%(brand)s: %(pct)s%% of the monthly budget planned',
                                                             brand=brand.name, pct=brand.budget_month_pct),
                               'model': 'mi.brand', 'res_id': brand.id})
            if brand.goals_behind_count:
                alerts.append({'level': 'warning', 'text': _('%(brand)s: %(n)s goal(s) behind schedule',
                                                             brand=brand.name, n=brand.goals_behind_count),
                               'model': 'mi.brand', 'res_id': brand.id})
        return alerts + self._flow_alerts(brands)

    def _flow_alerts(self, brands):
        return []
