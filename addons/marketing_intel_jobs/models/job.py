"""Assistant jobs (plan M4, approved boards 11.1 to 11.3, 2026-11-12).

A job is recurring marketing work the Marketing assistant does on a schedule: it reads the system, asks the assistant
when the work needs writing or judgement (``ai.agent.run._ask`` as the assistant user, caller Marketing), and ends in
drafts, notes or to-dos for its owner, never a send or a publish. Each run is kept with its result or the reason it
failed. Health uses the same four words everywhere: Healthy, Failing (the last two runs failed; the owner gets a
to-do with the reason), Waiting for a person (the owner's to-do from the last result is still open), Paused.
"""

from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_datetime

FREQUENCIES = [('hourly', 'Every hour'), ('daily', 'Every day'), ('weekly', 'Every week'), ('monthly', 'Every month')]
WEEKDAYS = [('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'), ('4', 'Friday'),
            ('5', 'Saturday'), ('6', 'Sunday')]
HEALTH = [('healthy', 'Healthy'), ('failing', 'Failing'), ('waiting', 'Waiting for a person'), ('paused', 'Paused'),
          ('off', 'Off')]
KINDS = [
    ('social_posts', 'Weekly social posts'), ('comment_replies', 'Comment replies'),
    ('newsletter', 'Weekly newsletter draft'), ('leads_summary', 'New leads summary'),
    ('performance_summary', 'Weekly performance summary'), ('campaigns_at_risk', 'Campaigns at risk'),
    ('competitor_watch', 'Competitor watch'), ('monthly_report', 'Monthly department report'),
    ('budget_burn', 'Budget burn alert'), ('team_workload', 'Team workload alert'),
]
ROLES = [('junior', 'For juniors (daily work)'), ('senior', "For seniors (the team's results)"),
         ('hod', 'For the head of department')]


