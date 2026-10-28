from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestFlowRecipe(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, default_phase='planning', default_proposal_state='approved'))
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.marketer = new_test_user(cls.env, 'mir_marketer', groups='marketing_intel.group_mi_user')
        cls.manager = new_test_user(cls.env, 'mir_manager', groups='marketing_intel.group_mi_manager')
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        cls.env.invalidate_all()
        cls.brand_a = cls.env['mi.brand'].sudo().create({'name': 'Brand A'})
        cls.recipe = cls.env.ref('marketing_intel_flow.recipe_comment_whatsapp')

    def test_shipped_recipe_has_step_lines(self):
        self.assertEqual(self.recipe.step_ids.mapped('action'), ['message', 'todo'])
        self.assertIn('INFO', self.recipe.summary)

    def test_use_asks_for_the_brand_when_several(self):
        recipe = self.recipe.with_user(self.marketer)
        # one brand: straight to the draft workflow
        flow = self.env['mi.flow'].browse(recipe.action_use()['res_id'])
        self.assertEqual((flow.brand_id, flow.recipe_id, flow.state), (self.brand_a, self.recipe, 'draft'))
        self.assertEqual(flow.step_ids.mapped('action'), ['message', 'todo'])
        # several brands: a dialog asks which one
        brand_b = self.env['mi.brand'].sudo().create({'name': 'Brand B'})
        action = recipe.action_use()
        self.assertEqual(action['res_model'], 'mi.flow.recipe.use')
        wizard = self.env['mi.flow.recipe.use'].with_user(self.marketer).with_context(action['context']).create(
            {'brand_id': brand_b.id})
        flow_b = self.env['mi.flow'].browse(wizard.action_create()['res_id'])
        self.assertEqual(flow_b.brand_id, brand_b)
        # the brand in view (e.g. from the control panel) is used without asking
        flow_c = self.env['mi.flow'].browse(recipe.with_context(default_brand_id=brand_b.id).action_use()['res_id'])
        self.assertEqual(flow_c.brand_id, brand_b)
        self.recipe.invalidate_recordset(['use_count'])
        self.assertEqual(self.recipe.use_count, 3)

    def test_managers_save_and_edit_recipes(self):
        flow = self.env['mi.flow'].sudo().create({
            'name': 'Webinar sign-up → thank you', 'brand_id': self.brand_a.id, 'trigger': 'event_registration',
            'step_ids': [Command.create({'action': 'message', 'message': 'Thanks {first_name}!'}),
                         Command.create({'action': 'todo', 'note': 'Call them'})]})
        with self.assertRaises(AccessError):
            flow.with_user(self.marketer).action_save_recipe()
        flow = flow.with_user(self.manager).sudo(False)
        recipe = self.env['mi.flow.recipe'].browse(flow.action_save_recipe()['res_id'])
        self.assertEqual((recipe.name, recipe.trigger, recipe.source_flow_id), (flow.name, 'event_registration', flow))
        self.assertEqual(recipe.step_ids.mapped('message')[0], 'Thanks {first_name}!')
        # saving again updates the same recipe
        flow.sudo().step_ids.filtered(lambda s: s.action == 'todo').unlink()
        self.assertEqual(self.env['mi.flow.recipe'].browse(flow.action_save_recipe()['res_id']), recipe)
        self.assertEqual(recipe.step_ids.mapped('action'), ['message'])
        # a different workflow may not take an existing recipe name
        other = flow.sudo().copy({'name': flow.name}).with_user(self.manager).sudo(False)
        with self.assertRaises(UserError):
            other.action_save_recipe()
        # managers edit and archive recipes; marketers only read them
        recipe.with_user(self.manager).write({'keyword': 'YES'})
        with self.assertRaises(AccessError):
            recipe.with_user(self.marketer).write({'keyword': 'NO'})
        recipe.with_user(self.manager).action_archive()
        self.assertFalse(self.env['mi.flow.recipe'].with_user(self.marketer).search([('id', '=', recipe.id)]))

    def test_new_workflow_opens_the_recipes(self):
        action = self.env['mi.flow'].with_user(self.marketer).with_context(default_brand_id=self.brand_a.id) \
            .action_new_from_recipe()
        self.assertEqual(action['res_model'], 'mi.flow.recipe')
        self.assertEqual(action['context'], {'default_brand_id': self.brand_a.id})
        blank = self.env['mi.flow.recipe'].with_user(self.marketer).action_blank()
        self.assertEqual((blank['res_model'], blank['view_mode']), ('mi.flow', 'form'))
