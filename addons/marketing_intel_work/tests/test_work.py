from datetime import date, datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

APP_GROUPS = ['mass_mailing.group_mass_mailing_user']


@tagged('post_install', '-at_install')
class TestWork(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        groups = ['marketing_intel.group_mi_user'] + [g for g in APP_GROUPS if cls.env.ref(g, raise_if_not_found=False)]
        cls.marketer = new_test_user(cls.env, 'miw_marketer', groups=','.join(groups))
        cls.reviewer = new_test_user(cls.env, 'miw_reviewer', groups=','.join(groups))
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        cls.env.invalidate_all()
        cls.brand = cls.env['mi.brand'].sudo().create({'name': 'metric.io'})
        cls.email = cls.env['mi.channel'].search([('code', '=', 'email')])

    def _plan(self, **values):
        start = values.pop('date_start', date.today() + timedelta(days=10))
        return self.env['mi.plan'].with_user(self.marketer).create(dict({
            'name': 'Open day', 'brand_id': self.brand.id, 'date_start': start, 'date_end': start + timedelta(days=14),
            'channel_ids': [Command.set(self.email.ids)]}, **values))

    def test_marketer_plans_tasks_and_they_follow_duplicates_and_templates(self):
        plan = self._plan()
        action = plan.action_open_tasks()
        project = plan.project_id
        self.assertTrue(project)
        self.assertEqual(action['domain'], [('project_id', '=', project.id)])
        Task = self.env['project.task'].with_user(self.marketer)
        Task.create({'name': 'Book the photographer', 'project_id': project.id, 'user_ids': [Command.set(self.marketer.ids)],
                     'date_deadline': datetime.combine(plan.date_start - timedelta(days=5), datetime.min.time())})
        Task.create({'name': 'Print flyers', 'project_id': project.id})
        plan.invalidate_recordset()
        self.assertEqual(plan.task_count, 2)
        self.assertEqual(plan.task_label, '0 of 2 done')
        self.assertEqual(project.task_ids.filtered(lambda t: t.name == 'Book the photographer').mi_plan_id, plan)

        copy = self.env['mi.plan'].browse(plan.with_user(self.marketer).action_duplicate()['res_id'])
        tasks = copy.project_id.task_ids
        self.assertEqual(sorted(tasks.mapped('name')), ['Book the photographer', 'Print flyers'])
        photographer = tasks.filtered(lambda t: t.name == 'Book the photographer')
        self.assertEqual(photographer.date_deadline.date(), copy.date_start - timedelta(days=5))
        self.assertFalse(tasks.filtered(lambda t: t.name == 'Print flyers').date_deadline)

        template = self.env['mi.plan'].browse(plan.with_user(self.marketer).action_save_template()['res_id'])
        self.assertEqual(template.project_id.task_ids.filtered(lambda t: t.name == 'Book the photographer').mi_days_before, 5)
        # saving again replaces the template's task list
        Task.create({'name': 'Order balloons', 'project_id': project.id})
        plan.with_user(self.marketer).action_save_template()
        self.assertEqual(len(template.project_id.task_ids), 3)
        started = self.env['mi.plan'].browse(template.with_user(self.marketer).action_use_template()['res_id'])
        self.assertEqual(len(started.project_id.task_ids), 3)

    def test_request_becomes_campaign_brief(self):
        Request = self.env['mi.request'].with_user(self.marketer)
        request = Request.create({'name': 'Promote the open day', 'brand_id': self.brand.id, 'goal': '40 bookings',
                                  'audience': 'Parents nearby', 'description': '<p>Saturday 10am, free coffee.</p>',
                                  'wanted_by': date.today() + timedelta(days=20),
                                  'channel_ids': [Command.set(self.email.ids)]})
        with self.assertRaises(UserError):
            request.action_decline()
        request.action_accept()
        self.assertEqual(request.state, 'accepted')
        self.assertEqual(request.user_id, self.marketer)
        plan = self.env['mi.plan'].browse(request.action_start_campaign()['res_id'])
        self.assertEqual(request.state, 'converted')
        self.assertEqual(plan.brand_id, self.brand)
        self.assertIn('40 bookings', plan.message)
        self.assertIn('free coffee', plan.message)
        self.assertEqual(plan.audience, 'Parents nearby')
        self.assertEqual(plan.date_end, request.wanted_by)
        self.assertEqual(plan.channel_ids, self.email)

    def test_proof_versions_compare_approve_and_block_review(self):
        plan = self._plan()
        item = plan.item_ids
        Proof = self.env['mi.proof'].with_user(self.marketer)
        proof = Proof.create({'name': 'Launch email', 'plan_id': plan.id, 'item_id': item.id,
                              'reviewer_id': self.reviewer.id, 'subject': 'Come to our open day',
                              'body': 'Join us on Saturday for coffee.'})
        proof.action_send()
        self.assertEqual(proof.state, 'review')
        self.assertFalse(proof.can_decide, 'the maker cannot approve their own proof')
        with self.assertRaises(UserError):
            proof.action_approve()
        # an open proof keeps the campaign out of review
        result = plan.with_user(self.marketer).action_submit_review()
        self.assertEqual(result['params']['title'], 'Not sent for review yet')
        self.assertIn('Launch email', result['params']['message'])
        self.assertEqual(plan.state, 'brief')

        as_reviewer = proof.with_user(self.reviewer)
        with self.assertRaises(UserError):
            as_reviewer.action_request_changes()  # feedback needed
        as_reviewer.feedback = 'Mention the free parking.'
        as_reviewer.action_request_changes()
        self.assertEqual(proof.state, 'changes')

        new = self.env['mi.proof'].browse(proof.action_new_version()['res_id'])
        self.assertEqual(proof.state, 'old')
        self.assertEqual((new.version, new.previous_id), (2, proof))
        new.body = 'Join us on Saturday for coffee and free parking.'
        self.assertIn('free parking', new.compare_html)
        self.assertIn('<ins', new.compare_html)
        new.action_send()
        new.with_user(self.reviewer).action_approve()
        self.assertEqual(new.state, 'approved')
        self.assertEqual(item.content_text, 'Join us on Saturday for coffee and free parking.')
        self.assertEqual(item.content_subject, 'Come to our open day')
        plan.invalidate_recordset()
        self.assertEqual(plan.proof_open_count, 0)
        self.assertFalse(plan._review_blockers())

    def test_workload_and_todos(self):
        plan = self._plan()
        plan.action_open_tasks()
        late = datetime.now() - timedelta(days=1)
        task = self.env['project.task'].with_user(self.marketer).create({
            'name': 'Write the brief', 'project_id': plan.project_id.id, 'allocated_hours': 3,
            'user_ids': [Command.set(self.marketer.ids)], 'date_deadline': late})
        proof = self.env['mi.proof'].with_user(self.marketer).create({
            'name': 'Poster', 'plan_id': plan.id, 'reviewer_id': self.reviewer.id, 'body': 'Open day!'})
        proof.action_send()
        self.env.flush_all()
        rows = self.env['mi.workload'].with_user(self.marketer).search([('plan_id', '=', plan.id)])
        mine = rows.filtered(lambda r: r.user_id == self.marketer)
        self.assertEqual(sorted(mine.mapped('kind')), ['campaign', 'task'])
        task_row = mine.filtered(lambda r: r.kind == 'task')
        self.assertTrue(task_row.late)
        self.assertEqual(task_row.hours, 3)
        self.assertEqual(rows.filtered(lambda r: r.kind == 'proof').user_id, self.reviewer)
        self.assertEqual(task_row.action_open()['res_id'], task.id)

        panel = self.env['mi.panel'].with_user(self.marketer)
        titles = [t['title'] for t in panel._todos(self.brand, plan)]
        self.assertIn('Task: Write the brief', titles)
        titles = [t['title'] for t in self.env['mi.panel'].with_user(self.reviewer)._todos(self.brand, plan)]
        self.assertIn('Review the proof Poster v1', titles)
