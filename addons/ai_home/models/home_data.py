"""Home page data: greeting, live tiles, items that need the user, recent activity, the day and recent records.

Everything is read with the current user's permissions. A section whose app is not installed, or that the user may
not read, is left out. Buttons on Home only call the whitelisted methods in HOME_ACTIONS, as the current user, so
the target model's own checks (approvers, owners, managers) still decide.
"""

from datetime import UTC, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import formatLang, html2plaintext

LIMIT = 20
FEED_LIMIT = 6
RECENT_LIMIT = 4
# Not "work": conversations, technical and Home records stay out of recent records and the feed.
EXCLUDED_MODELS = {
    'discuss.channel', 'mail.channel', 'res.users', 'res.users.log', 'mail.message', 'ai.home.item',
    'ir.ui.view', 'ir.actions.server', 'base.automation', 'ai.agent.conversation', 'ai.agent.run',
}
# What the buttons on Home may do: (model, method) run as the current user.
HOME_ACTIONS = {
    ('approval.center.request', 'action_approve'),
    ('approval.center.request', 'action_refuse'),
    ('approval.center.request', 'home_remind'),
    ('mail.activity', 'action_done'),
    ('mail.activity', 'action_reschedule_tomorrow'),
    ('omni.conversation', 'action_assign_me'),
    ('workflow.run', 'action_retry'),
}
# Dot colours, the same meanings as Odoo activities: red overdue or failed, orange due today or waiting, green on track.
GOOD, WARN, BAD = 'good', 'warn', 'bad'
WAIT_WARN, WAIT_BAD = 5, 30  # minutes a conversation may wait before it turns orange, then red


def _iso(value):
    return fields.Datetime.to_string(value) if value else False