class Job(models.Model):
    _name = 'mi.job'
    _description = 'Assistant job'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'role_sequence, sequence, id'

    kind = fields.Selection(KINDS, required=True, readonly=True, string='Ready-made job')
    name = fields.Char(required=True, string='Job')
    description = fields.Text(string='What it does')
    gives = fields.Char(string='Gives', help='What the owner gets from each run.')
    needs = fields.Char(string='Needs', help='What must be set up before it can work.')
    how_it_works = fields.Text(string='How it works')
    role = fields.Selection(ROLES, required=True, default='junior')
    role_sequence = fields.Integer(compute='_compute_role_sequence', store=True)
    sequence = fields.Integer(default=10)
    uses_ai = fields.Boolean(default=True, readonly=True, string='Uses the assistant')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    brand_id = fields.Many2one('mi.brand', string='Brand', check_company=True,
                               help='Empty: every brand of the company.')
    owner_id = fields.Many2one('res.users', string='Owner', tracking=True, domain=[('share', '=', False)],
                               help='Gets the result and the to-dos.')
    state = fields.Selection([('off', 'Off'), ('on', 'On'), ('paused', 'Paused')], default='off', required=True,
                             tracking=True)
    frequency = fields.Selection(FREQUENCIES, default='weekly', required=True)
    weekday = fields.Selection(WEEKDAYS, default='0', string='Day')
    month_day = fields.Integer(default=1, string='Day of the month')
    hour = fields.Integer(default=8, string='At (hour)', help="In the owner's timezone.")
    ai_daily_limit = fields.Integer(default=10, string='AI limit', help='At most this many questions a day.')
    next_run = fields.Datetime(readonly=True, copy=False, string='Next run')
    run_ids = fields.One2many('mi.job.run', 'job_id', readonly=True)
    health = fields.Selection(HEALTH, compute='_compute_health', search='_search_health', string='Health')
    schedule_label = fields.Char(compute='_compute_labels', string='Schedule')
    last_run_label = fields.Char(compute='_compute_labels', string='Last run')
    last_error = fields.Text(compute='_compute_labels', string='Last failure')
    success_label = fields.Char(compute='_compute_labels', string='Success (30 days)')
    ai_questions_30d = fields.Integer(compute='_compute_labels', string='AI questions (30 days)')
    average_time_label = fields.Char(compute='_compute_labels', string='Average time')
    outputs_30d = fields.Integer(compute='_compute_labels', string='Results (30 days)')

    @api.depends('role')
    def _compute_role_sequence(self):
        order = {'junior': 1, 'senior': 2, 'hod': 3}
        for job in self:
            job.role_sequence = order.get(job.role, 9)

    @api.depends('state', 'run_ids.state', 'run_ids.activity_id')
    def _compute_health(self):
        # Not stored: the owner's to-do is archived (Odoo 20 keeps done activities) or deleted when it is marked
        # done, which a stored value would not notice.
        for job in self:
            if job.state == 'off':
                job.health = 'off'
                continue
            if job.state == 'paused':
                job.health = 'paused'
                continue
            finished = job.run_ids.filtered(lambda r: r.state in ('done', 'failed')).sorted('id', reverse=True)
            if len(finished) >= 2 and all(r.state == 'failed' for r in finished[:2]):
                job.health = 'failing'
            elif finished[:1].state == 'done' and finished[:1].activity_id.exists().filtered('active'):
                job.health = 'waiting'
            else:
                job.health = 'healthy'

    def _search_health(self, operator, value):
        if operator not in ('in', 'not in', '=', '!='):
            raise UserError(_('Unsupported search.'))
        values = {value} if operator in ('=', '!=') else set(value)
        jobs = self.sudo().search([])
        matching = jobs.filtered(lambda job: job.health in values).ids
        return [('id', 'in' if operator in ('in', '=') else 'not in', matching)]

    def _compute_labels(self):
        since = fields.Datetime.now() - timedelta(days=30)
        days = dict(WEEKDAYS)
        for job in self:
            if job.frequency == 'hourly':
                job.schedule_label = _('Every hour')
            elif job.frequency == 'daily':
                job.schedule_label = _('Every day, %02d:00', job.hour)
            elif job.frequency == 'weekly':
                job.schedule_label = _('Every %(day)s, %(hour)02d:00', day=days.get(job.weekday or '0'), hour=job.hour)
            else:
                job.schedule_label = _('Every month on the %(day)s, %(hour)02d:00', day=job.month_day, hour=job.hour)
            runs = job.run_ids.sorted('id', reverse=True)
            last = runs[:1]
            job.last_run_label = '%s · %s' % (job._when_label(last.started_at),
                                              last.result or last.state_label) if last else ''
            failed = runs.filtered(lambda r: r.state == 'failed')[:1]
            job.last_error = failed.error if failed and runs[:1] == failed else ''
            recent = runs.filtered(lambda r: r.started_at and r.started_at >= since and r.state in ('done', 'failed'))
            job.success_label = _('%(done)s / %(all)s', done=len(recent.filtered(lambda r: r.state == 'done')),
                                  all=len(recent)) if recent else '—'
            job.ai_questions_30d = sum(recent.mapped('ai_questions'))
            job.outputs_30d = sum(recent.mapped('output_count'))
            timed = [(r.finished_at - r.started_at).total_seconds() for r in recent
                     if r.finished_at and r.started_at and r.state == 'done']
            if timed:
                seconds = int(sum(timed) / len(timed))
                job.average_time_label = _('%(m)s min %(s)s s', m=seconds // 60, s=seconds % 60) if seconds >= 60 \
                    else _('%s s', seconds)
            else:
                job.average_time_label = '—'

    # ------------------------------------------------------------------ schedule

    def _when_label(self, moment):
        """'Today 07:02', 'Yesterday 18:01' or 'Nov 7, 10:00', in the reader's timezone."""
        if not moment:
            return ''
        local = fields.Datetime.context_timestamp(self, moment)
        today = fields.Datetime.context_timestamp(self, fields.Datetime.now()).date()
        if local.date() == today:
            return _('Today %s', local.strftime('%H:%M'))
        if local.date() == today - timedelta(days=1):
            return _('Yesterday %s', local.strftime('%H:%M'))
        return format_datetime(self.env, moment, dt_format='MMM d, HH:mm')

    def _schedule_tz(self):
        """The schedule's hours are the owner's local hours (else the current user's, else UTC)."""
        name = self.owner_id.tz or self.env.user.tz or 'UTC'
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    def _next_after(self, moment):
        """The next time this job should run after `moment` (naive UTC, as stored). The hour and day are read in
        the owner's timezone, so "Monday 07:00" is 07:00 where the owner is."""
        self.ensure_one()
        tz = self._schedule_tz()
        local = pytz.utc.localize(moment).astimezone(tz).replace(tzinfo=None)
        return tz.localize(self._next_after_local(local)).astimezone(pytz.utc).replace(tzinfo=None)

    def _next_after_local(self, moment):
        hour = min(max(self.hour or 0, 0), 23)
        if self.frequency == 'hourly':
            return (moment + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        today = datetime.combine(moment.date(), time(hour))
        if self.frequency == 'daily':
            return today if today > moment else today + timedelta(days=1)
        if self.frequency == 'weekly':
            ahead = (int(self.weekday or 0) - moment.weekday()) % 7
            candidate = today + timedelta(days=ahead)
            return candidate if candidate > moment else candidate + timedelta(days=7)
        day = min(max(self.month_day or 1, 1), 28)
        candidate = datetime.combine(moment.date().replace(day=day), time(hour))
        return candidate if candidate > moment else candidate + relativedelta(months=1)

    # ------------------------------------------------------------------ buttons

    def action_switch_on_dialog(self):
        self.ensure_one()
        if not self.owner_id:
            self.owner_id = self.env.user  # the default the dialog shows; the job stays off until Switch on
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'views': [(self.env.ref('marketing_intel_jobs.job_switch_on_form').id, 'form')], 'target': 'new',
                'name': _('Switch on: %s', self.name), }

    def action_switch_on(self):
        for job in self:
            if not job.owner_id:
                job.owner_id = self.env.user
            job.write({'state': 'on', 'next_run': job._next_after(fields.Datetime.now())})
        if len(self) == 1:
            # Opens the job inside Assistant jobs, so the breadcrumb reads "Assistant jobs › <job>" (board 11.3).
            action = self.env['ir.actions.act_window']._for_xml_id('marketing_intel_jobs.action_jobs')
            action.update({'res_id': self.id, 'view_mode': 'form', 'views': [(False, 'form')], 'target': 'main'})
            return action
        return True

    def action_pause(self):
        self.write({'state': 'paused'})

    def action_resume(self):
        for job in self:
            job.write({'state': 'on', 'next_run': job._next_after(fields.Datetime.now())})

    def action_run_now(self):
        for job in self:
            if job.state == 'off':
                raise UserError(_('Switch the job on first.'))
            job.sudo()._start_run()
        return True

    def action_open_result(self):
        """What the last run gave (its drafts, notes' records or to-dos)."""
        self.ensure_one()
        run = self.run_ids.filtered(lambda r: r.state == 'done' and r.output_refs).sorted('id', reverse=True)[:1]
        return run.action_open_outputs() if run else False

    def action_runs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Runs of %s', self.name), 'res_model': 'mi.job.run',
                'view_mode': 'list,form', 'domain': [('job_id', '=', self.id)]}

    # ------------------------------------------------------------------ running

    @api.model
    def _cron_run_due(self):
        """Start the runs that are due (each job once, then its next time)."""
        now = fields.Datetime.now()
        for job in self.sudo().search([('state', '=', 'on'), ('next_run', '<=', now)]):
            job.next_run = job._next_after(now)
            job._start_run()

    def _job_agent(self):
        """The marketing agent the job asks: the brand's, else the marketing department's, if active."""
        self.ensure_one()
        Agent = self.env['ai.agent'].sudo()
        if self.brand_id.ai_agent_id and self.brand_id.ai_agent_id.state == 'active':
            return self.brand_id.ai_agent_id
        domain = self.env['mi.panel'].sudo()._mi_assistant_agent_domain()
        return Agent.search([('state', '=', 'active')] + list(domain), limit=1)

    def _ai_questions_today(self):
        start = datetime.combine(fields.Date.today(), time.min)
        runs = self.env['mi.job.run'].sudo().search([('job_id', '=', self.id), ('started_at', '>=', start)])
        return sum(runs.mapped('ai_questions'))

    def _brands(self):
        self.ensure_one()
        return self.brand_id or self.env['mi.brand'].sudo().search([('company_id', '=', self.company_id.id)])

    def _start_run(self):
        """One run: the job's own method prepares it, then either asks the assistant or finishes at once."""
        self.ensure_one()
        run = self.env['mi.job.run'].sudo().create({'job_id': self.id, 'started_at': fields.Datetime.now()})
        try:
            handler = getattr(self, '_run_%s' % self.kind)
            outcome = handler(run)
        except UserError as error:
            run._fail(str(error.args[0] if error.args else error))
            return run
        if outcome and outcome.get('prompt'):
            if self._ai_questions_today() >= (self.ai_daily_limit or 0):
                run._fail(_("Today's AI limit of this job (%s questions) is reached.", self.ai_daily_limit))
                return run
            agent = self._job_agent()
            if not agent:
                run._fail(_('No marketing assistant is active. An AI Agent manager activates the marketing '
                            "department's agent."))
                return run
            try:
                ai_run = self.env['ai.agent.run'].sudo()._ask(agent, outcome['prompt'], caller='marketing',
                                                              as_assistant=True, origin=run)
            except UserError as error:
                run._fail(str(error.args[0] if error.args else error))
                return run
            run.write({'state': 'waiting', 'ai_run_id': ai_run.id, 'ai_questions': 1,
                       'context_json': outcome.get('context') or {}})
        elif outcome is not None:
            run._done(outcome.get('result', ''), outcome.get('outputs', []), outcome.get('note', ''))
        return run

    def _owner_todo(self, records, summary, note):
        """One open to-do for the owner on the job, kept up to date while it is open (not one per run)."""
        self.ensure_one()
        owner = self.owner_id or self.env.user
        todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        lines = ''.join('<li>%s</li>' % (record.display_name or '') for record in records[:20])
        body = '<p>%s</p>%s' % (note or summary, '<ul>%s</ul>' % lines if lines else '')
        open_todo = self.activity_ids.filtered(lambda a: a.user_id == owner and a.summary == self.name)[:1]
        if open_todo:
            open_todo.write({'note': body, 'date_deadline': fields.Date.context_today(self)})
            return open_todo
        return self.activity_schedule(activity_type_id=todo_type.id if todo_type else False, summary=self.name,
                                      note=body, user_id=owner.id, date_deadline=fields.Date.context_today(self))


