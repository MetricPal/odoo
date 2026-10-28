"""Campaign lifecycle: Market Research › Planning › Execution › Results › Evaluation.

The proposal (the campaign in Market Research) is approved according to its type: Paid goes HOD › Finance › CEO,
Owned goes to the HOD, Earned goes HOD › CEO (the routes are configurable). Each approval is an Odoo To-Do activity
assigned to the approver; marking it done approves it and creates the next one. After the last approval the proposal
is frozen as a numbered version and the campaign moves to Planning. Later stages follow the channels: Execution once
the campaign is approved and scheduled, Results once it has finished, Evaluation when the owner starts it.
"""

from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.tools import formatLang

from odoo.addons.marketing_intel.models.fixers import BRANDS, can_fix, whom_to_ask

PHASES = [('research', 'Market Research'), ('planning', 'Planning'), ('execution', 'Execution'),
          ('results', 'Results'), ('evaluation', 'Evaluation')]
PROPOSAL_TYPES = [('paid', 'Paid'), ('owned', 'Owned'), ('earned', 'Earned')]
PROPOSAL_STATES = [('draft', 'Draft'), ('approval', 'In approval'), ('changes', 'Changes requested'),
                   ('approved', 'Approved'), ('refused', 'Refused')]
ROLES = [('hod', 'HOD'), ('finance', 'Finance'), ('ceo', 'CEO')]
STEP_STATES = [('waiting', 'Waiting'), ('current', 'To approve'), ('approved', 'Approved'), ('refused', 'Refused'),
               ('changes', 'Changes requested'), ('skipped', 'Skipped'), ('cancelled', 'Cancelled')]
APPROVAL_DAYS = 3  # due date of an approval activity
ROLE_CAN = {'hod': ('approve', 'changes', 'refuse'), 'finance': ('approve', 'refuse'),
            'ceo': ('approve', 'changes', 'refuse')}


class ApprovalRoute(models.Model):
    _name = 'mi.approval.route'
    _description = 'Proposal approval route'
    _order = 'proposal_type, sequence, id'

    proposal_type = fields.Selection(PROPOSAL_TYPES, required=True)
    sequence = fields.Integer(default=10)
    role = fields.Selection(ROLES, required=True)
    skip_without_budget = fields.Boolean(string='Skip when there is no budget',
                                         help='The step is left out for proposals without a budget.')
    active = fields.Boolean(default=True)


class Approver(models.Model):
    _name = 'mi.approver'
    _description = 'Proposal approver'
    _order = 'company_id, role'

    role = fields.Selection(ROLES, required=True)
    user_id = fields.Many2one('res.users', string='Approver', required=True,
                              domain=[('share', '=', False)])
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    _role_company_unique = models.Constraint('UNIQUE(role, company_id)', 'One approver per role and company.')


class PlanApproval(models.Model):
    _name = 'mi.plan.approval'
    _description = 'Proposal approval step'
    _order = 'round desc, sequence, id'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    round = fields.Integer(default=1, help='Each submission of the proposal is a new round.')
    sequence = fields.Integer(default=10)
    role = fields.Selection(ROLES, required=True)
    user_id = fields.Many2one('res.users', string='Approver')
    state = fields.Selection(STEP_STATES, default='waiting', required=True)
    activity_id = fields.Many2one('mail.activity', ondelete='set null', readonly=True)
    decided_on = fields.Datetime(readonly=True)
    comment = fields.Text()

    def _label(self):
        self.ensure_one()
        return _('%s approval', dict(ROLES)[self.role])

    def _on_approved(self, comment=False):
        for step in self:
            step.sudo().write({'state': 'approved', 'decided_on': fields.Datetime.now(), 'activity_id': False,
                               'comment': comment if comment and comment != _('Approved') else step.comment})


class PlanSnapshot(models.Model):
    _name = 'mi.plan.snapshot'
    _description = 'Approved proposal'
    _order = 'version desc'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    version = fields.Integer(required=True)
    approved_on = fields.Datetime(default=fields.Datetime.now, required=True)
    body = fields.Html(sanitize=True, readonly=True)
    name = fields.Char(compute='_compute_name')

    @api.depends('version', 'approved_on')
    def _compute_name(self):
        for snapshot in self:
            snapshot.name = _('Version %(version)s, approved %(date)s', version=snapshot.version,
                              date=fields.Date.to_string(fields.Datetime.to_datetime(snapshot.approved_on).date())
                              if snapshot.approved_on else '')


