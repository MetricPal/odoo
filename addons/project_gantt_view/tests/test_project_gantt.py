from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProjectGantt(TransactionCase):
    def test_task_gantt_view_and_dates(self):
        views = self.env['project.task'].get_views([(False, 'gantt')])
        self.assertIn('planned_date_start', views['views']['gantt']['arch'])
        self.assertIn('gantt', self.env.ref('project.action_view_all_task').view_mode)
        project = self.env['project.project'].create({'name': 'Gantt project'})
        task = self.env['project.task'].create({'name': 'Shoot video', 'project_id': project.id,
                                                'planned_date_start': datetime(2026, 11, 2, 9),
                                                'date_deadline': datetime(2026, 11, 13, 17)})
        self.assertTrue(task.planned_date_start)
        with self.assertRaises(ValidationError):
            task.date_deadline = datetime(2026, 11, 1)
