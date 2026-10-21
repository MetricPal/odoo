from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

# Home shows what fits the screen, then twice that for scrolling.
MY_WORK_LIMIT = 60
LIVE_LIMIT = 20
RUN_LIMIT = 10
# Conversations and technical records are not "work"; keep them out of history.
MY_WORK_EXCLUDED_MODELS = {
    'discuss.channel', 'mail.channel', 'res.users', 'res.users.log', 'mail.message',
    'ai.home.item', 'ir.ui.view', 'ir.actions.server', 'base.automation',
}
AUTOMATION_STATUSES = [
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('draft', 'Draft'),
    ('failed', 'Needs attention'),
]


def _iso(value):
    return fields.Datetime.to_string(value) if value else False


class AiHomeItem(models.Model):
    _name = 'ai.home.item'
    _description = 'AI Home Item'
    _order = 'section, sequence, id'

    name = fields.Char(required=True, translate=True)
    section = fields.Selection(
        selection=[
            ('attention', 'Needs Your Attention'),
            ('automation', 'Automations'),
            ('recent', 'Recent'),
        ],
        required=True,
        index=True,
    )
    subtitle = fields.Char(translate=True)
    occurred_label = fields.Char(translate=True)
    icon_text = fields.Char(help='Short text displayed when the item has no image.')
    tone = fields.Selection(
        selection=[
            ('primary', 'Primary'),
            ('success', 'Success'),
            ('warning', 'Warning'),
            ('danger', 'Danger'),
            ('neutral', 'Neutral'),
            ('info', 'Info'),
        ],
        default='neutral',
        required=True,
    )
    automation_status = fields.Selection(
        AUTOMATION_STATUSES,
        string='Automation status',
        default='active',
        help='Status used by the Automations filter on Home.',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    group_ids = fields.Many2many(
        'res.groups',
        string='Visible to Groups',
        help='Leave empty to show the item to every internal user who can access its company.',
    )
    seen_user_ids = fields.Many2many(
        'res.users',
        'ai_home_item_seen_user_rel',
        'item_id',
        'user_id',
        string='Seen by Users',
        copy=False,
        groups='base.group_system',
    )

    # ------------------------------------------------------------------
    # Static items (configured records)
    # ------------------------------------------------------------------

    @api.model
    def get_dashboard_items(self):
        """Return only dashboard items visible to the current internal user."""
        items = self.search([('active', '=', True)])
        user_groups = self.env.user.all_group_ids
        items = items.filtered(
            lambda item: not item.group_ids or bool(item.group_ids & user_groups)
        )
        items = items.filtered(
            lambda item: item.section != 'recent'
            or self.env.user not in item.sudo().seen_user_ids
        )
        return [
            {
                'id': item.id,
                'key': f'item-{item.id}',
                'name': item.name,
                'section': item.section,
                'subtitle': item.subtitle or '',
                'occurredLabel': item.occurred_label or '',
                'iconText': item.icon_text or item.name[:1].upper(),
                'tone': item.tone,
                'status': item.automation_status or 'active',
                'action': False,
            }
            for item in items
        ]

    @api.model
    def mark_recent_seen(self, item_id):
        """Mark an accessible Recent card as seen for the current user."""
        item = self.search([
            ('id', '=', item_id),
            ('section', '=', 'recent'),
            ('active', '=', True),
        ], limit=1)
        if not item:
            return False
        item.sudo().write({'seen_user_ids': [fields.Command.link(self.env.uid)]})
        return True

    # ------------------------------------------------------------------
    # Live Home data
    # ------------------------------------------------------------------

    @api.model
    def get_home_data(self):
        """Everything Home shows, read with the current user's permissions."""
        return {
            'items': self.get_dashboard_items(),
            'attention': self._live_attention(),
            'automations': self._live_automations(),
            'runs': self._live_workflow_runs(),
            'myWork': self._my_work(),
            'agents': self._usable_agents(),
            'canManageAgents': self.env.user.has_group('ai_agent.group_manager')
            if 'ai.agent' in self.env else False,
        }

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

    def _record_action(self, model, res_id):
        return {'res_model': model, 'res_id': res_id}

    @api.model
    def _live_attention(self):
        user = self.env.user
        items = []
        if self._can_read('approval.center.request'):
            requests = self.env['approval.center.request'].search([
                ('state', '=', 'submitted'),
                ('approver_ids', 'any', [('user_id', '=', user.id), ('status', '=', 'submitted')]),
            ], order='write_date desc', limit=LIVE_LIMIT)
            for request in requests.filtered('can_review'):
                items.append({
                    'key': f'approval-{request.id}',
                    'kind': 'approval',
                    'name': request.name,
                    'subtitle': _('%(category)s · from %(requester)s',
                                  category=request.policy_id.display_name,
                                  requester=request.requester_id.display_name),
                    'occurred': _iso(request.write_date),
                    'tone': 'primary',
                    'iconText': (request.policy_id.name or 'A')[:2].upper(),
                    'action': self._record_action(request._name, request.id),
                })
        today = fields.Date.context_today(self)
        activities = self.env['mail.activity'].search([
            ('user_id', '=', user.id), ('date_deadline', '<=', today),
        ], order='date_deadline asc, id asc', limit=LIVE_LIMIT)
        for activity in activities:
            if activity.res_model not in self.env:
                continue
            overdue = activity.date_deadline < today
            items.append({
                'key': f'activity-{activity.id}',
                'kind': 'activity',
                'name': activity.summary or activity.res_name or activity.activity_type_id.name,
                'subtitle': _('%(type)s · %(when)s', type=activity.activity_type_id.name or _('Activity'),
                              when=_('overdue') if overdue else _('due today')),
                'occurred': _iso(fields.Datetime.to_datetime(activity.date_deadline)),
                'tone': 'danger' if overdue else 'warning',
                'iconText': (activity.activity_type_id.name or 'A')[:2].upper(),
                'action': self._record_action(activity.res_model, activity.res_id),
            })
        if self._can_read('ai.agent.run') and user.has_group('ai_agent.group_manager'):
            for run in self.env['ai.agent.run'].search([('state', '=', 'uncertain')], limit=LIVE_LIMIT):
                items.append({
                    'key': f'ai-run-{run.id}',
                    'kind': 'ai_run',
                    'name': run.name,
                    'subtitle': _('AI request needs a manager check'),
                    'occurred': _iso(run.write_date),
                    'tone': 'warning',
                    'iconText': 'AI',
                    'action': self._record_action(run._name, run.id),
                })
        if self._can_read('workflow.run') and user.has_group('base.group_system'):
            for run in self.env['workflow.run'].search(
                [('state', '=', 'failed'), ('is_test', '=', False)], order='write_date desc', limit=LIVE_LIMIT,
            ):
                items.append({
                    'key': f'workflow-run-{run.id}',
                    'kind': 'workflow_run',
                    'name': run.workflow_id.name,
                    'subtitle': _('Workflow failed on %s', run.name),
                    'occurred': _iso(run.write_date),
                    'tone': 'danger',
                    'iconText': 'WF',
                    'action': self._record_action(run._name, run.id),
                })
        return items

    @api.model
    def _live_automations(self):
        if not self._can_read('workflow.definition') or not self.env.user.has_group('base.group_system'):
            return []
        workflows = self.env['workflow.definition'].search([], order='write_date desc', limit=LIVE_LIMIT)
        failed = {}
        if workflows:
            for workflow, count in self.env['workflow.run']._read_group(
                [('workflow_id', 'in', workflows.ids), ('state', '=', 'failed'), ('is_test', '=', False)],
                ['workflow_id'], ['__count'],
            ):
                failed[workflow.id] = count
        items = []
        for workflow in workflows:
            status = 'failed' if failed.get(workflow.id) else workflow.state
            subtitle = (
                (_('1 failed run') if failed[workflow.id] == 1 else _('%s failed runs', failed[workflow.id]))
                if failed.get(workflow.id)
                else dict(workflow._fields['trigger'].selection).get(workflow.trigger, '')
            )
            items.append({
                'key': f'workflow-{workflow.id}',
                'name': workflow.name,
                'subtitle': subtitle,
                'occurred': _iso(workflow.write_date),
                'tone': {'active': 'success', 'paused': 'neutral', 'draft': 'info', 'failed': 'danger'}[status],
                'status': status,
                'action': self._record_action(workflow._name, workflow.id),
            })
        return items

    @api.model
    def _live_workflow_runs(self):
        """Latest real (non-preview) workflow runs, for workflow administrators."""
        if not self._can_read('workflow.run') or not self.env.user.has_group('base.group_system'):
            return []
        Run = self.env['workflow.run']
        labels = dict(Run._fields['state']._description_selection(self.env))
        items = []
        for run in Run.search([('is_test', '=', False)], order='id desc', limit=RUN_LIMIT):
            items.append({
                'key': f'run-{run.id}',
                'name': run.workflow_id.name,
                'subtitle': run.name,
                'status': run.state,
                'statusLabel': labels.get(run.state, run.state),
                'occurred': _iso(run.finished_at or run.write_date or run.started_at),
                'action': self._record_action(run._name, run.id),
            })
        return items

    @api.model
    def _my_work(self):
        """Records the user recently commented on, changed or created, newest first."""
        partner = self.env.user.partner_id
        messages = self.env['mail.message'].sudo().search([
            ('author_id', '=', partner.id),
            ('model', '!=', False),
            ('res_id', '!=', 0),
            ('model', 'not in', list(MY_WORK_EXCLUDED_MODELS)),
            ('message_type', 'in', ['comment', 'tracking', 'notification', 'email', 'email_outgoing']),
        ], order='date desc, id desc', limit=300)
        seen, items = set(), []
        model_names = {}
        for message in messages:
            key = (message.model, message.res_id)
            if key in seen or message.model not in self.env:
                continue
            seen.add(key)
            record = self.env[message.model].browse(message.res_id).exists()
            if not record or not record.has_access('read'):
                continue
            if message.model not in model_names:
                model_names[message.model] = self.env['ir.model']._get(message.model).name or message.model
            if message.message_type == 'comment':
                what = _('You commented')
            elif message.message_type == 'tracking':
                what = _('You updated')
            else:
                what = _('You worked on')
            items.append({
                'key': f'work-{message.model}-{message.res_id}',
                'name': record.display_name,
                'subtitle': f'{model_names[message.model]} · {what}',
                'occurred': _iso(message.date),
                'iconText': (model_names[message.model] or '?')[:2].upper(),
                'action': self._record_action(message.model, message.res_id),
            })
            if len(items) >= MY_WORK_LIMIT:
                break
        return items
