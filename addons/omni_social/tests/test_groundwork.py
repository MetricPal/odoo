"""Capability list, OAuth sign-in, usage meter and the Omnichannel catalogue link."""

import dataclasses
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.models.social import internal
from odoo.addons.omni_social.providers import registry, http
from odoo.addons.omni_social.providers.capabilities import Capabilities

PERSON = {'id': 'urn:li:person:SELF', 'name': 'Person QA', 'member': 'urn:li:person:SELF', 'kind': 'person'}


@tagged('post_install', '-at_install')
class TestSocialGroundwork(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        installed = registry.installed(cls.env)
        if 'linkedin' not in installed or 'instagram' not in installed:
            cls.skipTest(cls, 'Needs omni_linkedin and omni_instagram')
        cls.manager = new_test_user(cls.env, login='gw_manager', groups='omni_channel.group_omni_manager')
        cls.operator = new_test_user(cls.env, login='gw_operator', groups='omni_channel.group_omni_user')
        cls.approver = new_test_user(
            cls.env, login='gw_approver',
            groups='omni_channel.group_omni_user,approval_center.group_approval_center_approver',
        )
        cls.team = cls.env['omni.purpose'].create({
            'name': 'Groundwork QA', 'code': 'groundwork_qa',
            'user_ids': [fields.Command.set([cls.manager.id, cls.operator.id, cls.approver.id])],
        })
        cls.policy = cls.env['approval.center.policy'].create({
            'name': 'Groundwork review', 'company_id': cls.env.company.id,
            'approver_ids': [fields.Command.create({'user_id': cls.approver.id, 'required': True})],
        })
        cls.LinkedIn = type(registry.provider(cls.env, 'linkedin'))
        cls.account = cls.env['omni.social.connection'].with_user(cls.manager).create({
            'name': 'LinkedIn GW', 'provider': 'linkedin', 'account_kind': 'person',
            'purpose_id': cls.team.id, 'approval_type_id': cls.policy.id,
            'public_url': 'https://social.example.org',
        })

    def _connect(self):
        with patch.object(self.LinkedIn, 'verify', return_value=PERSON):
            self.account.action_connect('synthetic-token')

    def _post(self, body='Hello', **values):
        return self.env['omni.social.publication'].with_user(self.operator).create(
            {'name': 'GW post', 'connection_id': self.account.id, 'body': body, 'reason': 'QA', **values}
        )

    # ---- capability list ---------------------------------------------

    def test_connectors_declare_capabilities(self):
        linkedin = registry.capabilities('linkedin')
        instagram = registry.capabilities('instagram')
        self.assertEqual(linkedin.text_limit, 3000)
        self.assertNotIn('message', linkedin.operations)
        self.assertTrue(instagram.needs_public_url)
        self.assertTrue(linkedin.upload_bytes)
        self.assertTrue(http.allowed('www.linkedin.com'), 'token host is allowed once LinkedIn registers')
        self.assertFalse(http.allowed('evil.example'))
        self.assertIn('3,000 characters', self.account.rules_summary)
        self.assertTrue(self.account.oauth_available)
        self.assertEqual(self.account.credentials_ui['label'], 'LinkedIn')
        self.assertTrue(self.account.credentials_ui['installed'])

    def test_long_text_is_refused_with_the_platform_limit(self):
        self._connect()
        post = self._post('x' * 3001)
        with self.assertRaisesRegex(UserError, '3000 characters'):
            post.with_user(self.operator).action_submit()

    def test_unsupported_action_is_refused(self):
        self._connect()
        caps = registry.capabilities('linkedin')
        narrowed = dataclasses.replace(caps, operations=('reply',))
        with patch.dict(registry._CAPABILITIES, {'linkedin': narrowed}):
            with self.assertRaisesRegex(UserError, 'does not support this action'):
                self._post().with_user(self.operator).action_submit()

    def test_media_count_and_required_media(self):
        self._connect()
        caps = registry.capabilities('linkedin')
        with patch.dict(registry._CAPABILITIES, {'linkedin': dataclasses.replace(caps, media_required=True)}):
            with self.assertRaisesRegex(UserError, 'needs at least 1 photo or video'):
                self._post().with_user(self.operator).action_submit()

    # ---- usage meter ---------------------------------------------------

    def test_daily_limit_blocks_publishing(self):
        self._connect()
        caps = dataclasses.replace(registry.capabilities('linkedin'), daily_limits={'post': 1})
        Usage = internal(self.env['omni.social.usage']).sudo()
        with patch.dict(registry._CAPABILITIES, {'linkedin': caps}):
            self.account._check_quota('post', {})
            Usage.create({'connection_id': self.account.id, 'operation': 'post'})
            with self.assertRaisesRegex(UserError, 'limit is reached'):
                self.account._check_quota('post', {})
            self.account.invalidate_recordset(['usage_summary'])
            self.assertIn('1 of 1 posts', self.account.usage_summary)

    def test_monthly_budget_blocks_paid_platform(self):
        self._connect()
        caps = dataclasses.replace(registry.capabilities('linkedin'), costs={'post': 0.5})
        with patch.dict(registry._CAPABILITIES, {'linkedin': caps}):
            with self.assertRaisesRegex(UserError, 'monthly budget'):
                self.account._check_quota('post', {})
            self.account.monthly_budget = 1.0
            self.account._check_quota('post', {})
            internal(self.env['omni.social.usage']).sudo().create(
                {'connection_id': self.account.id, 'operation': 'post', 'cost': 0.75}
            )
            with self.assertRaisesRegex(UserError, 'monthly budget'):
                self.account._check_quota('post', {})
            self.account.invalidate_recordset(['usage_summary', 'month_cost'])
            self.assertAlmostEqual(self.account.month_cost, 0.75)
            self.assertIn('$0.75 of $1.00', self.account.usage_summary)

    def test_usage_is_server_owned(self):
        self._connect()
        with self.assertRaises(AccessError):
            self.env['omni.social.usage'].with_user(self.manager).create(
                {'connection_id': self.account.id, 'operation': 'post'}
            )

    def test_sent_publication_is_counted(self):
        self._connect()
        post = self._post('Counted post')
        post.with_user(self.operator).action_submit()
        post.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(post.state, 'approved')
        with patch.object(type(post), '_publish_step', autospec=True, side_effect=self._fake_step):
            post.with_user(self.operator).action_publish()
        self.assertEqual(post.state, 'sent')
        self.assertEqual(self.env['omni.social.usage'].search_count([('publication_id', '=', post.id)]), 1)

    def _fake_step(self, row):
        """Same bookkeeping as _publish_step, on the test cursor (no commit)."""
        key, doc, bundle, container = row._claim()
        internal(row).write({'state': 'sent', 'result_key': 'urn:li:share:1'})
        row.connection_id._record_usage(row, doc)
        return {}

    # ---- OAuth sign-in -------------------------------------------------

    def test_app_secret_is_manager_only(self):
        with self.assertRaises(AccessError):
            self.account.with_user(self.operator).action_oauth_app('client-id', 'client-secret')

    def test_sign_in_round_trip(self):
        account = self.account.with_user(self.manager)
        account.action_oauth_app('client-id', 'client-secret')
        self.assertEqual(account.oauth_client_id, 'client-id')
        self.assertTrue(account.oauth_ready)
        self.assertEqual(account.oauth_redirect_url, 'https://social.example.org/omni/social/oauth/callback')
        action = account.action_oauth_start()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        url = urlsplit(action['url'])
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual(url.netloc, 'www.linkedin.com')
        self.assertEqual(params['client_id'], 'client-id')
        self.assertEqual(params['redirect_uri'], account.oauth_redirect_url)
        self.assertNotIn('r_organization_social', params['scope'], 'personal profiles ask only member scopes')
        state = params['state']
        stored = self.env['omni.social.oauth.state'].sudo().search([('connection_id', '=', account.id)])
        self.assertEqual(len(stored), 1)
        self.assertNotEqual(stored.state_hash, state, 'state is stored hashed')

        States = self.env['omni.social.oauth.state']
        self.assertFalse(States.with_user(self.operator)._consume(state), 'only the person who started can finish')
        pending = States.with_user(self.manager)._consume(state)
        self.assertTrue(pending)
        self.assertFalse(States.with_user(self.manager)._consume(state), 'a state works once')

        class Pending:
            verifier = pending['verifier'] or ''
            redirect_uri = pending['redirect_uri']
            account = ''

        token_reply = {'access_token': 'fresh-token', 'refresh_token': 'refresh-1', 'expires_in': 3600}
        with patch('odoo.addons.omni_social.models.platform.call_form', return_value=token_reply) as exchange, \
                patch.object(self.LinkedIn, 'verify', return_value=PERSON) as verify:
            account._oauth_finish(Pending, 'auth-code')
        sent = exchange.call_args.args[1]
        self.assertEqual(sent['grant_type'], 'authorization_code')
        self.assertEqual(sent['code'], 'auth-code')
        self.assertEqual(sent['client_secret'], 'client-secret')
        self.assertEqual(verify.call_args.args[0], 'fresh-token')
        self.assertTrue(account.connected)
        bundle = account.sudo()._bundle()
        self.assertEqual(bundle['refresh_token'], 'refresh-1')

    def test_expired_token_refreshes_without_voiding_reviews(self):
        account = self.account.with_user(self.manager)
        account.action_oauth_app('client-id', 'client-secret')
        past = (fields.Datetime.now() - timedelta(minutes=1)).isoformat()
        with patch.object(self.LinkedIn, 'verify', return_value=PERSON):
            account._store_verified('old-token', '', {'refresh_token': 'refresh-1', 'expires_at': past})
        revision = account.revision
        reference = account.sudo().credential_reference
        reply = {'access_token': 'new-token', 'expires_in': 3600}
        with patch('odoo.addons.omni_social.models.platform.call_form', return_value=reply) as exchange:
            bundle = account._bundle()
        self.assertEqual(exchange.call_args.args[1]['grant_type'], 'refresh_token')
        self.assertEqual(bundle['token'], 'new-token')
        self.assertEqual(bundle['refresh_token'], 'refresh-1', 'refresh token is kept when not rotated')
        self.assertNotEqual(account.sudo().credential_reference, reference)
        self.assertEqual(account.revision, revision, 'a refresh does not invalidate pending reviews')
        with patch('odoo.addons.omni_social.models.platform.call_form') as again:
            account._bundle()
        again.assert_not_called()

    def test_sign_in_needs_public_address(self):
        account = self.account.with_user(self.manager)
        account.action_oauth_app('client-id', 'client-secret')
        account.public_url = False
        with self.assertRaisesRegex(UserError, 'public HTTPS address'):
            account.action_oauth_start()

    # ---- catalogue link ------------------------------------------------

    def test_catalogue_knows_social_platforms(self):
        types = self.env['omni.channel.type'].search([('code', 'in', ['instagram', 'linkedin', 'telegram'])])
        ready = {t.code: t.social_ready for t in types}
        self.assertTrue(ready.get('instagram'))
        self.assertTrue(ready.get('linkedin'))
        self.assertFalse(ready.get('telegram', False))
        channel = self.env['omni.channel'].new({})
        self.assertIn('Instagram', channel.social_platforms)
        self.assertIn('LinkedIn', channel.social_platforms)

    def test_summary_reads_naturally(self):
        caps = Capabilities(label='Demo', text_limit=500, media_kinds=('image', 'video'), max_media=20,
                            daily_limits={'post': 250, 'reply': 1000})
        self.assertEqual(
            caps.summary(),
            'Demo: up to 500 characters; photos and videos, up to 20 files; 250 posts a day; 1,000 replies a day',
        )
