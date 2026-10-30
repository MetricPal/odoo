"""Home page data. Left: the user's own work (today, my plan, waiting on others, team load, recent). Middle: decisions
only the user can make. Right: what other people did.

Everything is read with the current user's permissions. A section whose app is not installed, or that the user may
not read, is left out. Buttons on Home only call the whitelisted methods in HOME_ACTIONS, or a decision source's own
buttons, as the current user, so the target model's own checks (approvers, owners, managers) still decide.
"""

from datetime import UTC, datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext
from odoo.tools.misc import format_date

LIMIT = 20
PLAN_LIMIT = 300
WAITING_LIMIT = 5
FEED_LIMIT = 20
RECENT_LIMIT = 4
WEEK_DAYS = 7
# Not "work": conversations, technical and Home records stay out of recent records and the feed.
EXCLUDED_MODELS = {
    'discuss.channel', 'mail.channel', 'res.users', 'res.users.log', 'mail.message', 'ai.home.item',
    'ir.ui.view', 'ir.actions.server', 'base.automation', 'ai.agent.conversation', 'ai.agent.run',
}
# What the built-in buttons on Home may do: (model, method) run as the current user.
HOME_ACTIONS = {
    ('approval.center.request', 'action_approve'),
    ('approval.center.request', 'action_refuse'),
    ('approval.center.request', 'home_remind'),
    ('mail.activity', 'action_done'),
    ('mail.activity', 'action_reschedule_tomorrow'),
    ('mail.activity', 'action_reschedule_nextweek'),
    ('mail.activity', 'home_nudge'),
    ('omni.conversation', 'action_assign_me'),
    ('workflow.run', 'action_retry'),
}
# Dot colours, the same meanings as Odoo activities: red overdue or failed, orange due today or waiting, green on track.
GOOD, WARN, BAD = 'good', 'warn', 'bad'
SECTIONS = ('late', 'today', 'tomorrow', 'week', 'later')


def _iso(value):
    return fields.Datetime.to_string(value) if value else False


def _initials(name):
    parts = (name or '?').split()
    return ''.join(part[0] for part in parts[:2]).upper()


