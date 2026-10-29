"""Campaign tasks in Project: one project per campaign, created when the first task is planned.

Templates and copies carry their task list. Each copied task keeps its timing relative to the campaign start
("3 days before start"), so a repeat or a campaign started from a template gets the same plan of work.
"""

from datetime import datetime, time, timedelta

from odoo import _, api, fields, models

from odoo.addons.marketing_intel_plan.models.pillars import PILLARS


class Project(models.Model):
    _inherit = 'project.project'

    mi_plan_id = fields.Many2one('mi.plan', string='Marketing campaign', index='btree_not_null', ondelete='set null',
                                 copy=False, readonly=True)


class Task(models.Model):
    _inherit = 'project.task'

    mi_plan_id = fields.Many2one(related='project_id.mi_plan_id', store=True, string='Marketing campaign',
                                 index='btree_not_null')
    mi_pillar = fields.Selection(PILLARS, string='Pillar', index=True,
                                 help='The campaign pillar this task works for (Awareness, Consideration, Conversion).')
    mi_days_before = fields.Integer(string='Due (days before start)', help='Used when the task is copied to a new '
                                    'campaign: the deadline is this many days before the campaign start (negative: '
                                    'after the start).')


class Plan(models.Model):
    _inherit = 'mi.plan'

    project_id = fields.Many2one('project.project', string='Tasks project', readonly=True, copy=False,
                                 index='btree_not_null')
    work_source_id = fields.Many2one('mi.plan', string='Tasks copied from', readonly=True, copy=False)
    task_count = fields.Integer(compute='_compute_tasks', string='Tasks')
    task_open_count = fields.Integer(compute='_compute_tasks', string='Open tasks')
    task_late_count = fields.Integer(compute='_compute_tasks', string='Late tasks')
    task_label = fields.Char(compute='_compute_tasks', string='Task progress')
    task_link = fields.Char(compute='_compute_tasks', string='Tasks ')

    def _compute_tasks(self):
        now = fields.Datetime.now()
        for plan in self:
            tasks = self.env['project.task'].search([('project_id', '=', plan.project_id.id)]) \
                if plan.project_id else self.env['project.task']
            open_tasks = tasks.filtered(lambda t: not t.is_closed)
            plan.task_count = len(tasks)
            plan.task_open_count = len(open_tasks)
            plan.task_late_count = len(open_tasks.filtered(lambda t: t.date_deadline and t.date_deadline < now))
            done = plan.task_count - plan.task_open_count
            plan.task_label = _('%(done)s of %(total)s done', done=done, total=plan.task_count) if tasks else False
            plan.task_link = _('Tasks: %(open)s open of %(total)s', open=plan.task_open_count, total=plan.task_count) \
                if tasks else _('Tasks: plan them')

    def _ensure_project(self):
        self.ensure_one()
        if not self.project_id:
            stages = self.env.ref('marketing_intel_work.stage_todo') | self.env.ref('marketing_intel_work.stage_doing') \
                | self.env.ref('marketing_intel_work.stage_done')
            project = self.env['project.project'].sudo().create({
                'name': _('Campaign: %s', self.name), 'company_id': self.company_id.id, 'user_id': self.user_id.id,
                'mi_plan_id': self.id, 'privacy_visibility': 'employees', 'type_ids': [(6, 0, stages.ids)]})
            self.sudo().project_id = project
        return self.project_id

    def action_open_tasks(self):
        self.ensure_one()
        self.check_access('read')
        project = self._ensure_project()
        gantt = self.env.ref('marketing_intel_work.task_gantt_campaign')
        return {
            'type': 'ir.actions.act_window', 'name': _('Tasks · %s', self.name), 'res_model': 'project.task',
            'view_mode': 'gantt,kanban,list,calendar,activity,form',
            'views': [(gantt.id, 'gantt'), (False, 'kanban'), (False, 'list'), (False, 'calendar'), (False, 'activity'),
                      (False, 'form')],
            'domain': [('project_id', '=', project.id)],
            'context': {'default_project_id': project.id, 'default_user_ids': [(6, 0, [self.env.uid])],
                        'mi_template': self.is_template},
        }

    # -- carrying tasks into copies ---------------------------------------------------------------------------------
    def _copy_values(self, **overrides):
        values = super()._copy_values(**overrides)
        values.setdefault('work_source_id', self.id)
        return values

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        for plan in plans.filtered('work_source_id'):
            plan._copy_tasks_from(plan.work_source_id)
        return plans

    def write(self, vals):
        result = super().write(vals)
        if vals.get('work_source_id'):  # a template saved again: its task list is replaced
            for plan in self:
                if plan.project_id:
                    plan.project_id.sudo().task_ids.filtered(lambda t: not t.parent_id).unlink()
                plan._copy_tasks_from(plan.work_source_id)
        if 'name' in vals:
            for plan in self.filtered('project_id'):
                plan.project_id.sudo().name = _('Campaign: %s', plan.name)
        return result

    def _task_offset(self, task):
        """Days before this campaign's start the task is due; None when it has no due date."""
        if self.is_template:
            return task.mi_days_before
        if task.date_deadline:
            return (self.date_start - task.date_deadline.date()).days
        return None

    def _copy_tasks_from(self, source):
        self.ensure_one()
        tasks = source.project_id.sudo().task_ids.filtered(lambda t: not t.parent_id and t.state != '1_canceled') \
            if source.project_id else []
        if not tasks:
            return
        project = self._ensure_project().sudo()
        todo = self.env.ref('marketing_intel_work.stage_todo')
        for task in tasks:
            offset = source._task_offset(task)
            values = {'name': task.name, 'project_id': project.id, 'description': task.description,
                      'allocated_hours': task.allocated_hours, 'stage_id': todo.id,
                      'mi_days_before': offset or 0, 'user_ids': [(6, 0, task.user_ids.ids)],
                      'mi_pillar': task.mi_pillar}
            if offset is not None and not self.is_template:
                values['date_deadline'] = datetime.combine(self.date_start - timedelta(days=offset), time(12, 0))
            self.env['project.task'].sudo().create(values)

    def _review_blockers(self):
        """Hook: what keeps the campaign from going to review (in addition to the channel checks)."""
        return []

    def action_submit_review(self):
        problems = []
        for plan in self:
            blockers = plan._review_blockers()
            if blockers:
                problems.append('%s:\n%s' % (plan.name, '\n'.join('• %s' % b for b in blockers)))
        if problems:
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'type': 'warning', 'sticky': True, 'title': _('Not sent for review yet'),
                'message': '\n\n'.join(problems)}}
        return super().action_submit_review()

    def unlink(self):
        projects = self.project_id
        result = super().unlink()
        projects.sudo().write({'active': False})
        return result

    def action_cancel(self):
        result = super().action_cancel()
        self.project_id.sudo().task_ids.filtered(lambda t: not t.is_closed).write({'state': '1_canceled'})
        return result

    def _on_done(self):
        result = super()._on_done()
        for plan in self.filtered('project_id'):
            open_tasks = plan.project_id.sudo().task_ids.filtered(lambda t: not t.is_closed)
            if open_tasks:
                plan.message_post(body=_('Campaign done with %s open task(s).', len(open_tasks)))
        return result