class JobRun(models.Model):
    _name = 'mi.job.run'
    _description = 'Assistant job run'
    _order = 'id desc'

    job_id = fields.Many2one('mi.job', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    owner_id = fields.Many2one(related='job_id.owner_id', store=True, string='Owner')
    state = fields.Selection([('running', 'Running'), ('waiting', 'Waiting for the assistant'), ('done', 'Done'),
                              ('failed', 'Failed')], default='running', required=True, readonly=True)
    state_label = fields.Char(compute='_compute_state_label')
    started_at = fields.Datetime(readonly=True, string='When')
    finished_at = fields.Datetime(readonly=True)
    result = fields.Char(readonly=True, string='Gave')
    error = fields.Text(readonly=True, string='Reason')
    output_count = fields.Integer(readonly=True)
    ai_run_id = fields.Many2one('ai.agent.run', readonly=True, string='AI request', ondelete='set null')
    ai_questions = fields.Integer(readonly=True)
    activity_id = fields.Many2one('mail.activity', readonly=True, ondelete='set null', string="Owner's to-do")
    context_json = fields.Json(readonly=True)
    output_refs = fields.Json(readonly=True, help='What the run gave, as ["model,id", ...].')
    duration_label = fields.Char(compute='_compute_state_label', string='Time')

    @api.depends('state', 'started_at', 'finished_at')
    def _compute_state_label(self):
        labels = dict(self._fields['state']._description_selection(self.env))
        for run in self:
            run.state_label = labels.get(run.state, '')
            if run.started_at and run.finished_at:
                seconds = int((run.finished_at - run.started_at).total_seconds())
                run.duration_label = _('%(m)s min %(s)s s', m=seconds // 60, s=seconds % 60) if seconds >= 60 \
                    else _('%s s', seconds)
            else:
                run.duration_label = ''

    def _fail(self, reason):
        self.ensure_one()
        self.write({'state': 'failed', 'error': reason, 'finished_at': fields.Datetime.now()})
        job = self.job_id
        job.invalidate_recordset(['health'])
        if job.health == 'failing':
            owner = job.owner_id or self.env.user
            todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            summary = _('%s is failing', job.name)
            if not job.activity_ids.filtered(lambda a: a.summary == summary):
                job.activity_schedule(activity_type_id=todo_type.id if todo_type else False, summary=summary,
                                      note=_('The last two runs failed: %s', reason), user_id=owner.id,
                                      date_deadline=fields.Date.context_today(self))

    def action_open_outputs(self):
        self.ensure_one()
        refs = [ref.split(',') for ref in (self.output_refs or [])]
        models_ = {model for model, _id in refs}
        if not refs or len(models_) != 1:
            return False
        model = models_.pop()
        ids = [int(res_id) for _model, res_id in refs]
        if len(ids) == 1:
            return {'type': 'ir.actions.act_window', 'res_model': model, 'res_id': ids[0], 'view_mode': 'form',
                    'views': [(False, 'form')], 'target': 'current'}
        return {'type': 'ir.actions.act_window', 'name': self.job_id.name, 'res_model': model,
                'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')],
                'domain': [('id', 'in', ids)], 'target': 'current'}

    def _done(self, result, outputs, note=''):
        self.ensure_one()
        values = {'state': 'done', 'result': result, 'finished_at': fields.Datetime.now(),
                  'output_count': len(outputs), 'output_refs': ['%s,%s' % (r._name, r.id) for r in outputs]}
        if outputs:
            values['activity_id'] = self.job_id._owner_todo(outputs, result, note).id
        self.write(values)

    def _ai_agent_finished(self, ai_run):
        """The assistant answered (or could not): the job's own method turns the answer into its results."""
        self.ensure_one()
        run = self.sudo()  # runs belong to the system; the job's methods check what they touch
        if run.state != 'waiting' or ai_run.id != run.ai_run_id.id:
            return
        if ai_run.state != 'completed' or not (ai_run.answer or '').strip():
            run._fail(ai_run.error_message or _('The assistant ended without an answer.'))
            return
        job = run.job_id
        try:
            outcome = getattr(job, '_answer_%s' % job.kind)(run, ai_run.answer.strip())
        except UserError as error:
            run._fail(str(error.args[0] if error.args else error))
            return
        run._done(outcome.get('result', ''), outcome.get('outputs', []), outcome.get('note', ''))