class AiHomeItem(models.Model):
    _inherit = 'ai.home.item'

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    @api.model
    def get_home_data(self):
        attention, groups, decided = self._home_attention()
        plan = self._home_plan(decided)
        agents = self._usable_agents()
        return {
            'today': self._home_today(plan),
            'week': self._home_week(plan),
            'plan': plan,
            'waiting': self._home_waiting(),
            'team': self._home_team(),
            'attention': attention,
            'attentionGroups': groups,
            'feed': self._home_feed(),
            'recent': self._home_recent(),
            'agents': agents,
            'prompts': self._home_prompts(self._home_role()) if agents else [],
            'canManageAgents': self.env.user.has_group('ai_agent.group_manager') if 'ai.agent' in self.env else False,
        }

    @api.model
    def run_home_action(self, model, res_id, method):
        """Run one Home button on one record, as the current user."""
        if model not in self.env:
            raise UserError(_('This action is not available from Home.'))
        record = self.env[model].browse(int(res_id)).exists()
        if not record:
            raise UserError(_('This record no longer exists.'))
        record.check_access('read')
        if (model, method) not in HOME_ACTIONS:
            sources = self.env['ai.home.source'].search([('model_name', '=', model)])
            if not any(source._allows(record, method) for source in sources):
                raise UserError(_('This action is not available from Home.'))
        if method == 'home_remind':
            return self._remind_approvers(record)
        if method == 'home_nudge':
            return self._nudge(record)
        result = getattr(record, method)()
        return result if isinstance(result, dict) else True

    @api.model
    def ask_ai(self, agent_id, prompt, attachment_ids=None, conversation_id=False):
        """Send the user's question to an agent (an answer only, it changes no records). Returns the run to follow."""
        if 'ai.agent' not in self.env:
            raise UserError(_('The AI assistant is not installed.'))
        agent = self.env['ai.agent'].browse(int(agent_id)).exists()
        if not agent:
            raise UserError(_('This assistant is no longer available.'))
        conversation = self.env['ai.agent.conversation'].browse(int(conversation_id)).exists() if conversation_id \
            else self.env['ai.agent.conversation']
        if conversation and conversation.user_id != self.env.user:
            conversation = self.env['ai.agent.conversation']
        attachments = self.env['ir.attachment'].browse([int(i) for i in attachment_ids or []]).exists()
        run = self.env['ai.agent.run']._queue(agent, prompt, conversation or None, attachments=attachments)
        return {'runId': run.id, 'conversationId': run.conversation_id.id}

    @api.model
    def get_ai_answer(self, run_id):
        """State and answer of the user's own AI question, for showing it on Home."""
        run = self.env['ai.agent.run'].search([('id', '=', int(run_id)), ('user_id', '=', self.env.uid)], limit=1) \
            if self._can_read('ai.agent.run') else False
        if not run:
            return {'state': 'failed', 'answer': '', 'error': _('This question is no longer available.')}
        return {'state': run.state, 'answer': run.answer or '', 'error': run.error_message or '',
                'conversationId': run.conversation_id.id}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _home_role(self):
        """Which suggestions fit the user: operations (managers), support or sales."""
        user = self.env.user
        if user.has_group('base.group_system'):
            return 'operations'
        if 'omni.conversation' in self.env and user.has_group('omni_channel.group_omni_user') \
                and not user.has_group('omni_channel.group_omni_manager'):
            return 'support'
        if 'crm.lead' in self.env and user.has_group('sales_team.group_sale_salesman') \
                and not user.has_group('sales_team.group_sale_manager'):
            return 'sales'
        return 'operations'

    def _home_prompts(self, role):
        if role == 'support':
            return [_('Draft a reply to my oldest conversation'), _('Summarize today’s complaints')]
        if role == 'operations':
            return [_('What needs my approval today?'), _('Plan my afternoon'), _('What is late and why?')]
        return [_('Plan my afternoon'), _('What is late and why?')]

    @api.model
    def _usable_agents(self):
        """Active agents the user may chat with right now (engine ready, configuration reviewed)."""
        if 'ai.agent' not in self.env or not self.env.user.has_group('ai_agent.group_user'):
            return []
        agents = []
        for agent in self.env['ai.agent'].search([('state', '=', 'active'), ('can_chat', '=', True)]):
            try:
                agent._usable()
            except (AccessError, UserError):
                continue
            agents.append({'id': agent.id, 'name': agent.name, 'description': agent.description or ''})
        return agents

    def _can_read(self, model):
        """The model is installed and the user may read it at all."""
        return model in self.env and self.env[model].has_access('read')

    def _today(self):
        return fields.Date.context_today(self)

    def _end_of_week(self, today):
        """Last day of the week of the user's language (Odoo's week start, Monday by default)."""
        lang = self.env['res.lang']._lang_get(self.env.lang or 'en_US')
        week_start = int(lang.week_start or 1) if lang else 1
        days_in = (today.isoweekday() - week_start) % 7
        return today + timedelta(days=6 - days_in)

    def _local(self, value):
        return fields.Datetime.context_timestamp(self, value) if value else False

    def _local_time(self, value):
        return self._local(value).strftime('%H:%M') if value else ''

    def _list_action(self, model, domain, name):
        return {'type': 'ir.actions.act_window', 'res_model': model, 'name': name, 'domain': domain,
                'views': [[False, 'list'], [False, 'form']], 'target': 'current'}

    def _due_text(self, deadline, today):
        days = (today - deadline).days
        if days > 0:
            return _('1 day late') if days == 1 else _('%s days late', days)
        if days == 0:
            return _('due today')
        if days == -1:
            return _('due tomorrow')
        return format_date(self.env, deadline, date_format='EEE d MMM')

    def _app_names(self, model_names):
        """App (root menu) of each model, e.g. crm.lead -> CRM; falls back to the model's name."""
        names = {}
        model_names = [name for name in set(model_names) if name]
        if not model_names:
            return names
        actions = self.env['ir.actions.act_window'].sudo().search([('res_model', 'in', model_names)], order='id')
        menus = self.env['ir.ui.menu'].sudo().search(
            [('action', 'in', [f'ir.actions.act_window,{action.id}' for action in actions])], order='id')
        roots = {}
        for menu in menus:
            model = menu.action.res_model
            if model not in roots and menu.parent_path:
                roots[model] = int(menu.parent_path.split('/')[0])
        root_names = {menu.id: menu.name for menu in self.env['ir.ui.menu'].sudo().browse(set(roots.values()))}
        for model in model_names:
            names[model] = root_names.get(roots.get(model)) or self.env['ir.model']._get(model).name or model
        return names

    def _app_label(self, model, cache):
        if model not in cache:
            cache.update(self._app_names([model]))
        return cache[model]

    def _excluded_activity_types(self):
        """Activity types that are decisions (middle column), not part of the plan."""
        types = self.env['mail.activity.type'].search([('home_decision', '=', True)])
        review = self.env.ref('approval_center.mail_act_approval_review', raise_if_not_found=False)
        return types | review if review else types

    # ------------------------------------------------------------------
    # Left: today, my plan, waiting on others, team load
    # ------------------------------------------------------------------

    def _home_plan(self, decided=frozenset()):
        """The user's open activities and meetings, in sections, in display order.

        Activities on a record that is already a decision in the middle column (``decided``: model and id pairs) are
        left out, so each thing shows in one place only.
        """
        today = self._today()
        end_week = self._end_of_week(today)
        excluded = self._excluded_activity_types()
        activities = self.env['mail.activity'].search(
            [('user_id', '=', self.env.uid), ('activity_type_id', 'not in', excluded.ids)],
            order='date_deadline asc, id asc', limit=PLAN_LIMIT)
        activities = activities.filtered(lambda activity: activity.res_model in self.env and activity.date_deadline
                                         and (activity.res_model, activity.res_id) not in decided)
        apps = self._app_names(activities.mapped('res_model') + ['calendar.event'])
        rows = {section: [] for section in SECTIONS}

        def section_of(day):
            if day < today:
                return 'late'
            if day == today:
                return 'today'
            if day == today + timedelta(days=1):
                return 'tomorrow'
            return 'week' if day <= end_week else 'later'

        for activity in activities:
            kind = activity.activity_type_id
            rows[section_of(activity.date_deadline)].append(({
                'key': f'activity-{activity.id}',
                'kind': 'activity',
                'title': activity.summary or kind.name or _('Activity'),
                'meta': ' · '.join(part for part in (activity.res_name, self._due_text(activity.date_deadline, today))
                                   if part),
                'note': ' '.join(html2plaintext(activity.note or '').split())[:120],
                'app': apps.get(activity.res_model, ''),
                'icon': kind.icon or 'checklist',
                'time': '',
                'date': fields.Date.to_string(activity.date_deadline),
                'model': 'mail.activity',
                'resId': activity.id,
                'openModel': activity.res_model,
                'openId': activity.res_id,
                'canDone': kind.category != 'upload_file',
                'joinUrl': False,
            }, (fields.Date.to_string(activity.date_deadline), 2, '', kind.sequence, activity.id)))

        now = self._local(fields.Datetime.now())
        for event in self._my_events(today):
            start = self._local(event.start)
            day = event.start_date if event.allday else start.date()
            minutes = round((event.duration or 0) * 60)
            parts = [_('Meeting')]
            if minutes and not event.allday:
                parts.append(_('%s min', minutes) if minutes < 120 else _('%s h', round(minutes / 60, 1)))
            if event.videocall_location:
                parts.append(_('video call'))
            row = {
                'key': f'meeting-{event.id}',
                'kind': 'meeting',
                'title': event.name,
                'meta': ' · '.join(parts),
                'note': '',
                'app': apps.get('calendar.event', _('Calendar')),
                'icon': 'event',
                'time': _('All day') if event.allday else start.strftime('%H:%M'),
                'date': fields.Date.to_string(day),
                'model': 'calendar.event',
                'resId': event.id,
                'openModel': 'calendar.event',
                'openId': event.id,
                'canDone': False,
                'joinUrl': event.videocall_location or False,
                'past': bool(not event.allday and start < now),
            }
            # Today: past meetings, then activities (no time: "now"), then meetings still to come.
            if day == today:
                rank = 0 if event.allday else (1 if row['past'] else 3)
            else:
                rank = 0 if event.allday else 1
            order = (row['date'], rank, '' if event.allday else row['time'], 0, event.id)
            rows[section_of(day)].append((row, order))

        plan = []
        for section in SECTIONS:
            for row, _order in sorted(rows[section], key=lambda pair: pair[1]):
                row['section'] = section
                plan.append(row)
        return plan

    def _my_events(self, today):
        """Meetings the user attends and did not decline, today and the next days."""
        if not self._can_read('calendar.event'):
            return []
        start = datetime.combine(today, time.min, tzinfo=self.env.tz).astimezone(UTC).replace(tzinfo=None)
        partner = self.env.user.partner_id
        events = self.env['calendar.event'].search([
            ('partner_ids', 'in', partner.id), ('start', '<', start + timedelta(days=WEEK_DAYS)), ('stop', '>=', start),
        ], order='start', limit=LIMIT * 5)
        return events.filtered(lambda event: not event.attendee_ids.filtered(
            lambda attendee: attendee.partner_id == partner and attendee.state == 'declined'))

    def _home_today(self, plan):
        """Activities done today out of done + due today + late (meetings are not counted)."""
        today = self._today()
        late = sum(1 for row in plan if row['kind'] == 'activity' and row['section'] == 'late')
        todo = sum(1 for row in plan if row['kind'] == 'activity' and row['section'] == 'today')
        done = self.env['mail.activity'].with_context(active_test=False).search_count([
            ('user_id', '=', self.env.uid), ('active', '=', False), ('date_done', '=', today)])
        return {'done': done, 'late': late, 'todo': todo, 'total': done + late + todo,
                'label': format_date(self.env, today, date_format='EEE d MMM')}

    def _home_week(self, plan):
        """Items per day for the next days; a busy day (at least 3 and over 1.5 x the average) is marked."""
        today = self._today()
        days = [today + timedelta(days=offset) for offset in range(WEEK_DAYS)]
        counts = {fields.Date.to_string(day): 0 for day in days}
        for row in plan:
            if row['section'] != 'late' and row['date'] in counts:
                counts[row['date']] += 1
        average = sum(counts.values()) / WEEK_DAYS
        return [{
            'date': fields.Date.to_string(day),
            'label': format_date(self.env, day, date_format='EEE'),
            'longLabel': format_date(self.env, day, date_format='EEEE d MMM'),
            'count': counts[fields.Date.to_string(day)],
            'heavy': counts[fields.Date.to_string(day)] >= 3 and counts[fields.Date.to_string(day)] > 1.5 * average,
            'isToday': day == today,
        } for day in days]

    def _home_waiting(self):
        """Work the user handed to someone else that is due or late, and the user's pending requests."""
        today = self._today()
        rows = []
        for activity in self.env['mail.activity'].search([
            ('create_uid', '=', self.env.uid), ('user_id', '!=', False), ('user_id', '!=', self.env.uid),
            ('date_deadline', '<=', today),
        ], order='date_deadline asc, id asc', limit=WAITING_LIMIT):
            if activity.res_model not in self.env:
                continue
            late = activity.date_deadline < today
            who = activity.user_id.name
            rows.append({
                'key': f'waiting-activity-{activity.id}',
                'who': who,
                'initials': _initials(who),
                'title': _('%(who)s · %(what)s', who=who.split()[0] if who else '',
                           what=activity.summary or activity.activity_type_id.name or activity.res_name),
                'meta': ' · '.join(part for part in (activity.res_name, self._due_text(activity.date_deadline, today))
                                   if part),
                'tone': BAD if late else WARN,
                'since': fields.Date.to_string(activity.date_deadline),
                'model': 'mail.activity',
                'resId': activity.id,
                'openModel': activity.res_model,
                'openId': activity.res_id,
                'nudge': {'label': _('Nudge'), 'method': 'home_nudge'},
            })
        if self._can_read('approval.center.request'):
            for request in self.env['approval.center.request'].search(
                [('requester_id', '=', self.env.uid), ('state', '=', 'submitted')], order='write_date asc',
                limit=WAITING_LIMIT,
            ):
                pending = request.approver_ids.filtered(lambda a: a.status == 'submitted').user_id
                who = ', '.join(pending.mapped('name')) or _('approver not set')
                days = (fields.Datetime.now() - (request.write_date or fields.Datetime.now())).days
                rows.append({
                    'key': f'waiting-request-{request.id}',
                    'who': who,
                    'initials': _initials(pending[:1].name or '?'),
                    'title': _('%(who)s · approve %(what)s', who=who, what=request.name),
                    'meta': _('Approvals · waiting %s days', days) if days > 1 else (
                        _('Approvals · waiting 1 day') if days == 1 else _('Approvals · sent today')),
                    'tone': WARN,
                    'since': fields.Date.to_string((request.write_date or fields.Datetime.now()).date()),
                    'model': 'approval.center.request',
                    'resId': request.id,
                    'openModel': 'approval.center.request',
                    'openId': request.id,
                    'nudge': {'label': _('Nudge'), 'method': 'home_remind'},
                })
        return sorted(rows, key=lambda row: (row['since'], row['key']))[:WAITING_LIMIT]

    def _home_team(self):
        """Managers: open activities of each direct report (counts only, never their content)."""
        employee = self.env.user.employee_id if 'employee_id' in self.env.user._fields else False
        if not employee or not self._can_read('hr.employee.public'):
            return []
        reports = self.env['hr.employee.public'].search([('parent_id', '=', employee.id), ('user_id', '!=', False)])
        if not reports:
            return []
        today = self._today()
        end_week = self._end_of_week(today)
        users = reports.user_id
        Activity = self.env['mail.activity'].sudo()

        def counts(domain):
            return {user.id: count for user, count in Activity._read_group(
                [('user_id', 'in', users.ids)] + domain, ['user_id'], ['__count'])}

        late = counts([('date_deadline', '<', today)])
        due = counts([('date_deadline', '=', today)])
        week = counts([('date_deadline', '<=', end_week)])
        busiest = max(week.values(), default=0) or 1
        rows = []
        for report in reports:
            user = report.user_id
            rows.append({
                'key': f'team-{user.id}',
                'name': report.name,
                'initials': _initials(report.name),
                'userId': user.id,
                'late': late.get(user.id, 0),
                'today': due.get(user.id, 0),
                'open': week.get(user.id, 0),
                'load': round(100 * week.get(user.id, 0) / busiest),
                'tone': BAD if late.get(user.id, 0) > 2 else (WARN if late.get(user.id, 0) else GOOD),
            })
        return sorted(rows, key=lambda row: (-row['late'], -row['today'], row['name']))

    def _nudge(self, activity):
        """Remind the assignee of an activity the user handed to them, with a note on the document."""
        if activity._name != 'mail.activity' or activity.create_uid != self.env.user or not activity.active:
            raise UserError(_('You can only nudge people about activities you assigned to them.'))
        document = self.env[activity.res_model].browse(activity.res_id).exists()
        if not document or not hasattr(document, 'message_post'):
            raise UserError(_('This document cannot receive notes.'))
        document.message_post(
            body=_('Reminder: "%(what)s" was due %(when)s.',
                   what=activity.summary or activity.activity_type_id.name,
                   when=format_date(self.env, activity.date_deadline)),
            partner_ids=activity.user_id.partner_id.ids, message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    # ------------------------------------------------------------------
    # Middle: needs your attention (decisions only)
    # ------------------------------------------------------------------

    def _categories(self):
        """Built-in categories, in chip order, with their label and badge."""
        return [
            ('approval', _('Approvals'), 'AP'),
            ('decision', _('To decide'), 'DE'),
            ('conversation', _('Conversations'), 'OC'),
            ('workflow', _('Workflows'), 'WF'),
            ('ai', _('AI agents'), 'AI'),
            ('notice', _('Notices'), 'NO'),
        ]

    def _review_deadlines(self, request):
        """Deadlines of the user's review activities on the request (from Odoo activities)."""
        return [activity.date_deadline for activity in request.activity_ids
                if activity.user_id == self.env.user and activity.date_deadline]

    def _approval_overdue(self, request):
        today = self._today()
        return any(deadline < today for deadline in self._review_deadlines(request))

    def _item(self, category, record, title, meta, primary, secondary=False, tag='', overdue=False, occurred=False,
              open_action=False, key=''):
        """One row; buttons are {label, method} (run on the server) or {label, open: True} (open the record, or
        open_action when given)."""
        badges = {key: badge for key, _label, badge in self._categories()}
        return {
            'openAction': open_action,
            'key': f'{category}-{key + "-" if key else ""}{record._name}-{record.id}',
            'category': category,
            'badge': badges.get(category, category[:2].upper()),
            'model': record._name,
            'resId': record.id,
            'title': title,
            'meta': meta,
            'tag': tag,
            'overdue': overdue,
            'occurred': _iso(occurred),
            'primary': primary,
            'secondary': secondary or False,
        }

    def _attention_collectors(self):
        """Methods that each return attention rows; other modules add theirs."""
        return [self._attention_approvals, self._attention_decisions, self._attention_conversations,
                self._attention_workflows, self._attention_ai]

    def _home_attention(self):
        """(rows, chip groups, decided records). Rows: built-in collectors, then decision sources; most urgent first.
        Decided records are the (model, id) pairs the middle column covers, including source rows past the limit."""
        items = []
        for collect in self._attention_collectors():
            try:
                items += collect()
            except AccessError:
                continue
        items += self._attention_configured()
        groups = []
        for key, label, _badge in self._categories():
            rows = [item for item in items if item['category'] == key]
            if rows:
                groups.append(self._group(key, label, rows))
        known = {key for key, _label, _badge in self._categories()}
        for key in dict.fromkeys(item['category'] for item in items if item['category'] not in known):
            groups.append(self._group(key, key.replace('_', ' ').title(),
                                      [item for item in items if item['category'] == key]))
        decided = {(item['model'], item['resId']) for item in items if item['model'] and item['model'] != 'mail.activity'}
        for source in self.env['ai.home.source'].search([]):
            try:
                rows, records = source._home_rows(self._item)
            except AccessError:
                continue
            if rows:
                items += rows
                decided.update((source.model_name, record_id) for record_id in records.ids)
                groups.append({
                    'key': f'source_{source.id}', 'label': source.name, 'count': len(records),
                    'shown': len(rows),
                    'action': self._list_action(source.model_name, [('id', 'in', records.ids)], source.name),
                })
        # One row per key, whatever the collectors return (keys must be unique on the page).
        seen = set()
        items = [item for item in items if not (item['key'] in seen or seen.add(item['key']))]
        items.sort(key=lambda item: (not item['overdue'], not item['tag'], item['occurred'] or '9'))
        return items, groups, decided

    def _group(self, key, label, rows):
        models_ = {row['model'] for row in rows}
        action = False
        if len(models_) == 1 and next(iter(models_)):
            model = next(iter(models_))
            action = self._list_action(model, [('id', 'in', [row['resId'] for row in rows])], label)
        return {'key': key, 'label': label, 'count': len(rows), 'shown': len(rows), 'action': action}

    def _attention_approvals(self):
        if not self._can_read('approval.center.request'):
            return []
        items = []
        domain = [('state', '=', 'submitted'),
                  ('approver_ids', 'any', [('user_id', '=', self.env.uid), ('status', '=', 'submitted')])]
        for request in self.env['approval.center.request'].search(domain, order='write_date asc', limit=LIMIT) \
                .filtered('can_review'):
            overdue = self._approval_overdue(request)
            days = (fields.Datetime.now() - (request.write_date or fields.Datetime.now())).days
            waiting = _('waiting %s days', days) if days > 1 else (_('waiting 1 day') if days == 1 else _('today'))
            items.append(self._item(
                'approval', request, request.name,
                _('Approvals · requested by %(who)s · %(when)s', who=request.requester_id.display_name, when=waiting),
                {'label': _('Approve'), 'method': 'action_approve'},
                {'label': _('Reject'), 'method': 'action_refuse'},
                tag=_('Overdue') if overdue else '', overdue=overdue, occurred=request.write_date))
        return items

    def _attention_decisions(self):
        """Activities of a type marked "Decision on Home", assigned to the user."""
        types = self.env['mail.activity.type'].search([('home_decision', '=', True)])
        if not types:
            return []
        today = self._today()
        activities = self.env['mail.activity'].search(
            [('user_id', '=', self.env.uid), ('activity_type_id', 'in', types.ids)],
            order='date_deadline asc, id asc', limit=LIMIT).filtered(lambda a: a.res_model in self.env)
        apps = self._app_names(activities.mapped('res_model'))
        items = []
        for activity in activities:
            overdue = bool(activity.date_deadline and activity.date_deadline < today)
            meta = ' · '.join(part for part in (apps.get(activity.res_model), activity.res_name,
                                                 activity.date_deadline and self._due_text(activity.date_deadline, today))
                              if part)
            item = self._item('decision', activity, activity.summary or activity.activity_type_id.name, meta,
                              {'label': _('Done'), 'method': 'action_done'}, {'label': _('Open'), 'open': True},
                              tag=_('Overdue') if overdue else '', overdue=overdue,
                              occurred=fields.Datetime.to_datetime(activity.date_deadline))
            # Opening an activity opens the document it is on.
            item['openModel'], item['openId'] = activity.res_model, activity.res_id
            items.append(item)
        return items

    def _attention_conversations(self):
        if not self._can_read('omni.conversation'):
            return []
        items = []
        now = fields.Datetime.now()
        domain = [('state', 'in', ['new', 'open', 'waiting']), '|', ('assigned_user_id', '=', self.env.uid),
                  ('assigned_user_id', '=', False)]
        for conversation in self.env['omni.conversation'].search(domain, order='last_message_at asc', limit=LIMIT):
            minutes = int((now - conversation.last_message_at).total_seconds() // 60) if conversation.last_message_at else 0
            who = conversation.contact_name or conversation.identity_id.display_name or conversation.thread_key
            channel = conversation.channel_id.display_name or _('Omnichannel')
            if conversation.assigned_user_id:
                primary, secondary, owner = {'label': _('Open'), 'open': True}, False, who
            else:
                primary = {'label': _('Assign to me'), 'method': 'action_assign_me'}
                secondary, owner = {'label': _('Open'), 'open': True}, _('unassigned')
            items.append(self._item(
                'conversation', conversation, _('%(who)s on %(channel)s', who=who, channel=channel),
                _('Omnichannel · %(owner)s · waiting %(min)s min', owner=owner, min=minutes),
                primary, secondary, occurred=conversation.last_message_at))
        return items

    def _attention_workflows(self):
        if not self._can_read('workflow.run') or not self.env.user.has_group('base.group_system'):
            return []
        items = []
        for run in self.env['workflow.run'].search([('state', '=', 'failed'), ('is_test', '=', False)],
                                                   order='write_date desc', limit=LIMIT):
            items.append(self._item(
                'workflow', run, _('%(flow)s failed on %(record)s', flow=run.workflow_id.name, record=run.name),
                _('Workflow · %s', self._local_time(run.write_date)),
                {'label': _('Retry'), 'method': 'action_retry'}, {'label': _('View run'), 'open': True},
                tag=_('Failed'), occurred=run.write_date))
        return items

    def _attention_ai(self):
        if not self._can_read('ai.agent.run') or not self.env.user.has_group('ai_agent.group_manager'):
            return []
        return [self._item('ai', run, run.name, _('AI Agents · needs a manager check · %s', self._local_time(run.write_date)),
                           {'label': _('Review'), 'open': True}, occurred=run.write_date)
                for run in self.env['ai.agent.run'].search([('state', '=', 'uncertain')], limit=LIMIT)]

    def _attention_configured(self):
        """Notices an administrator configured as Home items (section: Needs your attention)."""
        return [{
            'key': item['key'], 'category': 'notice', 'badge': 'NO', 'model': False, 'resId': False,
            'openAction': False, 'title': item['name'], 'meta': item['subtitle'], 'tag': '', 'overdue': False,
            'occurred': False, 'primary': False, 'secondary': False,
        } for item in self.get_dashboard_items() if item['section'] == 'attention']

    def _remind_approvers(self, request):
        if request._name != 'approval.center.request' or request.requester_id != self.env.user \
                or request.state != 'submitted':
            raise UserError(_('Only the requester can send a reminder while the request is waiting.'))
        partners = request.approver_ids.filtered(lambda a: a.status == 'submitted').user_id.partner_id
        if not partners:
            raise UserError(_('Nobody is set to review this request yet.'))
        request.message_post(body=_('Reminder: this request is waiting for your review.'), partner_ids=partners.ids,
                             message_type='comment', subtype_xmlid='mail.mt_comment')
        return True

    # ------------------------------------------------------------------
    # Right: what just happened; left: recent
    # ------------------------------------------------------------------

    def _team_partner_ids(self):
        employee = self.env.user.employee_id if 'employee_id' in self.env.user._fields else False
        if not employee or not employee.department_id or not self._can_read('hr.employee.public'):
            return set()
        team = self.env['hr.employee.public'].search([('department_id', '=', employee.department_id.id)])
        return set(team.user_id.partner_id.ids)

    def _technical(self, model):
        """Configuration and system records are not news for Home."""
        return model in EXCLUDED_MODELS or model.startswith(('ir.', 'base.', 'res.company', 'res.groups'))

    def _home_feed(self):
        """What other people did on records the user may read (the user's own work is in Recent, on the left).

        For me: Odoo notified the user (mentioned, or following the record), the same list as the Discuss Inbox.
        My team: written by people in the user's department.
        """
        partner = self.env.user.partner_id
        team = self._team_partner_ids()
        since = fields.Datetime.now() - timedelta(days=7)
        messages = self.env['mail.message'].search([
            ('date', '>=', since), ('model', '!=', False), ('res_id', '!=', 0), ('author_id', '!=', partner.id),
            ('model', 'not in', list(EXCLUDED_MODELS)),
            ('message_type', 'in', ['comment', 'email', 'notification', 'tracking']),
        ], order='date desc, id desc', limit=150)
        for_me = set(self.env['mail.notification'].sudo().search([
            ('res_partner_id', '=', partner.id), ('mail_message_id', 'in', messages.ids),
        ]).mail_message_id.ids)
        labels, items, shown = {}, [], set()
        for message in messages:
            if message.model not in self.env or self._technical(message.model):
                continue
            record = self.env[message.model].browse(message.res_id).exists()
            if not record or not record.has_access('read'):
                continue
            text = self._feed_text(message, record)
            if not text or (message.model, message.res_id, message.author_id.id, text) in shown:
                continue
            shown.add((message.model, message.res_id, message.author_id.id, text))
            items.append({
                'key': f'feed-{message.id}',
                'occurred': _iso(message.date),
                'actor': message.author_id.name or message.email_from or _('System'),
                'text': text,
                'app': self._app_label(message.model, labels),
                'forMe': message.id in for_me,
                'team': message.author_id.id in team,
                'model': message.model,
                'resId': message.res_id,
            })
        # Keep enough for each tab: For me / My team / Everything.
        kept, counts = [], {'forMe': 0, 'team': 0, 'all': 0}
        for item in items:
            tabs = [tab for tab in ('forMe', 'team') if item[tab]] + ['all']
            if any(counts[tab] < FEED_LIMIT for tab in tabs):
                for tab in tabs:
                    counts[tab] += 1
                kept.append(item)
        return kept

    def _feed_text(self, message, record):
        if message.message_type == 'tracking':
            change = message.subtype_id.description or message.subtype_id.name
            if change and message.subtype_id != self.env.ref('mail.mt_note'):
                return _('%(change)s · %(record)s', change=change, record=record.display_name)
            return _('updated %s', record.display_name)
        body = ' '.join(html2plaintext(message.body or '').split())
        if not body:
            return ''
        if len(body) > 90:
            body = body[:87] + '…'
        if message.message_type == 'email':
            return _('emailed about %(record)s: %(text)s', record=record.display_name, text=body)
        if message.message_type == 'comment':
            return _('commented on %(record)s: %(text)s', record=record.display_name, text=body)
        return _('%(text)s · %(record)s', text=body, record=record.display_name)

    def _home_recent(self):
        """Records the user worked on most recently: commented on, changed or created."""
        partner = self.env.user.partner_id
        messages = self.env['mail.message'].sudo().search([
            ('author_id', '=', partner.id), ('model', '!=', False), ('res_id', '!=', 0),
            ('model', 'not in', list(EXCLUDED_MODELS)),
        ], order='date desc, id desc', limit=100)
        seen, labels, items = set(), {}, []
        for message in messages:
            key = (message.model, message.res_id)
            if key in seen or message.model not in self.env or self._technical(message.model):
                continue
            seen.add(key)
            record = self.env[message.model].browse(message.res_id).exists()
            if not record or not record.has_access('read'):
                continue
            items.append({'key': f'recent-{message.model}-{message.res_id}', 'name': record.display_name,
                          'app': self._app_label(message.model, labels), 'model': message.model, 'resId': message.res_id,
                          'occurred': _iso(message.date)})
            if len(items) >= RECENT_LIMIT:
                break
        return items
