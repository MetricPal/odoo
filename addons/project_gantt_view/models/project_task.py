from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTask(models.Model):
    _inherit = 'project.task'

    planned_date_start = fields.Datetime(string='Planned start', copy=False, index=True,
                                         help='When work on the task starts; the Gantt bar runs from here to the deadline.')

    @api.constrains('planned_date_start', 'date_deadline')
    def _check_planned_dates(self):
        for task in self:
            if task.planned_date_start and task.date_deadline and task.date_deadline < task.planned_date_start:
                raise ValidationError(_('The deadline of “%s” is before its planned start.', task.name))