class AiHomeItem(models.Model):
    _inherit = 'ai.home.item'

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    @api.model
    def get_home_data(self):
        role = self._home_role()
        attention = self._home_attention()
        agents = self._usable_agents()
        overdue = sum(1 for item in attention if item.get('overdue'))
        return {
            'firstName': (self.env.user.name or '').split(' ')[0],
            'roleLabel': self._home_role_label(role),
            'summary': self._home_summary(role, attention, overdue),
            'live': self._home_live(role),
            'attention': attention,
            'feed': self._home_feed(),
            'day': self._home_day(),
            'recent': self._home_recent(),
            'quickActions': [] if agents else self._home_quick_actions(role),
            'agents': agents,
            'prompts': self._home_prompts(role) if agents else [],
            'canManageAgents': self.env.user.has_group('ai_agent.group_manager') if 'ai.agent' in self.env else False,
        }

    @api.model
    def run_home_action(self, model, res_id, method):
        """Run one Home button on one record, as the current user."""
        if (model, method) not in HOME_ACTIONS or model not in self.env:
            raise UserError(_('This action is not available from Home.'))
        record = self.env[model].browse(int(res_id)).exists()
        if not record:
            raise UserError(_('This record no longer exists.'))
        record.check_access('read')
        if method == 'home_remind':
            return self._remind_approvers(record)
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
    # Role
    # ------------------------------------------------------------------

    def _home_role(self):
        """Which set of tiles and suggestions fits the user: operations (managers), support or sales."""
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

    def _home_role_label(self, role):
        employee = self.env.user.employee_id if 'employee_id' in self.env.user._fields else False
        if employee and employee.job_title:
            return employee.job_title
        return {'operations': _('Operations manager'), 'support': _('Support agent'), 'sales': _('Sales rep')}[role]

    def _home_summary(self, role, attention, overdue):
        if role == 'support':
            waiting = sum(1 for item in attention if item['category'] == 'conversation')
            return _('%s customers waiting for you', waiting) if waiting != 1 else _('1 customer waiting for you')
        if not attention:
            return _('nothing needs you right now')
        need = _('1 item needs you') if len(attention) == 1 else _('%s items need you', len(attention))
        return _('%(need)s, %(overdue)s overdue', need=need, overdue=overdue) if overdue else need

    def _home_prompts(self, role):
        if role == 'support':
            return [_('Draft a reply to my oldest conversation'), _('Summarize today’s complaints')]
        if role == 'operations':
            return [_('What needs my approval today?'), _('Summarize overnight escalations'),
                    _('Draft the weekly ops update')]
        return []

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

    def _money(self, amount):
        return formatLang(self.env, amount or 0.0, currency_obj=self.env.company.currency_id, digits=0)

    def _today_range(self):
        """Start and end of the user's today, in UTC, for datetime fields."""
        today = fields.Date.context_today(self)
        start = datetime.combine(today, time.min, tzinfo=self.env.tz).astimezone(UTC).replace(tzinfo=None)
        return start, start + timedelta(days=1)

    # ------------------------------------------------------------------
    # Right now
    # ------------------------------------------------------------------

    def _home_live(self, role):
        providers = {
            'operations': ['activities', 'conversations', 'approvals', 'workflows', 'agents', 'sales_today', 'team'],
            'support': ['activities', 'my_queue', 'team_queue', 'my_requests'],
            'sales': ['activities', 'pipeline', 'quotes_today', 'meetings', 'my_requests', 'orders_month'],
        }[role]
        tiles = []
        for key in providers:
            try:
                tile = getattr(self, '_tile_' + key)()
            except AccessError:
                tile = None
            if tile:
                tiles.append(dict(tile, key=key))
        return tiles

    def _tile(self, label, value, sub, tone, action=False):
        return {'label': label, 'value': str(value), 'sub': sub, 'tone': tone, 'action': action}

    def _list_action(self, model, domain, name):
        return {'type': 'ir.actions.act_window', 'res_model': model, 'name': name, 'domain': domain,
                'views': [[False, 'list'], [False, 'form']], 'target': 'current'}

    def _tile_activities(self):
        """The user's Odoo activities, coloured like Odoo's activity list: overdue red, today orange, planned green."""
        today = fields.Date.context_today(self)
        domain = [('user_id', '=', self.env.uid)]
        Activity = self.env['mail.activity']
        total = Activity.search_count(domain)
        overdue = Activity.search_count(domain + [('date_deadline', '<', today)])
        due_today = Activity.search_count(domain + [('date_deadline', '=', today)])
        if overdue:
            sub, tone = _('%(overdue)s overdue · %(today)s today', overdue=overdue, today=due_today), BAD
        elif due_today:
            sub, tone = _('%s due today', due_today), WARN
        else:
            sub, tone = (_('all planned') if total else _('nothing planned')), GOOD
        return self._tile(_('My activities'), total, sub, tone,
                          self._list_action('mail.activity', domain, _('My activities')))

    def _tile_conversations(self):
        if not self._can_read('omni.conversation'):
            return None
        Conversation = self.env['omni.conversation']
        domain = [('state', 'in', ['new', 'open', 'waiting'])]
        waiting = [('state', 'in', ['new', 'waiting'])]
        now = fields.Datetime.now()
        late = Conversation.search_count(waiting + [('last_message_at', '<', now - timedelta(minutes=WAIT_WARN))])
        very_late = Conversation.search_count(waiting + [('last_message_at', '<', now - timedelta(minutes=WAIT_BAD))])
        if very_late:
            sub, tone = _('%(count)s waiting over %(min)s min', count=very_late, min=WAIT_BAD), BAD
        elif late:
            sub, tone = _('%(count)s waiting over %(min)s min', count=late, min=WAIT_WARN), WARN
        else:
            sub, tone = _('none waiting'), GOOD
        return self._tile(_('Conversations open'), Conversation.search_count(domain), sub, tone,
                          self._list_action('omni.conversation', domain, _('Conversations')))

    def _approval_domain(self):
        return [('state', '=', 'submitted'),
                ('approver_ids', 'any', [('user_id', '=', self.env.uid), ('status', '=', 'submitted')])]

    def _tile_approvals(self):
        if not self._can_read('approval.center.request'):
            return None
        requests = self.env['approval.center.request'].search(self._approval_domain()).filtered('can_review')
        overdue = sum(1 for request in requests if self._approval_overdue(request))
        due_today = sum(1 for request in requests if self._approval_due_today(request))
        if overdue:
            sub, tone = _('%s overdue', overdue), BAD
        elif due_today:
            sub, tone = _('%s due today', due_today), WARN
        else:
            sub, tone = _('none overdue'), GOOD
        return self._tile(_('Approvals pending'), len(requests), sub, tone,
                          self._list_action('approval.center.request', [('id', 'in', requests.ids)], _('Approvals')))

    def _tile_workflows(self):
        if not self._can_read('workflow.definition') or not self.env.user.has_group('base.group_system'):
            return None
        start, _end = self._today_range()
        failed = self.env['workflow.run'].search_count([('state', '=', 'failed'), ('is_test', '=', False),
                                                        ('write_date', '>=', start)])
        running = self.env['workflow.definition'].search_count([('state', '=', 'active')])
        return self._tile(_('Workflows running'), running,
                          _('%s failed today', failed) if failed else _('no failures today'), BAD if failed else GOOD,
                          self._list_action('workflow.definition', [('state', '=', 'active')], _('Workflows')))

    def _tile_agents(self):
        if not self._can_read('ai.agent') or not self.env.user.has_group('ai_agent.group_manager'):
            return None
        start, _end = self._today_range()
        actions = self.env['ai.agent.run'].search_count([('create_date', '>=', start)])
        return self._tile(_('AI agents active'), self.env['ai.agent'].search_count([('state', '=', 'active')]),
                          _('%s requests today', actions), GOOD,
                          self._list_action('ai.agent', [('state', '=', 'active')], _('AI agents')))

    def _tile_sales_today(self):
        if not self._can_read('sale.order'):
            return None
        start, end = self._today_range()
        domain = [('state', '=', 'sale'), ('date_order', '>=', start), ('date_order', '<', end)]
        orders = self.env['sale.order'].search(domain)
        total = sum(order.currency_id._convert(order.amount_total, self.env.company.currency_id, self.env.company,
                                               fields.Date.today()) for order in orders)
        return self._tile(_('Sales today'), self._money(total), _('%s orders', len(orders)), GOOD,
                          self._list_action('sale.order', domain, _('Sales today')))

    def _tile_team(self):
        if not self._can_read('hr.employee.public'):
            return None
        Employee = self.env['hr.employee.public']
        employee = self.env.user.employee_id if 'employee_id' in self.env.user._fields else False
        domain = [('company_id', '=', self.env.company.id)]
        if employee and employee.department_id:
            domain = [('department_id', '=', employee.department_id.id)]
        team = Employee.search(domain)
        if not team:
            return None
        online = sum(1 for member in team if member.hr_presence_state == 'present')
        sub = _('%s people', len(team))
        if 'is_absent' in Employee._fields:
            absent = sum(1 for member in team if member.is_absent)
            sub = _('%s on leave', absent) if absent else _('nobody on leave')
        return self._tile(_('Team online'), '%s / %s' % (online, len(team)), sub, GOOD)

    def _tile_my_queue(self):
        if not self._can_read('omni.conversation'):
            return None
        mine = self.env['omni.conversation'].search([('assigned_user_id', '=', self.env.uid),
                                                     ('state', 'in', ['new', 'open', 'waiting'])],
                                                    order='last_message_at asc')
        oldest = mine.filtered('last_message_at')[:1]
        sub, tone = _('nobody waiting'), GOOD
        if oldest:
            minutes = int((fields.Datetime.now() - oldest.last_message_at).total_seconds() // 60)
            sub = _('oldest waiting %s min', minutes)
            tone = BAD if minutes >= WAIT_BAD else (WARN if minutes >= WAIT_WARN else GOOD)
        return self._tile(_('My queue'), len(mine), sub, tone,
                          self._list_action('omni.conversation', [('id', 'in', mine.ids)], _('My queue')))

    def _tile_team_queue(self):
        if not self._can_read('omni.conversation'):
            return None
        Conversation = self.env['omni.conversation']
        domain = [('state', 'in', ['new', 'open', 'waiting'])]
        unassigned = Conversation.search_count(domain + [('assigned_user_id', '=', False)])
        return self._tile(_('Team queue'), Conversation.search_count(domain),
                          _('%s unassigned', unassigned) if unassigned else _('all assigned'),
                          WARN if unassigned else GOOD, self._list_action('omni.conversation', domain, _('Team queue')))

    def _tile_my_requests(self):
        if not self._can_read('approval.center.request'):
            return None
        domain = [('requester_id', '=', self.env.uid), ('state', '=', 'submitted')]
        count = self.env['approval.center.request'].search_count(domain)
        return self._tile(_('My requests pending'), count, _('awaiting approval') if count else _('nothing waiting'),
                          WARN if count else GOOD, self._list_action('approval.center.request', domain, _('My requests')))

    def _tile_pipeline(self):
        if not self._can_read('crm.lead'):
            return None
        domain = [('user_id', '=', self.env.uid), ('type', '=', 'opportunity'), ('active', '=', True),
                  ('won_status', '=', 'pending')]
        deals = self.env['crm.lead'].search(domain)
        return self._tile(_('My pipeline'), self._money(sum(deals.mapped('expected_revenue'))),
                          _('%s open deals', len(deals)), GOOD, self._list_action('crm.lead', domain, _('My pipeline')))

    def _tile_quotes_today(self):
        if not self._can_read('sale.order'):
            return None
        start, end = self._today_range()
        domain = [('user_id', '=', self.env.uid), ('state', '=', 'sent'), ('write_date', '>=', start),
                  ('write_date', '<', end)]
        open_quotes = self.env['sale.order'].search_count([('user_id', '=', self.env.uid), ('state', '=', 'sent')])
        return self._tile(_('Quotes sent today'), self.env['sale.order'].search_count(domain),
                          _('%s open quotes', open_quotes), GOOD, self._list_action('sale.order', domain, _('Quotes')))

    def _my_events_today(self):
        if not self._can_read('calendar.event'):
            return []
        start, end = self._today_range()
        return self.env['calendar.event'].search([('partner_ids', 'in', self.env.user.partner_id.id),
                                                  ('start', '<', end), ('stop', '>=', start)], order='start')

    def _tile_meetings(self):
        if not self._can_read('calendar.event'):
            return None
        events = self._my_events_today()
        upcoming = events.filtered(lambda e: e.start >= fields.Datetime.now() and not e.allday)[:1]
        sub = _('next at %s', self._local_time(upcoming.start)) if upcoming else _('none left today')
        return self._tile(_('Meetings today'), len(events), sub, GOOD)

    def _tile_orders_month(self):
        if not self._can_read('sale.order'):
            return None
        first = fields.Date.context_today(self).replace(day=1)
        domain = [('user_id', '=', self.env.uid), ('state', '=', 'sale'), ('date_order', '>=', first)]
        orders = self.env['sale.order'].search(domain)
        return self._tile(_('Orders this month'), len(orders), self._money(sum(orders.mapped('amount_untaxed'))), GOOD,
                          self._list_action('sale.order', domain, _('Orders this month')))

    def _local_time(self, value):
        return fields.Datetime.context_timestamp(self, value).strftime('%H:%M') if value else ''

    # ------------------------------------------------------------------
    # Needs your attention
    # ------------------------------------------------------------------

    def _review_deadlines(self, request):
        """Deadlines of the user's review activities on the request (from Odoo activities)."""
        return [activity.date_deadline for activity in request.activity_ids
                if activity.user_id == self.env.user and activity.date_deadline]

    def _approval_due_today(self, request):
        return fields.Date.context_today(self) in self._review_deadlines(request)

    def _approval_overdue(self, request):
        today = fields.Date.context_today(self)
        return any(activity.date_deadline and activity.date_deadline < today
                   for activity in request.activity_ids if activity.user_id == self.env.user)

    def _item(self, category, record, title, meta, primary, secondary=False, tag='', overdue=False, occurred=False,
              open_action=False):
        """One row; buttons are {label, method} (run on the server) or {label, open: True} (open the record, or
        open_action when given)."""
        return {
            'openAction': open_action,
            'key': f'{category}-{record._name}-{record.id}',
            'category': category,
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
        return [self._attention_approvals, self._attention_conversations, self._attention_workflows,
                self._attention_ai, self._attention_activities, self._attention_sales]

    def _home_attention(self):
        items = []
        for collect in self._attention_collectors():
            try:
                items += collect()
            except AccessError:
                continue
        items += self._attention_configured()
        # Most urgent first: overdue, then tagged, then oldest.
        return sorted(items, key=lambda item: (not item['overdue'], not item['tag'], item['occurred'] or '9'))

    def _attention_approvals(self):
        if not self._can_read('approval.center.request'):
            return []
        items = []
        Request = self.env['approval.center.request']
        for request in Request.search(self._approval_domain(), order='write_date asc', limit=LIMIT).filtered('can_review'):
            overdue = self._approval_overdue(request)
            days = (fields.Datetime.now() - (request.write_date or fields.Datetime.now())).days
            waiting = _('waiting %s days', days) if days > 1 else (_('waiting 1 day') if days == 1 else _('today'))
            items.append(self._item(
                'approval', request, request.name,
                _('Approvals · requested by %(who)s · %(when)s', who=request.requester_id.display_name, when=waiting),
                {'label': _('Approve'), 'method': 'action_approve'},
                {'label': _('Reject'), 'method': 'action_refuse'},
                tag=_('Overdue') if overdue else '', overdue=overdue, occurred=request.write_date))
        for request in Request.search([('requester_id', '=', self.env.uid), ('state', '=', 'submitted')],
                                      order='write_date asc', limit=LIMIT):
            pending = request.approver_ids.filtered(lambda a: a.status == 'submitted').user_id
            items.append(self._item(
                'approval', request, _('Your request %s is waiting', request.name),
                _('Approvals · approver %s', ', '.join(pending.mapped('name')) or _('not set')),
                {'label': _('Remind'), 'method': 'home_remind'}, {'label': _('View'), 'open': True},
                occurred=request.write_date))
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

    def _attention_activities(self):
        today = fields.Date.context_today(self)
        items = []
        # Approval reviews already show as approvals.
        skip = self.env.ref('approval_center.mail_act_approval_review', raise_if_not_found=False)
        for activity in self.env['mail.activity'].search([('user_id', '=', self.env.uid), ('date_deadline', '<=', today)],
                                                         order='date_deadline asc, id asc', limit=LIMIT):
            if activity.res_model not in self.env or (skip and activity.activity_type_id == skip):
                continue
            overdue = activity.date_deadline < today
            days = (today - activity.date_deadline).days
            when = _('due today') if not overdue else (_('due yesterday') if days == 1 else _('due %s days ago', days))
            title = activity.summary or activity.activity_type_id.name or _('Activity')
            meta = _('Activity · %(record)s · %(when)s', record=activity.res_name or '', when=when)
            item = self._item('activity', activity, title, meta, {'label': _('Done'), 'method': 'action_done'},
                              {'label': _('Reschedule'), 'method': 'action_reschedule_tomorrow'},
                              tag=_('Overdue') if overdue else '', overdue=overdue,
                              occurred=fields.Datetime.to_datetime(activity.date_deadline))
            # Opening an activity opens the document it is on.
            item['openModel'], item['openId'] = activity.res_model, activity.res_id
            items.append(item)
        return items

    def _attention_sales(self):
        if not self._can_read('sale.order'):
            return []
        today = fields.Date.context_today(self)
        quotes = self.env['sale.order'].search([('user_id', '=', self.env.uid), ('state', 'in', ['draft', 'sent']),
                                                ('validity_date', '>=', today),
                                                ('validity_date', '<=', today + relativedelta(days=1))], limit=LIMIT)
        return [self._item('sales', quote, _('Quote %s expires %s', quote.name,
                                             _('today') if quote.validity_date == today else _('tomorrow')),
                           _('Sales · %(customer)s · %(amount)s', customer=quote.partner_id.display_name,
                             amount=formatLang(self.env, quote.amount_total, currency_obj=quote.currency_id)),
                           {'label': _('Open'), 'open': True},
                           tag=_('Expires today') if quote.validity_date == today else _('Expires tomorrow'))
                for quote in quotes]

    def _attention_configured(self):
        """Notices an administrator configured as Home items (section: Needs your attention)."""
        return [{
            'key': item['key'], 'category': 'activity', 'model': False, 'resId': False, 'openAction': False,
            'title': item['name'],
            'meta': item['subtitle'], 'tag': '', 'overdue': False, 'occurred': False,
            'primary': False, 'secondary': False,
        } for item in self.get_dashboard_items() if item['section'] == 'attention']

    def _remind_approvers(self, request):
        if request.requester_id != self.env.user or request.state != 'submitted':
            raise UserError(_('Only the requester can send a reminder while the request is waiting.'))
        partners = request.approver_ids.filtered(lambda a: a.status == 'submitted').user_id.partner_id
        if not partners:
            raise UserError(_('Nobody is set to review this request yet.'))
        request.message_post(body=_('Reminder: this request is waiting for your review.'), partner_ids=partners.ids,
                             message_type='comment', subtype_xmlid='mail.mt_comment')
        return True

    # ------------------------------------------------------------------
    # What just happened, my day, recently opened, quick actions
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

    def _app_label(self, model, cache):
        if model not in cache:
            cache[model] = self.env['ir.model']._get(model).name or model
        return cache[model]

    def _home_feed(self):
        """Latest changes and comments on records the user may read, with the scope each one belongs to."""
        partner = self.env.user.partner_id
        team = self._team_partner_ids()
        since = fields.Datetime.now() - timedelta(days=7)
        messages = self.env['mail.message'].search([
            ('date', '>=', since), ('model', '!=', False), ('res_id', '!=', 0),
            ('model', 'not in', list(EXCLUDED_MODELS)), ('message_type', 'in', ['comment', 'notification', 'tracking']),
        ], order='date desc, id desc', limit=60)
        labels, items, shown = {}, [], set()
        for message in messages:
            if message.model not in self.env or self._technical(message.model):
                continue
            record = self.env[message.model].browse(message.res_id).exists()
            if not record or not record.has_access('read'):
                continue
            mine = message.author_id == partner or partner in message.partner_ids
            text = self._feed_text(message, record)
            if not text or (message.model, message.res_id, message.author_id.id, text) in shown:
                continue
            shown.add((message.model, message.res_id, message.author_id.id, text))
            items.append({
                'key': f'feed-{message.id}',
                'occurred': _iso(message.date),
                'actor': _('You') if message.author_id == partner else (message.author_id.name or _('System')),
                'text': text,
                'app': self._app_label(message.model, labels),
                'scope': 'mine' if mine else ('team' if message.author_id.id in team else 'all'),
                'model': message.model,
                'resId': message.res_id,
            })
        # Keep enough of each scope for the Mine / My team / Everything tabs.
        kept, counts = [], {'mine': 0, 'team': 0, 'all': 0}
        for item in items:
            if counts[item['scope']] < FEED_LIMIT:
                counts[item['scope']] += 1
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
        if message.message_type == 'comment':
            return _('commented on %(record)s: %(text)s', record=record.display_name, text=body)
        return _('%(text)s · %(record)s', text=body, record=record.display_name)

    def _home_day(self):
        rows = []
        for event in self._my_events_today()[:4]:
            rows.append({'key': f'event-{event.id}', 'time': _('All day') if event.allday else self._local_time(event.start),
                         'text': event.name, 'model': 'calendar.event', 'resId': event.id})
        due = self.env['mail.activity'].search_count([('user_id', '=', self.env.uid),
                                                      ('date_deadline', '=', fields.Date.context_today(self))])
        if due:
            rows.append({'key': 'due', 'time': _('Today'),
                         'text': _('1 task due') if due == 1 else _('%s tasks due', due), 'model': False, 'resId': False})
        return rows

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
                          'app': self._app_label(message.model, labels), 'model': message.model, 'resId': message.res_id})
            if len(items) >= RECENT_LIMIT:
                break
        return items

    def _home_quick_actions(self, role):
        candidates = {
            'sales': [('sale.order', _('Quotation'), {}), ('crm.lead', _('Opportunity'), {'default_type': 'opportunity'}),
                      ('res.partner', _('Contact'), {})],
        }.get(role, [('res.partner', _('Contact'), {}), ('project.task', _('Task'), {}), ('hr.expense', _('Expense'), {})])
        return [{'key': model, 'label': label, 'model': model, 'context': context}
                for model, label, context in candidates
                if model in self.env and self.env[model].has_access('create')]