class Plan(models.Model):
    _inherit = 'mi.plan'

    phase = fields.Selection(PHASES, string='Stage', default='research', required=True, tracking=True, copy=False,
                             group_expand=True, index=True)
    proposal_type = fields.Selection(PROPOSAL_TYPES, string='Proposal type', tracking=True,
                                     help='Paid: spends money outside (ads, paid social, influencers, outsourced work); '
                                          'approved by HOD, Finance and CEO. Owned: own channels (website, blog, '
                                          'pages, email); approved by the HOD. Earned: coverage, mentions, guest '
                                          'posts; approved by HOD and CEO.')
    proposal_state = fields.Selection(PROPOSAL_STATES, default='draft', required=True, tracking=True, copy=False,
                                      string='Proposal')
    approval_ids = fields.One2many('mi.plan.approval', 'plan_id', string='Approvals', copy=False)
    snapshot_ids = fields.One2many('mi.plan.snapshot', 'plan_id', string='Approved versions', copy=False)
    snapshot_id = fields.Many2one('mi.plan.snapshot', compute='_compute_snapshot', string='Approved proposal')
    approval_route = fields.Char(compute='_compute_approval_route', string='Approvals')
    current_approval_id = fields.Many2one('mi.plan.approval', compute='_compute_current_approval')
    can_decide = fields.Boolean(compute='_compute_current_approval')
    can_request_changes = fields.Boolean(compute='_compute_current_approval')
    phase_label = fields.Char(compute='_compute_phase_label', string='Stage ')
    evaluation_done = fields.Boolean(copy=False, tracking=True, string='Evaluated')
    spend_link = fields.Char(compute='_compute_spend_link', string='Spend ')

    @api.depends('spent', 'budget', 'currency_id')
    def _compute_spend_link(self):
        for plan in self:
            plan.spend_link = _('Spend: %(spent)s of %(budget)s',
                                spent=formatLang(self.env, plan.spent, currency_obj=plan.currency_id),
                                budget=formatLang(self.env, plan.budget, currency_obj=plan.currency_id))

    @api.depends('snapshot_ids')
    def _compute_snapshot(self):
        for plan in self:
            plan.snapshot_id = plan.snapshot_ids[:1]

    @api.depends('proposal_type', 'budget', 'company_id')
    def _compute_approval_route(self):
        for plan in self:
            routes = plan._routes()
            plan.approval_route = ' › '.join(dict(ROLES)[route.role] for route in routes) if routes else False

    @api.depends_context('uid')
    @api.depends('approval_ids.state', 'approval_ids.user_id')
    def _compute_current_approval(self):
        for plan in self:
            current = plan.approval_ids.filtered(lambda a: a.state == 'current')[:1]
            plan.current_approval_id = current
            mine = bool(current) and current.user_id == self.env.user
            plan.can_decide = mine
            plan.can_request_changes = mine and 'changes' in ROLE_CAN[current.role]

    @api.depends('phase', 'state', 'proposal_state', 'approval_ids.state', 'evaluation_done')
    def _compute_phase_label(self):
        names = dict(PHASES)
        for plan in self:
            label = names[plan.phase]
            current = plan.approval_ids.filtered(lambda a: a.state == 'current')[:1]
            if plan.state == 'cancelled':
                label = _('Cancelled')
            elif plan.phase == 'research' and current:
                label = '%s · %s' % (label, current._label())
            elif plan.phase == 'research' and plan.proposal_state in ('changes', 'refused'):
                label = '%s · %s' % (label, dict(PROPOSAL_STATES)[plan.proposal_state])
            elif plan.phase == 'planning' and plan.state == 'review':
                label = '%s · %s' % (label, _('In review'))
            elif plan.phase == 'evaluation' and plan.evaluation_done:
                label = '%s · %s' % (label, _('Done'))
            plan.phase_label = label

    # ------------------------------------------------------------------ routes and approvers

    def _routes(self):
        self.ensure_one()
        if not self.proposal_type:
            return self.env['mi.approval.route']
        routes = self.env['mi.approval.route'].sudo().search([('proposal_type', '=', self.proposal_type)])
        return routes.filtered(lambda r: not (r.skip_without_budget and not self.budget))

    def _approver(self, role):
        """Who approves ``role`` for this campaign: the owner's department manager for HOD (else the configured
        HOD), the configured approver for Finance and CEO."""
        self.ensure_one()
        if role == 'hod':
            employee = self.env['hr.employee'].sudo().search(
                [('user_id', '=', self.user_id.id), ('company_id', 'in', (self.company_id.id, False))], limit=1)
            manager = employee.department_id.manager_id.user_id or employee.parent_id.user_id
            if manager and manager != self.user_id:
                return manager
            if employee.department_id.manager_id.user_id == self.user_id:
                return self.user_id  # the owner is the HOD
        return self.env['mi.approver'].sudo().search(
            [('role', '=', role), ('company_id', '=', self.company_id.id)], limit=1).user_id

    # ------------------------------------------------------------------ submit and decide

    def action_submit_proposal(self):
        """Send the proposal (Market Research) through the approvals of its type."""
        for plan in self:
            plan.check_access('write')
            if plan.is_template:
                raise UserError(_('This is a template: click “Use this template” to start a campaign from it.'))
            if plan.phase != 'research' or plan.proposal_state not in ('draft', 'changes'):
                raise UserError(_('This proposal is already in approval or approved.'))
            if not plan.proposal_type:
                raise UserError(_('Choose the proposal type (Paid, Owned or Earned) first: it decides who approves.'))
            if not plan.channel_ids:
                raise UserError(_('Choose at least one channel: a campaign without a channel is not valid.'))
            routes = plan._routes()
            if not routes:
                raise UserError(_('No approval route is set for %s proposals.',
                                  dict(PROPOSAL_TYPES)[plan.proposal_type]))
            round_no = max(plan.approval_ids.mapped('round') or [0]) + 1
            steps = []
            for route in routes:
                user = plan._approver(route.role)
                if not user:
                    plan._missing_approver(route.role)
                if not user.has_group('marketing_intel.group_mi_user'):
                    raise UserError(_('%(user)s approves as %(role)s but has no access to Marketing: give them the '
                                      'Marketing user right first.', user=user.name, role=dict(ROLES)[route.role]))
                skipped = user == plan.user_id
                steps.append({'plan_id': plan.id, 'round': round_no, 'sequence': route.sequence, 'role': route.role,
                              'user_id': user.id, 'state': 'skipped' if skipped else 'waiting',
                              'comment': _('The owner holds this role.') if skipped else False})
            plan.approval_ids.sudo().filtered(lambda a: a.state in ('waiting', 'current')).state = 'cancelled'
            self.env['mi.plan.approval'].sudo().create(steps)
            plan.sudo().proposal_state = 'approval'
            plan.message_post(body=_('Proposal submitted for approval (%(type)s: %(route)s).',
                                     type=dict(PROPOSAL_TYPES)[plan.proposal_type], route=plan.approval_route))
            plan._advance_approval()
        return True

    def _missing_approver(self, role):
        name = dict(ROLES)[role]
        if can_fix(self.env.user, BRANDS):
            raise RedirectWarning(_('Nobody is set as %s approver for this company.', name),
                                  self.env.ref('marketing_intel_plan.action_approvers').id, _('Set the approvers'))
        raise UserError(_('Nobody is set as %(role)s approver: ask %(who)s to set the approvers.', role=name,
                          who=whom_to_ask(self.env, BRANDS, self.company_id)))

    def _advance_approval(self):
        """Open the next approval as a To-Do activity, or approve the proposal when none is left."""
        self.ensure_one()
        round_no = max(self.approval_ids.mapped('round') or [0])
        step = self.approval_ids.filtered(lambda a: a.round == round_no and a.state == 'waiting').sorted(
            lambda a: (a.sequence, a.id))[:1]
        if not step:
            self._approve_proposal()
            return
        activity = self.sudo().activity_schedule(
            'mail.mail_activity_data_todo', user_id=step.user_id.id,
            date_deadline=fields.Date.context_today(self) + timedelta(days=APPROVAL_DAYS),
            summary=_('%(step)s: %(name)s', step=step._label(), name=self.name),
            note=_('Approve, refuse%(changes)s the proposal on the campaign. Marking this activity done approves it.',
                   changes=_(' or request changes to') if 'changes' in ROLE_CAN[step.role] else ''))
        step.sudo().write({'state': 'current', 'activity_id': activity.id})

    def _approve_proposal(self):
        self.ensure_one()
        version = max(self.snapshot_ids.mapped('version') or [0]) + 1
        self.env['mi.plan.snapshot'].sudo().create({'plan_id': self.id, 'version': version,
                                                     'body': self._proposal_html()})
        self.sudo().write({'proposal_state': 'approved', 'phase': 'planning'})
        self.message_post(body=_('Proposal approved and frozen as version %s. The campaign moves to Planning.',
                                 version))

    def _proposal_html(self):
        """The proposal as approved: what the Market Research and Overview tabs hold."""
        self.ensure_one()
        rows = [(_('Campaign'), self.name), (_('Brand'), self.brand_id.name),
                (_('Proposal type'), dict(PROPOSAL_TYPES).get(self.proposal_type, '')),
                (_('Dates'), '%s → %s' % (self.date_start, self.date_end)),
                (_('Budget'), '%s %s' % (self.budget, self.currency_id.name or '')),
                (_('Channels'), ', '.join(self.channel_ids.mapped('name'))),
                (_('Key message'), self.message), (_('Audience'), self.audience), (_('KPIs'), self.kpis)]
        rows += self._proposal_rows()
        body = Markup('').join(Markup('<tr><th style="text-align:left;padding-right:12px">%s</th><td>%s</td></tr>')
                               % (label, escape(value or '').replace('\n', Markup('<br/>')) if not isinstance(value, Markup) else value)
                               for label, value in rows if value)
        return Markup('<table>%s</table>') % body

    def _proposal_rows(self):
        """Hook: more (label, value) rows for the frozen proposal."""
        return []

    def _decide(self, decision, comment=False):
        """Approve, refuse or request changes on the current approval (only its approver)."""
        self.ensure_one()
        step = self.current_approval_id
        if not step:
            raise UserError(_('Nothing is waiting for approval on this campaign.'))
        if step.user_id != self.env.user and not self.env.su:
            raise UserError(_('Only %s can decide this approval.', step.user_id.name))
        if decision not in ROLE_CAN[step.role]:
            raise UserError(_('%s approves or refuses; it does not request changes.', dict(ROLES)[step.role]))
        if decision == 'approve':
            if step.activity_id:
                step.activity_id.action_feedback(feedback=comment or _('Approved'))  # hook moves on
            else:
                step._on_approved(comment)
                self._advance_approval()
            return True
        state = 'refused' if decision == 'refuse' else 'changes'
        activity = step.activity_id
        step.sudo().write({'state': state, 'decided_on': fields.Datetime.now(), 'comment': comment,
                           'activity_id': False})
        if activity:
            activity.sudo().with_context(mi_approval_internal=True).unlink()
        self.sudo().proposal_state = state
        if state == 'refused':
            self.message_post(body=_('%(step)s refused by %(user)s. %(comment)s', step=step._label(),
                                     user=self.env.user.name, comment=comment or ''))
        else:
            self.message_post(body=_('%(step)s: changes requested by %(user)s. %(comment)s', step=step._label(),
                                     user=self.env.user.name, comment=comment or ''))
            self.sudo().activity_schedule('mail.mail_activity_data_todo', user_id=self.user_id.id,
                                          summary=_('Update the proposal: %s', self.name),
                                          note=comment or _('Changes requested.'))
        return True

    def action_approve_proposal(self):
        self.ensure_one()
        return self._decide('approve')

    def action_decide_proposal(self):
        """Refuse or request changes: asks for a comment."""
        self.ensure_one()
        decision = self.env.context.get('decision', 'refuse')
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.plan.decision', 'view_mode': 'form',
                'target': 'new', 'name': _('Request changes') if decision == 'changes' else _('Refuse the proposal'),
                'context': {'default_plan_id': self.id, 'default_decision': decision}}

    def action_open_spend(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Spend · %s', self.name), 'res_model': 'mi.plan.spend',
                'view_mode': 'list,pivot,graph', 'domain': [('plan_id', '=', self.id)],
                'views': [(self.env.ref('marketing_intel_plan.spend_list').id, 'list'), (False, 'pivot'), (False, 'graph')],
                'context': {'default_plan_id': self.id}}

    def action_view_snapshot(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.plan.snapshot', 'res_id': self.snapshot_id.id,
                'view_mode': 'form', 'target': 'new', 'name': self.snapshot_id.name}

    # ------------------------------------------------------------------ later stages

    def _sync_phase(self):
        for plan in self:
            if plan.is_template or plan.state == 'cancelled':
                continue
            if plan.state in ('scheduled', 'live') and plan.phase in ('research', 'planning'):
                plan.sudo().phase = 'execution'
            elif plan.state == 'done' and plan.phase in ('research', 'planning', 'execution'):
                plan.sudo().phase = 'results'

    def write(self, vals):
        result = super().write(vals)
        if 'state' in vals and not self.env.context.get('mi_no_phase_sync'):
            self._sync_phase()
        return result

    def unlink(self):
        return super(Plan, self.with_context(mi_approval_internal=True)).unlink()

    def action_start_evaluation(self):
        for plan in self:
            if plan.phase != 'results':
                raise UserError(_('The evaluation starts once the results are in.'))
            plan.phase = 'evaluation'
        return True

    def action_mark_evaluated(self):
        self.filtered(lambda p: p.phase == 'evaluation').evaluation_done = True
        return True

    def action_submit_review(self):
        for plan in self:
            if plan.phase == 'research' and not plan.is_template:
                raise UserError(_('Get the proposal approved first: choose the proposal type and click Submit for '
                                  'approval.'))
        return super().action_submit_review()

    def _repeat_run(self, start):
        """A repeating series was approved once: its next runs start in Planning."""
        self = self.with_context(default_phase='planning', default_proposal_state='approved',
                                 default_proposal_type=self.proposal_type)
        return super()._repeat_run(start)

    def _next_step(self):
        self.ensure_one()
        if self.phase == 'research' and self.state not in ('cancelled', 'done') and not self.is_template:
            step = self.current_approval_id
            if self.proposal_state == 'approval' and step:
                return _('Waiting for %(step)s by %(user)s', step=step._label(), user=step.user_id.name), False
            if self.proposal_state == 'changes':
                return _('Update the proposal as asked, then submit it again'), True
            if self.proposal_state == 'refused':
                return _('Proposal refused'), False
            if not self.proposal_type:
                return _('Choose the proposal type, then submit the proposal for approval'), True
            return _('Finish the market research, then submit the proposal for approval'), True
        if self.phase == 'results':
            return _('Check the results, then start the evaluation'), True
        if self.phase == 'evaluation':
            return (_('Evaluated'), False) if self.evaluation_done else (
                _('Write the evaluation, then mark it done'), True)
        return super()._next_step()

    @api.depends_context('uid')
    @api.depends('state', 'user_id', 'worker', 'item_ids.stage', 'review_request_id.state', 'phase',
                 'proposal_state', 'approval_ids.state', 'evaluation_done')
    def _compute_needs_me(self):
        super()._compute_needs_me()
        for plan in self:
            if plan.can_decide:
                plan.my_todo = _('%s: approve or refuse the proposal', plan.current_approval_id._label())
                plan.needs_me = True


