"""Post editor data: choices, limits, media rules per format, file details."""

import base64
import io

from PIL import Image

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.models.social import internal
from odoo.addons.omni_social.providers import registry


def jpeg(width=40, height=30):
    buf = io.BytesIO()
    Image.new('RGB', (width, height), (200, 120, 60)).save(buf, 'JPEG')
    return base64.b64encode(buf.getvalue()).decode()


@tagged('post_install', '-at_install')
class TestComposer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        installed = registry.installed(cls.env)
        if not {'linkedin', 'instagram'} <= set(installed):
            cls.skipTest(cls, 'Needs omni_linkedin and omni_instagram')
        cls.operator = new_test_user(cls.env, login='composer_operator', groups='omni_channel.group_omni_user')
        cls.team = cls.env['omni.purpose'].create({
            'name': 'Composer QA', 'code': 'composer_qa', 'user_ids': [fields.Command.set(cls.operator.ids)],
        })
        cls.accounts = {}
        for provider in ('instagram', 'linkedin', 'x', 'youtube', 'facebook'):
            if provider not in installed:
                continue
            account = cls.env['omni.social.connection'].create({
                'name': 'Composer %s' % provider, 'provider': provider, 'purpose_id': cls.team.id,
            })
            internal(account).write({'connected': True, 'profile_name': '@composer_' + provider})
            cls.accounts[provider] = account

    def _post(self, provider, **values):
        return self.env['omni.social.publication'].with_user(self.operator).create({
            'name': 'Composer post', 'connection_id': self.accounts[provider].id, 'body': 'Hello',
            'reason': 'QA', **values,
        })

    def test_choices_follow_the_account(self):
        ui = self._post('instagram').composer_ui
        self.assertTrue(ui['ready'])
        self.assertEqual(ui['platform']['label'], 'Instagram')
        self.assertEqual([o['value'] for o in ui['operations']], ['post', 'reply', 'message'])
        self.assertEqual([f['value'] for f in ui['formats']], ['standard', 'carousel', 'reel', 'story'])
        self.assertTrue(all(o['description'] for o in ui['operations'] + ui['formats']))
        self.assertIn('2–10', next(f for f in ui['formats'] if f['value'] == 'carousel')['description'])
        linkedin = self._post('linkedin')
        self.assertEqual([o['value'] for o in linkedin.composer_ui['operations']], ['post', 'reply'])
        self.assertEqual(linkedin.composer_operations, 2)
        self.assertEqual(linkedin.composer_formats, 2)

    def test_limits_and_placeholders(self):
        post = self._post('instagram')
        ui = post.composer_ui
        self.assertEqual(ui['text']['limit'], 2200)
        self.assertIn('Instagram', ui['text']['placeholder'])
        self.assertEqual(ui['account']['profile'], '@composer_instagram')
        self.assertEqual((ui['media']['min'], ui['media']['max']), (1, 1))
        self.assertIn('Exactly 1 file', ui['media']['rules'])
        post.format = 'story'
        self.assertTrue(post.composer_ui['text']['hidden'])
        self.assertEqual(post.composer_ui['media']['video_seconds'], [3, 60])
        post.write({'format': 'standard', 'operation': 'message'})
        self.assertEqual(post.composer_ui['text']['limit'], 1000)
        self.assertEqual(post.composer_ui['formats'], [])
        self.assertEqual(post.composer_ui['media']['max'], 0)

    def test_without_an_account_the_editor_waits(self):
        draft = self.env['omni.social.publication'].with_user(self.operator).new({'name': 'Empty'})
        self.assertFalse(draft.composer_ui['ready'])
        self.assertEqual([o['value'] for o in draft.composer_ui['operations']], ['post'])

    def test_title_hint_for_platforms_with_titles(self):
        if 'youtube' not in self.accounts:
            self.skipTest('Needs omni_youtube')
        ui = self._post('youtube').composer_ui
        self.assertEqual(ui['title']['limit'], 100)
        self.assertIn('YouTube', ui['title']['hint'])
        self.assertEqual(ui['media']['kinds'], ['video'])
        self.assertEqual(ui['media']['accept'], 'video/mp4')

    def test_reply_limits(self):
        if 'facebook' not in self.accounts:
            self.skipTest('Needs omni_facebook')
        self.assertEqual(self._post('facebook', operation='reply').composer_ui['text']['limit'], 8000)

    def test_media_rules_per_format_on_submit(self):
        post = self._post('instagram')
        with self.assertRaisesRegex(UserError, 'at least 1 photo or video'):
            post._check_capabilities([])
        with self.assertRaisesRegex(UserError, 'takes only photos'):
            post._check_capabilities([{'kind': 'video'}])
        post.format = 'carousel'
        with self.assertRaisesRegex(UserError, 'at least 2 files for a carousel'):
            post._check_capabilities([{'kind': 'image'}])
        post._check_capabilities([{'kind': 'image'}, {'kind': 'video'}])
        with self.assertRaisesRegex(UserError, 'up to 10 files'):
            post._check_capabilities([{'kind': 'image'}] * 11)
        post.format = 'reel'
        with self.assertRaisesRegex(UserError, 'takes only a video'):
            post._check_capabilities([{'kind': 'image'}])

    def test_platform_photo_size(self):
        if 'x' not in self.accounts:
            self.skipTest('Needs omni_x')
        post = self._post('x')
        self.assertEqual(post.composer_ui['media']['photo_bytes'], 5 * 1024 * 1024)
        media = self.env['omni.social.media'].with_user(self.operator).create(
            {'publication_id': post.id, 'name': 'big.jpg', 'kind': 'image', 'file': jpeg()})
        post._check_capabilities([{'kind': 'image'}])  # small photo passes
        # A photo above X's own 5 MB limit is refused even though Odoo takes 8 MB.
        raw = base64.b64decode(jpeg()) + b'\0' * (5 * 1024 * 1024)
        media.write({'file': base64.b64encode(raw).decode()})
        with self.assertRaisesRegex(UserError, 'up to 5 MB'):
            post._check_capabilities([{'kind': 'image'}])

    def test_media_details_are_read_from_the_file(self):
        post = self._post('instagram')
        media = self.env['omni.social.media'].with_user(self.operator).create(
            {'publication_id': post.id, 'name': 'p.jpg', 'kind': 'image', 'file': jpeg(64, 48)})
        self.assertEqual((media.width, media.height), (64, 48))
        self.assertGreater(media.file_size, 100)
        self.assertEqual(media.duration, 0)

    def test_labels_explain_the_fields(self):
        fields_ = self.env['omni.social.publication']._fields
        self.assertEqual(fields_['body'].string, 'Text')
        self.assertEqual(fields_['reason'].string, 'Note for the approver')
        self.assertIn('approver', fields_['reason'].help)


