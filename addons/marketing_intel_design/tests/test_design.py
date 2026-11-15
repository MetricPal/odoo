import io
import json
import zipfile
from unittest.mock import patch

from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal as agent_internal
from odoo.addons.marketing_intel_design.models import image_ask, render


def _png(size=(40, 30), color='red'):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, 'PNG')
    return buffer.getvalue()


def _size(content):
    return Image.open(io.BytesIO(content)).size


@tagged('post_install', '-at_install')
class TestDesignStudio(TransactionCase):
    """Design studio 3a, plan M6 (approved boards 13.1 to 13.4)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        groups = 'marketing_intel.group_mi_user,ai_agent.group_user'
        cls.junior = new_test_user(cls.env, 'design_junior', groups=groups)
        cls.other = new_test_user(cls.env, 'design_other', groups=groups)
        cls.senior = new_test_user(cls.env, 'design_senior', groups='marketing_intel_team.group_mi_senior')
        engine = cls.env['ai.agent.engine'].create({
            'name': 'Design engine', 'url': 'https://hermes.example.com', 'secret_reference': 'AI_AGENT_SECRET_TEST',
            'management_url': 'https://hermes.example.com', 'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        agent_internal(engine).write({'state': 'ready'})
        marketing = cls.env['hr.department'].create({'name': 'Design marketing'})
        marketing.action_create_ai_assistant()
        cls.agent = cls.env['ai.agent'].create({'name': 'Marketing Assistant', 'engine_id': engine.id,
                                               'department_id': marketing.id,
                                               'user_ids': [Command.set([cls.junior.id, cls.other.id])]})
        cls.agent.action_activate()
        cls.brand = cls.env['mi.brand'].create({
            'name': 'Design brand', 'offering': 'Plants', 'ai_agent_id': cls.agent.id,
            'kit_color_main': '#0B5FA5', 'kit_color_accent': '#F59E0B', 'kit_color_dark': '#1F2937',
            'kit_color_light': '#F3F4F6', 'kit_handle': '@design'})
        cls.offer = cls.env.ref('marketing_intel_design.template_offer')
        cls.tips = cls.env.ref('marketing_intel_design.template_tips')
        cls.Design = cls.env['mi.design']

    def _design(self, fmt='square', template=None, user=None, **values):
        return self.Design.with_user(user or self.junior).create({
            'name': 'Offer', 'format': fmt, 'template_id': (template or self.offer).id, 'brand_id': self.brand.id,
            **values})

    def _answer(self, record, field, text, state='completed', error=False):
        ai_run = record.sudo()[field]
        agent_internal(ai_run).write({'state': state, 'answer': text, 'error_message': error})
        ai_run._notify_origin()

    # ------------------------------------------------------------------ drawing

    def test_every_template_draws_in_every_format(self):
        picture = _png()
        for fmt in render.FORMATS:
            for template in render.TEMPLATES:
                for look in ('main', 'light', 'dark'):
                    image = render.render({'size': render.size_of(fmt), 'template': template, 'look': look,
                                           'headline': 'A headline that is quite long ' * 3, 'text': 'Text ' * 40,
                                           'button': 'Go', 'image': picture, 'brand': 'Brand', 'handle': '@b',
                                           'index': 1, 'count': 3}, 200)
                    width, height = render.size_of(fmt)
                    self.assertEqual(image.size, (200, round(height * 200 / width)), (fmt, template, look))

    def test_unreadable_picture_and_colours_do_not_break_a_design(self):
        image = render.render({'size': (1080, 1080), 'template': 'photo', 'image': b'not a picture',
                               'logo': b'nope', 'colors': {'main': 'javascript:1', 'accent': None}}, 120)
        self.assertEqual(image.size, (120, 120))
        self.assertEqual(image.getpixel((60, 110)), (0x71, 0x63, 0x9e), "Odoo's colour when the kit's is not a colour")

    # ------------------------------------------------------------------ brand kit (board 13.1)

    def test_brand_kit(self):
        self.assertFalse(self.brand.kit_empty)
        self.assertEqual(_size(self.brand.kit_preview_main.content), (420, 420))
        with self.assertRaises(ValidationError):
            self.brand.kit_color_main = 'blue'
        empty = self.env['mi.brand'].create({'name': 'No kit'})
        self.assertTrue(empty.kit_empty)
        self.assertEqual(empty._kit()['colors']['main'], False, 'The renderer falls back to Odoo colours')
        self.assertTrue(empty.kit_preview_light)

    # ------------------------------------------------------------------ a design (boards 13.2, 13.3)

    def test_new_design_from_the_dialog(self):
        wizard = self.env['mi.design.new'].with_user(self.junior).create({
            'format': 'carousel', 'template_id': self.tips.id, 'brand_id': self.brand.id})
        design = self.Design.browse(wizard.action_create()['res_id'])
        self.assertEqual(design.name, 'Tip list · Carousel')
        self.assertEqual(len(design.slide_ids), 3)
        self.assertEqual(design.slide_ids.mapped('label'), ['Cover', '1', 'Last'])
        self.assertEqual(design.active_slide_id, design.slide_ids[0])
        self.assertEqual(design.summary, 'Carousel · 3 slides · no campaign')
        self.assertEqual(_size(self.tips._sample('story', self.brand)), (220, 391))

    def test_the_slide_being_edited_and_the_preview(self):
        design = self._design('carousel', self.tips)
        second = design.slide_ids[1]
        design.active_slide_id = second
        before = design.preview.content
        design.write({'slide_headline': 'Let the assistant draft', 'slide_text': 'You only check.'})
        self.assertEqual(second.headline, 'Let the assistant draft')
        self.assertEqual(design.slide_label, 'Slide 1')
        self.assertEqual(design.preview_label, 'Slide 2 of 3')
        design.invalidate_recordset(['preview'])
        self.assertNotEqual(design.preview.content, before, 'The preview follows the texts')
        self.assertEqual(_size(design.preview.content), (520, 650))
        self.assertTrue(design.touched_at, 'A changed slide makes the cached pictures reload')
        self.assertIn('o_selected', design.strip)
        design.action_add_slide()
        self.assertEqual(design.slide_ids.mapped('label'), ['Cover', '1', '2', 'Last'])
        self.assertEqual(design.active_slide_id.label, '2', 'The new slide comes before the closing one')
        second.unlink()
        design.active_slide_id.unlink()
        self.assertEqual(design.active_slide_id, design.slide_ids[0], 'Never left without a slide to edit')

    def test_slide_rules(self):
        design = self._design()
        with self.assertRaises(ValidationError):
            design.slide_ids = [Command.create({})]
        with self.assertRaises(UserError):
            design.action_add_slide()
        with self.assertRaises(ValidationError):
            design.slide_ids.text = 'x' * 161
        carousel = self._design('carousel', self.tips)
        for _index in range(7):
            carousel.action_add_slide()
        with self.assertRaises(UserError):
            carousel.action_add_slide()

    def test_export_png_zip_pdf(self):
        design = self._design()
        name, kind, content = design._export('png')
        self.assertEqual((name, kind, _size(content)), ('Offer.png', 'image/png', (1080, 1080)))
        carousel = self._design('carousel', self.tips, name='Tips / "2026"')
        name, kind, content = carousel._export('png')
        self.assertEqual((name, kind), ('Tips 2026.zip', 'application/zip'))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.namelist(), ['Tips 2026-01.png', 'Tips 2026-02.png', 'Tips 2026-03.png'])
            self.assertEqual(_size(archive.read('Tips 2026-01.png')), (1080, 1350))
        name, kind, content = carousel._export('pdf')
        self.assertEqual((name, kind, content[:4]), ('Tips 2026.pdf', 'application/pdf', b'%PDF'))
        poster = self._design('poster', paper='a3')
        self.assertEqual(poster.format_label, 'Poster · A3')
        self.assertEqual(poster._images(100)[0].size, (100, 141))

    def test_copy_to_another_format(self):
        carousel = self._design('carousel', self.tips)
        carousel.slide_ids[1].write({'headline': 'Tip one', 'look': 'light'})
        carousel.active_slide_id = carousel.slide_ids[1]
        wizard = self.env['mi.design.copy'].with_user(self.junior).create({'design_id': carousel.id,
                                                                           'format': 'story'})
        story = self.Design.browse(wizard.action_copy()['res_id'])
        self.assertEqual((story.format, story.name), ('story', 'Offer (Story)'))
        self.assertEqual(story.slide_ids.mapped('headline'), ['Tip one'])
        wizard = self.env['mi.design.copy'].with_user(self.junior).create({'design_id': story.id,
                                                                           'format': 'carousel'})
        again = self.Design.browse(wizard.action_copy()['res_id'])
        self.assertEqual(len(again.slide_ids), 3)

    def test_who_sees_a_design(self):
        design = self._design()
        self.assertFalse(self.Design.with_user(self.other).search([('id', '=', design.id)]))
        with self.assertRaises(AccessError):
            design.with_user(self.other).slide_ids.headline = 'Not mine'
        self.assertTrue(self.Design.with_user(self.senior).search([('id', '=', design.id)]))
        plan = self.env['mi.plan'].with_user(self.other).create({'name': 'Their campaign', 'brand_id': self.brand.id})
        design.sudo().plan_id = plan
        self.assertTrue(self.Design.with_user(self.other).search([('id', '=', design.id)]),
                        "The campaign owner sees the campaign's designs")
        self.assertEqual(plan.design_count, 1)
        self.assertEqual(plan.action_open_designs()['domain'], [('plan_id', '=', plan.id)])

    # ------------------------------------------------------------------ writing tools on the slide's texts

    def test_writing_tools_on_a_slide(self):
        design = self._design()
        Writing = self.env['mi.writing'].with_user(self.junior)
        tools = Writing.get_tools('mi.design', 'slide_headline')
        self.assertTrue(tools['available'])
        self.assertEqual((tools['kind'], tools['limit']), ('design_headline', 60))
        self.assertNotIn('fit', tools['tools'])
        prompt = Writing._prompt('design_text', 'shorter', 'Some text', False, {})
        self.assertIn('the short text of a designed social post', prompt)
        self.assertIn('Never go over 160 characters.', prompt)
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            self.assertTrue(Writing.ask('mi.design', 'slide_headline', design.id, 'rewrite', 'Hello there'))
        with self.assertRaises(AccessError):
            self.env['mi.writing'].with_user(self.other).ask('mi.design', 'slide_headline', design.id, 'rewrite', 'x')

    # ------------------------------------------------------------------ ✦ Suggest text for all slides

    def test_suggest_text_fills_empty_fields_and_suggests_the_rest(self):
        design = self._design('carousel', self.tips)
        design.slide_ids[0].headline = 'My own cover'
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            design.action_suggest_text()
        self.assertEqual(design.suggest_state, 'asking')
        self.assertIn('Slide 1: headline "My own cover"', design.sudo().suggest_run_id.prompt)
        answer = 'Here you go:\n' + json.dumps([
            {'headline': 'A better cover', 'text': 'Cover text', 'button': ''},
            {'headline': 'Tip one', 'text': 'x' * 400, 'button': ''},
            {'headline': 'Start today', 'text': '', 'button': 'Try it'}])
        self._answer(design, 'suggest_run_id', answer)
        self.assertFalse(design.suggest_state)
        cover, tip, last = design.slide_ids
        self.assertEqual((cover.headline, cover.suggested_headline, cover.text),
                         ('My own cover', 'A better cover', 'Cover text'))
        self.assertEqual((tip.headline, len(tip.text)), ('Tip one', 160))
        self.assertEqual(last.button, 'Try it')
        design.active_slide_id = cover
        design.action_use_headline()
        self.assertEqual((cover.headline, cover.suggested_headline), ('A better cover', False))

    def test_suggest_text_says_why_it_failed(self):
        design = self._design()
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            design.action_suggest_text()
        self._answer(design, 'suggest_run_id', 'I would rather write a poem.')
        self.assertEqual(design.suggest_state, 'failed')
        self.assertIn('did not give texts', design.suggest_error)
        design.action_dismiss_suggest_error()
        self.assertFalse(design.suggest_state)

    # ------------------------------------------------------------------ ✦ AI image (board 13.4 A, C)

    def _ask(self, design, image_on=True):
        Ask = type(self.env['mi.design.image.ask'])
        with patch.object(Ask, '_image_on', lambda self, agent: image_on), \
             patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            ask = self.env['mi.design.image.ask'].with_user(self.junior).browse(
                design.action_ai_image()['res_id'])
            ask.description = 'A tidy desk in morning light'
            if image_on:
                ask.action_make()
        return ask

    def test_ai_image_goes_on_the_slide(self):
        design = self._design()
        ask = self._ask(design)
        self.assertEqual(ask.state, 'making')
        prompt = ask.sudo().ai_run_id.prompt
        self.assertIn('image generation tool', prompt)
        self.assertIn('landscape format', prompt)
        self.assertIn('A tidy desk in morning light', prompt)
        with patch.object(image_ask, 'fetch_picture', return_value=_png((64, 64), 'blue')) as fetch:
            self._answer(ask, 'ai_run_id', 'Here it is: https://cdn.example.com/a/picture.png.')
        fetch.assert_called_once_with('https://cdn.example.com/a/picture.png')
        self.assertEqual(ask.state, 'ready')
        self.assertEqual(_size(ask.image.content), (64, 64))
        self.assertIn('Made by Marketing Assistant', ask.made_label)
        ask.action_use()
        self.assertEqual(_size(design.slide_ids.image.content), (64, 64))
        self.assertFalse(ask.exists(), 'The ask is finished once a picture is used')

    def test_ai_image_reasons(self):
        design = self._design()
        off = self._ask(design, image_on=False)
        Ask = type(self.env['mi.design.image.ask'])
        with patch.object(Ask, '_image_on', lambda self, agent: False):
            self.assertEqual(off.problem, 'off')
            self.assertIn('Image generation is not switched on for Marketing Assistant', off.problem_text)
            with self.assertRaises(UserError):
                off.action_make()
        off.unlink()
        ask = self._ask(design)
        self._answer(ask, 'ai_run_id', 'No image model is set, so I cannot make pictures.')
        self.assertEqual(ask.state, 'failed')
        self.assertIn('No image model is set', ask.error)
        with patch.object(Ask, '_image_on', lambda self, agent: True), \
             patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            ask.action_make()
        with patch.object(image_ask, 'fetch_picture', side_effect=image_ask.PictureError(image_ask.NOT_PICTURE)):
            self._answer(ask, 'ai_run_id', 'https://cdn.example.com/x')
        self.assertEqual(ask.state, 'failed')
        self.assertIn('is not a picture', ask.error)
        self.agent.sudo().action_pause()
        ask.invalidate_recordset(['problem', 'problem_text'])
        self.assertEqual(ask.problem, 'none')

    def test_pictures_are_fetched_from_public_https_only(self):
        for address in ('http://cdn.example.com/a.png', 'https://127.0.0.1/a.png', 'https://localhost/a.png',
                        'https://169.254.169.254/latest', 'https://10.0.0.5/a.png', 'file:///etc/passwd'):
            with self.assertRaises(image_ask.PictureError, msg=address):
                image_ask.fetch_picture(address)

    # ------------------------------------------------------------------ Use in (board 13.4 B)

    def test_use_in_a_proof_and_from_designs(self):
        plan = self.env['mi.plan'].with_user(self.junior).create({'name': 'Campaign', 'brand_id': self.brand.id})
        design = self._design(plan_id=plan.id)
        self.assertIn('proof', design.use_targets.split(','))
        self.assertNotIn('email', design.use_targets.split(','))
        action = design.action_use_proof()
        wizard = self.env['mi.design.use'].with_user(self.junior).with_context(action['context']).create({})
        proof = self.env['mi.proof'].browse(wizard.action_apply()['res_id'])
        self.assertEqual((proof.plan_id, proof.name), (plan, 'Offer'))
        self.assertEqual(_size(proof.image.content), (1080, 1080))
        # The other way round, on a draft proof
        proof.image = False
        action = proof.action_mi_from_designs()
        wizard = self.env['mi.design.use'].with_user(self.junior).with_context(action['context']).create(
            {'design_id': design.id})
        wizard.action_apply()
        self.assertTrue(proof.image)

    def test_use_in_an_email(self):
        if not self.env['mailing.mailing'].with_user(self.junior).has_access('create'):
            self.junior.group_ids += self.env.ref('mass_mailing.group_mass_mailing_user')
        header = self._design('email_header')
        self.assertIn('email', header.use_targets.split(','))
        action = header.action_use_email()
        wizard = self.env['mi.design.use'].with_user(self.junior).with_context(action['context']).create({})
        mailing = self.env['mailing.mailing'].browse(wizard.action_apply()['res_id'])
        self.assertEqual((mailing.state, mailing.subject), ('draft', 'Offer'))
        self.assertIn('<img', mailing.body_arch)
        self.assertNotIn('base64', mailing.body_arch, 'The mailing serves the picture as its own file')
        with self.assertRaises(UserError):
            self._design().action_use_email()

    def test_use_in_a_social_post_and_from_designs(self):
        from odoo.addons.omni_social.models.social import internal as omni_internal  # noqa: PLC0415
        from odoo.addons.omni_social.providers import registry  # noqa: PLC0415
        installed = sorted(registry.installed(self.env), key=lambda name: name != 'instagram')
        if not installed:
            self.skipTest('Needs a social platform module')
        provider = installed[0]
        expected = 'carousel' if 'carousel' in registry.capabilities(provider).formats else 'standard'
        self.junior.group_ids += self.env.ref('omni_channel.group_omni_user')
        team = self.env['omni.purpose'].create({'name': 'Design QA', 'code': 'design_qa',
                                                'user_ids': [Command.set(self.junior.ids)]})
        account = self.env['omni.social.connection'].create({'name': 'Design account', 'provider': provider,
                                                             'purpose_id': team.id})
        omni_internal(account).write({'connected': True, 'profile_name': '@design'})
        self.env['mi.brand.account'].create({'brand_id': self.brand.id,
                                             'account': 'omni.social.connection,%s' % account.id})
        carousel = self._design('carousel', self.tips)
        carousel.slide_ids[0].headline = 'Cover line'
        self.assertIn('social', carousel.use_targets.split(','))
        post = self.env['omni.social.publication'].browse(carousel.action_use_social()['res_id'])
        self.assertEqual((post.state, post.format, post.connection_id, post.body),
                         ('draft', expected, account, 'Cover line'))
        self.assertEqual(post.media_ids.mapped('name'), ['Offer-01.png', 'Offer-02.png', 'Offer-03.png'])
        self.assertEqual((post.media_ids[0].width, post.media_ids[0].height), (1080, 1350))
        # The other way round: From Designs adds a design's picture to the draft post
        action = post.action_mi_from_designs()
        wizard = self.env['mi.design.use'].with_user(self.junior).with_context(action['context']).create(
            {'design_id': self._design().id})
        wizard.action_apply()
        self.assertEqual(post.media_ids.mapped('name')[-1], 'Offer.png')
        with self.assertRaises(UserError):
            self._design('email_header').action_use_social()

    def test_from_the_library(self):
        design = self._design()
        self.assertEqual(design.action_pick_library()['context'], {'mi_slide_id': design.slide_ids.id})