class Activity(models.Model):
    _inherit = 'mail.activity'

    def _action_done(self, feedback=False, attachment_ids=None):
        Approval = self.env['mi.plan.approval'].sudo()
        steps = Approval.search([('activity_id', 'in', self.ids), ('state', '=', 'current')])
        for step in steps:
            if step.user_id != self.env.user and not self.env.su:
                raise UserError(_('Only %s can approve this.', step.user_id.name))
            step._on_approved(feedback)
        result = super(Activity, self.with_context(mi_approval_internal=True))._action_done(
            feedback=feedback, attachment_ids=attachment_ids)
        for plan in steps.plan_id:
            plan._advance_approval()
        return result

    def unlink(self):
        if not self.env.context.get('mi_approval_internal'):
            current = self.env['mi.plan.approval'].sudo().search(
                [('activity_id', 'in', self.ids), ('state', '=', 'current')])
            if current:
                raise UserError(_('An approval cannot be cancelled: approve, refuse or request changes on the '
                                  'campaign.'))
        return super().unlink()


class Decision(models.TransientModel):
    _name = 'mi.plan.decision'
    _description = 'Refuse or request changes'

    plan_id = fields.Many2one('mi.plan', required=True)
    decision = fields.Selection([('refuse', 'Refuse'), ('changes', 'Request changes')], required=True)
    comment = fields.Text(required=True, string='Comment')

    def action_confirm(self):
        self.ensure_one()
        self.plan_id._decide(self.decision, self.comment)
        return {'type': 'ir.actions.act_window_close'}
