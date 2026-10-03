from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError
from odoo.modules.module import Manifest
from odoo.tests import TransactionCase, new_test_user
from odoo.tools import file_open


class TestWorkDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Other Dashboard Company'})
        cls.internal_user = new_test_user(
            cls.env,
            login='ai_home_user',
            groups='base.group_user',
            company_id=cls.company.id,
        )
        cls.portal_user = new_test_user(
            cls.env,
            login='ai_home_portal',
            groups='base.group_portal',
            company_id=cls.company.id,
        )
        cls.item_model = cls.env['ai.home.item']
        cls.attention_item = cls.item_model.create({
            'name': 'Approval needed',
            'section': 'attention',
            'company_id': cls.company.id,
        })
        cls.automation_item = cls.item_model.create({
            'name': 'Admin automation',
            'section': 'automation',
            'company_id': cls.company.id,
            'group_ids': [fields.Command.link(cls.env.ref('base.group_system').id)],
        })
        cls.recent_item = cls.item_model.create({
            'name': 'Recent update',
            'section': 'recent',
            'company_id': cls.company.id,
        })
        cls.other_company_item = cls.item_model.create({
            'name': 'Other company approval',
            'section': 'attention',
            'company_id': cls.other_company.id,
        })

    def test_dashboard_items_apply_groups_and_company_rules(self):
        user_items = self.item_model.with_user(self.internal_user).get_dashboard_items()
        user_item_ids = {item['id'] for item in user_items}

        self.assertIn(self.attention_item.id, user_item_ids)
        self.assertIn(self.recent_item.id, user_item_ids)
        self.assertNotIn(self.automation_item.id, user_item_ids)
        self.assertNotIn(self.other_company_item.id, user_item_ids)
        self.assertNotIn(
            self.automation_item,
            self.item_model.with_user(self.internal_user).search([]),
        )

        admin_items = self.item_model.with_user(
            self.env.ref('base.user_admin')
        ).get_dashboard_items()
        self.assertIn(self.automation_item.id, {item['id'] for item in admin_items})

    def test_home_is_the_first_internal_root_app(self):
        menu = self.env.ref('ai_home.menu_ai_home_root')
        action = self.env.ref('ai_home.action_ai_home')
        module = self.env['ir.module.module']._get('ai_home')
        manifest = Manifest.for_addon('ai_home')

        self.assertEqual(module.with_context(lang=None).shortdesc, 'AI Home')
        self.assertEqual(
            manifest['icon'],
            '/ai_home/static/description/icon.svg',
        )
        with file_open(manifest['icon'].removeprefix('/'), mode='rb') as icon_file:
            icon = etree.parse(icon_file).getroot()
        self.assertEqual(icon.tag, '{http://www.w3.org/2000/svg}svg')
        self.assertEqual(icon.get('width'), '50')
        self.assertEqual(icon.get('height'), '50')
        self.assertEqual(icon.get('viewBox'), '0 0 50 50')
        self.assertFalse(menu.parent_id)
        self.assertEqual(menu.sequence, 1)
        self.assertIn(self.env.ref('base.group_user'), menu.group_ids)
        self.assertEqual(menu.action, action)
        self.assertEqual(menu.name, 'Home')
        self.assertEqual(
            menu.web_icon,
            'ai_home,static/description/icon.svg',
        )
        self.assertTrue(menu.web_icon_data)
        self.assertEqual(action.name, 'Home')
        self.assertEqual(action.path, 'home')
        self.assertEqual(action.tag, 'ai_home.dashboard')

    def test_website_home_menu_navigates_directly_to_home(self):
        layout = self.env.ref('website.layout')._get_combined_arch()
        home_buttons = layout.xpath(
            ".//a[contains(concat(' ', normalize-space(@class), ' '), "
            "' o_frontend_to_backend_apps_btn ')]"
        )

        self.assertEqual(len(home_buttons), 1)
        home_button = home_buttons[0]
        self.assertEqual(home_button.get('href'), '/odoo/home')
        self.assertEqual(home_button.get('title'), 'Home Menu')
        self.assertEqual(home_button.get('aria-label'), 'Go to Home')
        self.assertIsNone(home_button.get('data-bs-toggle'))
        self.assertIsNone(home_button.get('data-bs-display'))
        self.assertFalse(
            layout.xpath(
                ".//div[contains(concat(' ', normalize-space(@class), ' '), "
                "' o_frontend_to_backend_apps_menu ')]"
            )
        )

    def test_mark_recent_seen_is_user_specific(self):
        user_model = self.item_model.with_user(self.internal_user)
        self.assertIn(
            self.recent_item.id,
            {item['id'] for item in user_model.get_dashboard_items()},
        )

        self.assertTrue(user_model.mark_recent_seen(self.recent_item.id))

        self.assertNotIn(
            self.recent_item.id,
            {item['id'] for item in user_model.get_dashboard_items()},
        )
        self.assertIn(self.internal_user, self.recent_item.seen_user_ids)
        self.assertNotIn(self.env.user, self.recent_item.seen_user_ids)

    def test_cannot_mark_inaccessible_recent_item_seen(self):
        inaccessible_recent = self.item_model.create({
            'name': 'Other company update',
            'section': 'recent',
            'company_id': self.other_company.id,
        })

        result = self.item_model.with_user(self.internal_user).mark_recent_seen(
            inaccessible_recent.id
        )

        self.assertFalse(result)
        self.assertFalse(inaccessible_recent.seen_user_ids)

    def test_internal_users_have_read_only_model_access(self):
        user_model = self.item_model.with_user(self.internal_user)

        self.assertTrue(user_model.has_access('read'))
        self.assertFalse(user_model.has_access('write'))
        self.assertFalse(user_model.has_access('create'))
        self.assertFalse(user_model.has_access('unlink'))
        with self.assertRaises(AccessError):
            self.recent_item.with_user(self.internal_user).read(['seen_user_ids'])

    def test_portal_users_cannot_read_dashboard_items(self):
        with self.assertRaises(AccessError):
            self.item_model.with_user(self.portal_user).get_dashboard_items()

    def test_security_records_use_odoo20_access_model(self):
        permission = self.env.ref('ai_home.access_ai_home_item_user')
        restriction = self.env.ref('ai_home.ai_home_item_company_rule')
        self.assertEqual(permission._name, 'ir.access')
        self.assertEqual(permission.model_id.model, 'ai.home.item')
        self.assertEqual(permission.operation, 'r')
        self.assertEqual(permission.kind, 'permission')
        self.assertEqual(restriction._name, 'ir.access')
        self.assertEqual(restriction.model_id, permission.model_id)
        self.assertEqual(restriction.operation, 'crud')
        self.assertEqual(restriction.kind, 'restriction')
