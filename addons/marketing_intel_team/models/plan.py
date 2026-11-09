"""The review chain (ADR 0016, approved board 5.2).

- A junior's campaign goes to a **senior review** (Approval Center, "Marketing: senior review", the junior's senior
  as approver) before anything is submitted in the channel apps.
- The senior accepts: within the limits the head of department set, the senior releases it ("Marketing: release
  within limits", the senior approves); above them the release goes to the head of department ("Marketing
  campaign"). Request changes sends it back to Content with the comment.
- A senior's own campaign within the limits, and the head of department's, are released by their owner (recorded as
  a release within limits); above the limits a senior's goes to the head of department.
- Without a marketing department for the company, nothing changes (one review, as before).
"""

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import formatLang

from .team import user_role

AUDIENCE_CHANNELS = ('email', 'sms', 'messaging')


class Plan(models.Model):
    _inherit = 'mi.plan'

    senior_review_state = fields.Selection(
        [('none', 'No senior review'), ('waiting', 'Waiting for the senior'), ('accepted', 'Accepted by the senior'),
         ('changes', 'Changes requested')], string='Senior review', default='none', required=True, readonly=True,
        copy=False, tracking=True)
    senior_request_id = fields.Many2one('approval.center.request', readonly=True, copy=False)
    senior_reviewer_id = fields.Many2one('res.users', string='Senior reviewer', readonly=True, copy=False)
    needs_senior_review = fields.Boolean(compute='_compute_review_chain')
    can_senior_decide = fields.Boolean(compute='_compute_review_chain')
    within_limits = fields.Boolean(compute='_compute_review_chain')
    limit_note = fields.Char(compute='_compute_review_chain', string='Release')

    # -- helpers ----------------------------------------------------------------------------------------------
    def _team(self):
        """The marketing department (the team), or an empty recordset."""
        self.ensure_one()
        return self.env['hr.department']._mi_department(self.company_id)

    def _money(self, amount):
        return formatLang(self.env, amount, currency_obj=self.currency_id or self.company_id.currency_id)

    def _audience(self):
        """People the campaign's email, SMS and messages go to (what each app counts today)."""
        self.ensure_one()
        return sum(item.result_audience for item in self.item_ids if item.channel in AUDIENCE_CHANNELS)

    def _releaser(self):
        """Who releases: the senior who accepted a junior's campaign, else the owner."""
        self.ensure_one()
        return self.senior_reviewer_id if self.senior_review_state == 'accepted' else self.user_id

    @api.depends_context('uid')
    @api.depends('user_id', 'company_id', 'senior_review_state', 'senior_reviewer_id', 'budget', 'channel_ids')
    def _compute_review_chain(self):
        for plan in self:
            team = plan._team() if not plan.is_template else False
            owner_role = user_role(plan.user_id) if team else False
            plan.needs_senior_review = bool(team) and owner_role == 'junior'
            plan.can_senior_decide = plan.senior_review_state == 'waiting' and plan.state == 'review' and \
                plan.senior_reviewer_id == self.env.user
            if not team:
                plan.within_limits, plan.limit_note = True, False
                continue
            releaser = plan.senior_reviewer_id if plan.needs_senior_review else plan.user_id
            problems = team._limit_problems(plan, releaser) if releaser else [_('No senior chosen')]
            plan.within_limits = not problems
            if problems:
                plan.limit_note = _('%(problems)s: the release goes to %(hod)s.', problems='; '.join(problems),
                                    hod=team.mi_hod_user_id.name or _('the head of department'))
            else:
                plan.limit_note = _('Within the limits: %s can release it.', releaser.name)

    def _team_policy(self, xmlid):
        """The company's copy of one of this module's approval types (made on first use)."""
        self.ensure_one()
        template = self.env.ref(xmlid).sudo()
        Policy = self.env['approval.center.policy'].sudo().with_context(active_test=False)
        policy = Policy.search([('model_id', '=', template.model_id.id), ('action_name', '=', template.action_name),
                                ('company_id', '=', self.company_id.id)], limit=1)
        if not policy:
            if template.company_id and template.company_id != self.company_id:
                policy = template.copy({'company_id': self.company_id.id, 'name': template.name})
            else:
                policy = template
                if not policy.company_id:
                    policy.company_id = self.company_id
        if not policy.active:
            raise UserError(_('The approval type “%s” is switched off.', policy.name))
        return policy

    def _open_request(self, policy, approver, reason):
        """An Approval Center request for this campaign with one chosen approver, submitted as the current user."""
        request = self.env['approval.center.request'].sudo().create({
            'name': _('%(type)s: %(name)s (%(brand)s)', type=policy.name, name=self.name, brand=self.brand_id.name),
            'policy_id': policy.id, 'company_id': self.company_id.id, 'requester_id': self.env.uid,
            'target_model': self._name, 'target_res_id': self.id, 'reason': reason,
            'approver_ids': [(5, 0, 0), (0, 0, {'sequence': 1, 'user_id': approver.id, 'required': True,
                                                'status': 'new'})],
        })
        request.with_user(self.env.user).sudo().action_submit()
        return request

    # -- the senior review --------------------------------------------------------------------------------------
    def action_submit_review(self):
        to_senior = self.filtered(lambda p: p.needs_senior_review and p.senior_review_state != 'accepted')
        for plan in to_senior:
            plan._send_to_senior()
        rest = self - to_senior
        if not rest:
            return True
        result = super(Plan, rest).action_submit_review()
        for plan in rest.filtered(lambda p: p.state == 'review' and p.review_request_id):
            plan._release_if_mine()
        return result

    def _send_to_senior(self):
        self.ensure_one()
        self.check_access('write')
        if self.is_template:
            raise UserError(_('This is a template: click “Use this template” to start a campaign from it.'))
        if self.state not in ('brief', 'content'):
            raise UserError(_('This campaign was already reviewed.'))
        if self.phase == 'research':
            raise UserError(_('Get the proposal approved first: choose the proposal type and click Submit for '
                              'approval.'))
        team = self._team()
        senior = team._senior_for(self.user_id)
        if not senior:
            raise UserError(_('Nobody reviews %s\'s work yet: set their manager in Employees, or the marketing '
                              'department\'s manager (Marketing › Configuration › Department).', self.user_id.name))
        self.action_prepare()
        request = self._open_request(self._team_policy('marketing_intel_team.policy_senior_review'), senior,
                                     self._review_summary())
        self.sudo().write({'senior_request_id': request.id, 'senior_reviewer_id': senior.id,
                           'senior_review_state': 'waiting', 'state': 'review'})
        self.message_post(body=_('Sent to %s for the senior review.', senior.name))
        self._sync_state()

    def action_senior_accept(self):
        """The senior accepts: within the limits they release it; above them it goes to the head of department."""
        self.ensure_one()
        if not self.can_senior_decide:
            raise AccessError(_('This campaign is not waiting for your review.'))
        within = self.within_limits
        self.senior_request_id.with_user(self.env.user).sudo(False).action_approve()
        self.invalidate_recordset()
        if within and self.review_request_id and self.review_request_id.state == 'submitted':
            self.action_approve_review()
        return True

    def action_senior_accepted(self):
        """Run by Approval Center as the junior once the senior approved: submit the channels and open the release."""
        for plan in self:
            plan.sudo().write({'senior_review_state': 'accepted', 'state': 'content'})
            plan.message_post(body=_('Accepted by %s in the senior review.', plan.senior_reviewer_id.name))
            super(Plan, plan).action_submit_review()
        return True

    def action_senior_changes(self):
        self.ensure_one()
        if not self.can_senior_decide:
            raise AccessError(_('This campaign is not waiting for your review.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.senior.decision', 'view_mode': 'form',
                'target': 'new', 'name': _('Request changes'), 'context': {'default_plan_id': self.id}}

    def _senior_request_changes(self, comment):
        self.ensure_one()
        self.senior_request_id.with_user(self.env.user).sudo(False).action_refuse()
        self.sudo().write({'senior_review_state': 'changes', 'state': 'content'})
        self.message_post(body=Markup('<p>%s</p><p>%s</p>') % (
            _('%s asked for changes in the senior review.', self.env.user.name), comment))
        self.activity_schedule('mail.mail_activity_data_todo', user_id=self.user_id.id,
                               summary=_('Changes requested by %s', self.env.user.name), note=comment)
        self._sync_state()

    # -- the release ----------------------------------------------------------------------------------------------
    def _open_review_request(self):
        """With a team, the release has one chosen approver: the releaser within the limits, else the head of
        department."""
        self.ensure_one()
        team = self._team()
        if not team:
            return super()._open_review_request()
        if self.review_request_id and self.review_request_id.state not in ('refused', 'cancelled'):
            return
        releaser = self._releaser()
        problems = team._limit_problems(self, releaser)
        if problems:
            if not team.mi_hod_user_id:
                raise UserError(_('%s, and nobody is head of department: set the marketing department\'s manager '
                                  '(Marketing › Configuration › Department).', '; '.join(problems)))
            policy, approver = self._campaign_policy(), team.mi_hod_user_id
            reason = '%s\n\n%s' % ('; '.join(problems), self._review_summary())
        else:
            policy = self._team_policy('marketing_intel_team.policy_release_within_limits')
            approver, reason = releaser, self._review_summary()
        self.sudo().review_request_id = self._open_request(policy, approver, reason)

    def _release_if_mine(self):
        """A senior's own campaign within the limits, or the head of department's: the owner releases it now."""
        self.ensure_one()
        request = self.review_request_id.sudo()
        if self._team() and request.state == 'submitted' and request.policy_id.allow_self_approval \
                and request.approver_ids.user_id == self.env.user:
            self.action_approve_review()

    def action_release_within_limits(self):
        return self.action_release()

    # -- what the campaign says next -------------------------------------------------------------------------------
    def _next_step(self):
        self.ensure_one()
        if self.state == 'review' and self.senior_review_state == 'waiting':
            if self._step_user() == self.senior_reviewer_id:
                return _('Review %s\'s campaign: accept it or request changes', self.user_id.name), False
            return _('Waiting for the senior review by %s', self.senior_reviewer_id.name), False
        return super()._next_step()

    @api.depends_context('uid')
    @api.depends('senior_review_state', 'senior_reviewer_id')
    def _compute_needs_me(self):
        super()._compute_needs_me()
        for plan in self.filtered('can_senior_decide'):
            plan.my_todo = _('Review %s\'s campaign: accept it or request changes', plan.user_id.name)
            plan.needs_me = True


class Request(models.Model):
    _inherit = 'approval.center.request'

    def action_refuse(self):
        """A refused senior review is "changes requested" (the senior decision wizard adds the comment)."""
        result = super().action_refuse()
        for request in self.sudo().filtered(lambda r: r.target_model == 'mi.plan' and r.state == 'refused'):
            plan = self.env['mi.plan'].sudo().browse(request.target_res_id).exists()
            if plan and plan.senior_request_id == request and plan.senior_review_state == 'waiting':
                plan.write({'senior_review_state': 'changes', 'state': 'content'})
        return result
