import base64
from unittest.mock import patch
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, TransactionCase, tagged
from odoo.addons.omni_channel.tests.test_users import new_test_user
from ..models.template import FORMATS

@tagged('post_install', '-at_install')
class TestTemplates(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.operator = new_test_user(env, login='template_operator', groups='omni_channel.group_omni_user')
        cls.outsider = new_test_user(env, login='template_outsider', groups='omni_channel.group_omni_manager')
        cls.portal = new_test_user(env, login='template_portal', groups='base.group_portal')
        cls.team = env['omni.purpose'].create({'name':'Template QA', 'code':'template_qa', 'user_ids':[fields.Command.link(cls.operator.id)]})
        cls.contact = env['res.partner'].create({'name':'Aisha <script>alert(1)</script>', 'company_id':env.company.id})
        cls.templates = env['omni.template'].with_user(cls.operator)
        cls.telegram = env.ref('omni_channel.channel_type_telegram')
        if not env['omni.channel.type'].search([('code','=','teams')]):
            env['omni.channel.type'].create({'name':'Microsoft Teams','code':'teams','category':'messaging'})

    def make(self, **values):
        return self.templates.create({'name':'Welcome', 'purpose_id':self.team.id, 'channel_type_id':self.telegram.id, **values})

    def test_shared_feature_has_no_app_entry(self):
        self.assertFalse(self.env.ref('base.module_omni_template').application)
        menus = ['menu_templates_app', 'menu_workspace_channels', 'menu_workspace_inbox', 'menu_workspace_templates', 'menu_templates']
        hidden = {self.env.ref('omni_template.' + name).id for name in menus}
        self.assertTrue(hidden.isdisjoint(self.env['ir.ui.menu']._visible_menu_ids()))
        for name in menus: self.assertFalse(self.env.ref('omni_template.' + name).active)
        self.assertTrue(self.env.ref('omni_template.action_templates').exists())

    def test_all_channel_formats_native_form(self):
        for code, choices in FORMATS.items():
            channel = self.env['omni.channel.type'].search([('code','=',code)], limit=1)
            for fmt, label in choices:
                with self.subTest(channel=code, format=fmt):
                    with Form(self.templates, view='omni_template.template_form') as form:
                        form.name = code + ' ' + label
                        form.channel_type_id = channel
                        form.content_type = fmt
                        if fmt != 'story': form.body = 'Hi {{ object.name }} from {{ company.name }}'
                        form.purpose_id = self.team
                    template = form.record
                    self.assertEqual(template.content_type, fmt)
                    self.assertEqual(template.render_content(self.contact.id)['body'], '' if fmt == 'story' else 'Hi ' + self.contact.name + ' from ' + self.env.company.name)

    def test_preview_is_escaped_and_no_execution(self):
        with patch('requests.Session.request', side_effect=AssertionError('No external I/O')), patch.object(type(self.env['ir.mail_server']), 'send_email', side_effect=AssertionError('No email')):
            template = self.make(resource_ref=f'res.partner,{self.contact.id}', body='{{ object.name }} {{ company.name }}')
            self.assertIn('&lt;script&gt;', str(template.preview_html))
            self.assertNotIn('<script>', str(template.preview_html))
            self.assertIn(self.env.company.name, str(template.preview_html))
            self.assertEqual(self.env['omni.command'].search_count([]), 0)
            copied = template.copy({'name':'Copy'})
            self.assertFalse(copied.resource_ref)
            self.assertEqual(copied.body, template.body)

    def test_access_and_company(self):
        template = self.make()
        # Template authoring never grants technical-model metadata access.
        with self.assertRaises(AccessError): self.env.ref('base.model_res_partner').with_user(self.operator).read(['model'])
        for user in (self.outsider, self.portal):
            with self.assertRaises(AccessError): template.with_user(user).read(['body'])
            with self.assertRaises(AccessError): template.with_user(user).render_content(self.contact.id)
        other = self.env['res.company'].create({'name':'Other Company'})
        other_contact = self.env['res.partner'].create({'name':'Hidden', 'company_id':other.id})
        with self.assertRaises(AccessError): template.render_content(other_contact.id)
        # Even granting both companies does not allow rendering another company's data.
        self.operator.company_ids = [fields.Command.link(other.id)]
        with self.assertRaises(AccessError): template.with_context(allowed_company_ids=[self.env.company.id,other.id]).render_content(other_contact.id)
        with self.assertRaises(AccessError): self.templates.with_context(allowed_company_ids=[self.env.company.id]).create({'name':'Forbidden company','purpose_id':self.team.id,'channel_type_id':self.telegram.id,'company_id':other.id})
        with self.assertRaises(AccessError): self.templates.with_user(self.outsider).create({'name':'Forbidden','purpose_id':self.team.id,'channel_type_id':self.telegram.id})

    def test_reject_code_private_models_and_stale_fields(self):
        for body in ('{{ object.sudo().name }}', '{{ env["ir.config_parameter"] }}', '{{ object.__class__ }}', '{{ object.user_id.password }}', '{{ object.image_1920 }}', '{{ company.partner_id.name }}'):
            with self.subTest(body=body), self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.make(body=body)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.make(model_name='res.users')
        for link in ('javascript:alert(1)', 'https://[', 'https:missing-host', 'https://user:password@example.com'):
            with self.subTest(link=link), self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.make(button_label='Bad', button_url=link)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.make(content_type='reel')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.make(header='Unsupported')
        template = self.make(body='{{ object.email ||| no email }}')
        self.assertEqual(template.render_content(self.contact.id)['body'], 'no email')

    def test_optional_content_can_be_removed(self):
        template = self.make(button_label='Open', button_url='https://example.com')
        self.assertTrue(template.use_button)
        template.write({'use_button':False})
        self.assertFalse(template.button_label)
        self.assertFalse(template.button_url)
        draft = self.templates.new({'name':'Preview','company_id':self.env.company.id,'purpose_id':self.team.id,'channel_type_id':self.telegram.id,'model_name':'res.partner','content_type':'message','button_label':'Bad','button_url':'https://['})
        self.assertFalse(draft.preview_html)
        self.assertIn('HTTPS', draft.preview_note)

    def test_ordered_media_access_and_format_changes(self):
        channel = self.env.ref('omni_channel.channel_type_instagram')
        template = self.make(channel_type_id=channel.id, content_type='carousel', media_ids=[
            fields.Command.create({'sequence':20,'name':'Second.jpg','kind':'photo','content':base64.b64encode(b'fixture').decode()}),
            fields.Command.create({'sequence':10,'name':'First.jpg','kind':'photo','content':base64.b64encode(b'fixture').decode()}),
        ])
        self.assertEqual([item['name'] for item in template.render_content(self.contact.id)['media']], ['First.jpg','Second.jpg'])
        for user in (self.outsider, self.portal):
            with self.assertRaises(AccessError): template.media_ids.with_user(user).read(['content'])
        with self.assertRaises(ValidationError), self.env.cr.savepoint(): template.write({'content_type':'post'})
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.env['omni.template.media'].with_user(self.outsider).create({'template_id':template.id,'name':'bad','content':base64.b64encode(b'x').decode()})
        copied = template.copy({'name':'Carousel copy'})
        self.assertEqual(copied.media_ids.sorted('sequence').mapped('name'),template.media_ids.sorted('sequence').mapped('name'))
        self.assertNotEqual(copied.media_ids.ids,template.media_ids.ids)