@tagged('post_install', '-at_install')
class TestComposerWidgets(HttpCase):
    def test_composer_widgets(self):
        module_hash = 0
        for char in '@omni_social/composer':
            module_hash = ((module_hash << 5) - module_hash + ord(char)) & 0xFFFFFFFF
        self.browser_js(
            f'/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&id={module_hash:08x}',
            '', login='admin', timeout=180,
            success_signal='[HOOT] Test suite succeeded',
        )


@tagged('post_install', '-at_install')
class TestTeamsAndChoices(TransactionCase):
    def test_social_media_team_is_the_default(self):
        team = self.env.ref('omni_channel.purpose_social_media')
        self.assertEqual(team.name, 'Social Media')
        self.assertEqual(self.env['omni.social.connection'].default_get(['purpose_id'])['purpose_id'], team.id)
        self.assertEqual(self.env['omni.social.campaign'].default_get(['purpose_id'])['purpose_id'], team.id)
        team.active = False
        self.assertFalse(self.env['omni.social.connection'].default_get(['purpose_id']).get('purpose_id'))

    def test_team_and_account_type_are_horizontal_radios(self):
        from lxml import etree
        views = [
            ('omni.social.connection', 'omni_social.connection_setup_form', 'purpose_id'),
            ('omni.social.connection', 'omni_social.connection_setup_form', 'account_kind'),
            ('omni.social.campaign', None, 'purpose_id'),
            ('omni.channel', 'omni_channel.channel_form', 'purpose_id'),
            ('omni.channel', 'omni_channel.channel_setup_form', 'purpose_id'),
        ]
        for model, xmlid, name in views:
            view_id = self.env.ref(xmlid).id if xmlid else None
            arch = etree.fromstring(self.env[model].get_view(view_id, 'form')['arch'])
            nodes = arch.xpath('//field[@name="%s"]' % name)
            self.assertTrue(nodes, (model, xmlid, name))
            self.assertEqual(nodes[0].get('widget'), 'radio', (model, xmlid, name))
            self.assertIn('horizontal', nodes[0].get('options', ''), (model, xmlid, name))
