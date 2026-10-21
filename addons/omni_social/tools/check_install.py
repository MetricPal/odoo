import base64, io, logging, secrets, sys, tempfile, uuid
from datetime import timedelta
from PIL import Image
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import odoo
from odoo import api, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.modules import db
from odoo.modules.registry import Registry
from odoo.tests import Form
from odoo.tools import config


def exercise(env, directory):
    from odoo.addons.omni_channel.tests.test_users import new_test_user
    from odoo.addons.omni_social.models.social import internal
    from odoo.addons.omni_social.providers import vault
    from odoo.addons.omni_instagram.providers.api import Adapter as Instagram
    from odoo.addons.omni_linkedin.providers.api import Adapter as LinkedIn
    from odoo.addons.omni_social.controllers import media

    check = TestCase()
    store, load, remove = vault.store, vault.load, vault.remove
    with (
        patch.object(type(env['ir.mail_server']), 'send_email', side_effect=AssertionError('Email blocked')),
        patch.object(
            type(env['res.users']), '_action_reset_password', side_effect=AssertionError('Invitations blocked')
        ),
        patch.object(vault, 'store', side_effect=lambda b: store(b, directory)),
        patch.object(vault, 'load', side_effect=lambda r, **s: load(r, data_dir=directory, **s)),
        patch.object(vault, 'remove', side_effect=lambda r, d: remove(r, d, directory)),
    ):
        manager = new_test_user(
            env, login='social_manager', groups='omni_channel.group_omni_manager', company_id=env.company.id
        )
        operator = new_test_user(
            env, login='social_operator', groups='omni_channel.group_omni_user', company_id=env.company.id
        )
        approver = new_test_user(
            env,
            login='social_approver',
            groups='omni_channel.group_omni_user,approval_center.group_approval_center_approver',
            company_id=env.company.id,
        )
        outsider = new_test_user(
            env, login='social_outsider', groups='omni_channel.group_omni_manager', company_id=env.company.id
        )
        portal = new_test_user(env, login='social_portal', groups='base.group_portal', company_id=env.company.id)
        team = env['omni.purpose'].create(
            {
                'name': 'Social QA',
                'code': 'social_qa',
                'user_ids': [fields.Command.set([manager.id, operator.id, approver.id])],
            }
        )
        policy = env['approval.center.policy'].create(
            {
                'name': 'Social review',
                'company_id': env.company.id,
                'approver_ids': [fields.Command.create({'user_id': approver.id, 'required': True})],
            }
        )
        Connections = env['omni.social.connection'].with_user(manager)
        with Form(Connections, view='omni_social.connection_form') as form:
            form.name = 'LinkedIn QA'
            form.provider = 'linkedin'
            form.account_kind = 'person'
            form.purpose_id = team
            form.approval_type_id = policy
        account = form.record
        for vals in ({'connected': True}, {'profile': {'id': 'forged'}}, {'credential_reference': 'forged'}):
            with check.assertRaises(AccessError):
                account.write(vals)
        with check.assertRaises(AccessError):
            Connections.with_context(default_connected=True).create(
                {'name': 'Forged', 'provider': 'linkedin', 'purpose_id': team.id}
            )
        for user in (operator, outsider, portal):
            with check.assertRaises(AccessError):
                account.with_user(user).action_connect('synthetic')
        with patch.object(
            LinkedIn,
            'verify',
            return_value={
                'id': 'urn:li:person:SELF',
                'name': 'Person QA',
                'member': 'urn:li:person:SELF',
                'kind': 'person',
            },
        ):
            account.action_connect('synthetic')
        with check.assertRaises(UserError):
            account.write({'purpose_id': False})
        fixture = {
            'external_key': 'urn:li:ugcPost:100',
            'kind': 'post',
            'body': 'Existing post',
            'author': 'Person QA',
            'occurred_at': fields.Datetime.now(),
            'likes': 3,
            'comments': 1,
        }
        with patch.object(LinkedIn, 'read', return_value=([fixture], 'Latest activity')):
            account.action_sync()
            account.action_sync()
        check.assertEqual(env['omni.social.activity'].search_count([('connection_id', '=', account.id)]), 1)
        item = env['omni.social.activity'].search([('connection_id', '=', account.id)])
        with check.assertRaises(AccessError):
            item.with_user(manager).write({'body': 'Forged'})
        Publications = env['omni.social.publication'].with_user(operator)
        with Form(Publications, view='omni_social.publication_form') as draft:
            draft.name = 'Native publication form'
            draft.connection_id = account
            draft.body = 'Native content'
            draft.reason = 'QA'
        pub = Publications.create(
            {'name': 'Public post QA', 'connection_id': account.id, 'body': 'Exact approved post', 'reason': 'QA'}
        )
        with check.assertRaises(AccessError):
            pub.write({'state': 'approved'})
        with check.assertRaises(AccessError):
            Publications.with_context(default_state='approved').create(
                {'name': 'Forged', 'connection_id': account.id, 'body': 'bad', 'reason': 'bad'}
            )
        pub.action_submit()
        for user in (operator, manager, outsider, portal):
            with check.assertRaises(AccessError):
                pub.approval_request_id.with_user(user).action_approve()
        for user in (operator, manager, approver):
            with check.assertRaises(AccessError):
                pub.approval_request_id.with_user(user).write({'state': 'approved'})
        line = pub.approval_request_id.sudo().approver_ids
        with check.assertRaises(AccessError):
            line.with_user(manager).write({'status': 'approved'})
        with check.assertRaises(AccessError):
            env['approval.center.approver'].with_user(manager).with_context(
                default_request_id=pub.approval_request_id.id
            ).create({'user_id': manager.id})
        pub.approval_request_id.with_user(approver).action_approve()
        check.assertEqual(pub.state, 'approved')
        with check.assertRaises(AccessError):
            pub.write({'body': 'Edited after approval'})
        with check.assertRaises(AccessError):
            pub.with_user(outsider).action_publish()
        env.cr.commit()

        def send(bundle, doc, container):
            with env.registry.cursor() as cr:
                row = api.Environment(cr, api.SUPERUSER_ID, {})['omni.social.publication'].browse(pub.id)
                check.assertEqual(row.state, 'executing')
            check.assertEqual(doc['body'], 'Exact approved post')
            return 'sent', 'urn:li:ugcPost:200', 'Accepted'

        with patch.object(LinkedIn, 'execute', side_effect=send) as post:
            pub.action_publish()
            env.cr.rollback()
            pub.invalidate_recordset()
            check.assertEqual(pub.state, 'sent')
            check.assertEqual(pub.approval_request_id.audit_count, 3)
            with check.assertRaises(UserError):
                pub.action_publish()
            check.assertEqual(post.call_count, 1)
        uncertain = Publications.create(
            {'name': 'Unknown QA', 'connection_id': account.id, 'body': 'Unknown', 'reason': 'QA'}
        )
        uncertain.action_submit()
        uncertain.approval_request_id.with_user(approver).action_approve()
        env.cr.commit()
        with patch.object(LinkedIn, 'execute', side_effect=TimeoutError('secret must never leak')):
            uncertain.action_publish()
        env.cr.rollback()
        uncertain.invalidate_recordset()
        check.assertEqual(uncertain.state, 'unknown')
        with check.assertRaises(UserError):
            uncertain.action_publish()
        stale = Publications.create({'name': 'Stale QA', 'connection_id': account.id, 'body': 'Stale', 'reason': 'QA'})
        stale.action_submit()
        stale.approval_request_id.with_user(approver).action_approve()
        account.write({'active': False})
        with check.assertRaises(UserError):
            stale._claim()
        account.write({'active': True})
        ig = Connections.create(
            {
                'name': 'Instagram QA',
                'provider': 'instagram',
                'purpose_id': team.id,
                'approval_type_id': policy.id,
                'public_url': 'https://social.example.org',
            }
        )
        with patch.object(
            Instagram,
            'verify',
            return_value={'id': '1000', 'page': '2000', 'name': '@social_qa', 'kind': 'organization'},
        ):
            ig.action_connect('synthetic-page')
        incoming = {
            'external_key': 'mid.QA',
            'root_key': 'threadQA',
            'kind': 'message',
            'thread_key': 'threadQA',
            'recipient_key': '3000',
            'body': 'Incoming hello',
            'author': 'Tester',
            'occurred_at': fields.Datetime.now(),
        }
        with patch.object(Instagram, 'read', return_value=([incoming], 'Latest chats')):
            ig.action_sync()
        message = env['omni.social.activity'].search([('connection_id', '=', ig.id)])
        private = Publications.create(
            {
                'name': 'Private reply',
                'connection_id': ig.id,
                'operation': 'message',
                'target_id': message.id,
                'body': 'Thanks',
                'reason': 'QA',
            }
        )
        with check.assertRaises(UserError):
            private.action_submit()
        message.with_user(manager).action_consent()
        private.action_submit()
        private.approval_request_id.with_user(approver).action_approve()
        blocked = (
            env['omni.blocked.identity']
            .with_user(manager)
            .create(
                {
                    'company_id': env.company.id,
                    'purpose_id': team.id,
                    'channel_type_id': env.ref('omni_channel.channel_type_instagram').id,
                    'namespace': '1000',
                    'external_key': '3000',
                    'reason': 'QA block',
                }
            )
        )
        blocked.action_block()
        with check.assertRaises(UserError):
            private._claim()
        blocked.action_unblock()
        message.with_user(manager).action_revoke()
        with check.assertRaises(UserError):
            private._claim()
        with check.assertRaises(AccessError):
            message.with_user(operator).action_consent()
        image = io.BytesIO()
        Image.new('RGB', (32, 32), (152, 81, 132)).save(image, format='JPEG')
        photo = Publications.create(
            {
                'name': 'Approved photo',
                'connection_id': ig.id,
                'body': 'Photo caption',
                'reason': 'QA',
                'image': base64.b64encode(image.getvalue()).decode('ascii'),
            }
        )
        photo.action_submit()
        photo.approval_request_id.with_user(approver).action_approve()
        check.assertEqual(photo.payload['image_digest'], __import__('hashlib').sha256(image.getvalue()).hexdigest())
        token = photo.sudo().media_token
        fake = SimpleNamespace(
            env=env(user=env.ref('base.public_user').id, su=False),
            not_found=lambda: http.Response(status=404),
            make_response=lambda raw, headers: http.Response(raw, headers=headers),
        )
        with patch.object(media, 'request', fake):
            check.assertEqual(media.SocialMedia().image(token).status_code, 404)
        env.cr.commit()

        def stage(bundle, doc, container):
            check.assertIn('/omni/social/media/', doc['media_url'])
            check.assertFalse(container)
            with env.registry.cursor() as cr:
                public_env = api.Environment(cr, env.ref('base.public_user').id, {})
                fake = SimpleNamespace(
                    env=public_env,
                    not_found=lambda: http.Response(status=404),
                    make_response=lambda raw, headers: http.Response(raw, headers=headers),
                )
                with patch.object(media, 'request', fake):
                    response = media.SocialMedia().image(token)
                    check.assertEqual(response.data, image.getvalue())
                    check.assertEqual(response.headers['Cache-Control'], 'no-store')
            return 'waiting', '987', 'Processing'

        with patch.object(Instagram, 'execute', side_effect=stage):
            photo.action_publish()
        env.cr.rollback()
        photo.invalidate_recordset()
        check.assertEqual(photo.state, 'waiting')
        with patch.object(Instagram, 'execute', return_value=('sent', '988', 'Published')) as send:
            photo.action_publish()
            check.assertEqual(send.call_args.args[2], '987')
        env.cr.rollback()
        photo.invalidate_recordset()
        check.assertEqual(photo.state, 'sent')
        fake.env = env(user=env.ref('base.public_user').id, su=False)
        with patch.object(media, 'request', fake):
            check.assertEqual(media.SocialMedia().image(token).status_code, 404)
        check.assertEqual(photo.approval_request_id.with_user(approver).action_execute()['res_id'], photo.id)
        # Ordered carousel evidence freezes child rows as well as the parent.
        carousel = Publications.create(
            {
                'name': 'Ordered carousel',
                'connection_id': ig.id,
                'body': 'Ordered caption',
                'reason': 'QA',
                'format': 'carousel',
                'media_ids': [
                    fields.Command.create(
                        {
                            'sequence': seq,
                            'name': f'photo{seq}.jpg',
                            'file': base64.b64encode(image.getvalue()).decode('ascii'),
                        }
                    )
                    for seq in (20, 10)
                ],
            }
        )
        check.assertEqual(carousel.media_ids.mapped('sequence'), [10, 20])
        for user in (outsider, portal):
            with check.assertRaises(AccessError):
                carousel.media_ids.with_user(user).read(['file'])
        carousel.action_submit()
        carousel.approval_request_id.with_user(approver).action_approve()
        check.assertEqual([m['name'] for m in carousel.payload['media']], ['photo10.jpg', 'photo20.jpg'])
        for vals in (
            {'sequence': 99},
            {'file': base64.b64encode(b'forged').decode('ascii')},
            {'publication_id': pub.id},
        ):
            with check.assertRaises(AccessError):
                carousel.media_ids[:1].write(vals)
        with check.assertRaises(AccessError):
            carousel.media_ids[:1].unlink()
        with check.assertRaises(AccessError):
            env['omni.social.media'].with_user(operator).with_context(default_publication_id=carousel.id).create(
                {'name': 'forged.jpg', 'file': base64.b64encode(image.getvalue()).decode('ascii')}
            )
        token = carousel.sudo().media_token
        env.cr.commit()
        stages = []

        def multi_stage(bundle, doc, container):
            stages.append(container or '')
            with env.registry.cursor() as cr:
                fresh = api.Environment(cr, api.SUPERUSER_ID, {})['omni.social.publication'].browse(carousel.id)
                check.assertEqual(fresh.state, 'executing')
                check.assertEqual(fresh.container_key or '', container or '')
                fresh_public = api.Environment(cr, env.ref('base.public_user').id, {})
                fake = SimpleNamespace(
                    env=fresh_public,
                    not_found=lambda: http.Response(status=404),
                    make_response=lambda raw, headers: http.Response(raw, headers=headers),
                )
                with patch.object(media, 'request', fake):
                    check.assertEqual(media.SocialMedia().image(token, index=0).data, image.getvalue())
                    check.assertEqual(media.SocialMedia().image(token, index=2).status_code, 404)
            if len(stages) < 3:
                return 'waiting', str(len(stages)), 'Preparing media.'
            return 'sent', 'carousel-result', 'Accepted'

        with patch.object(Instagram, 'execute', side_effect=multi_stage):
            carousel.action_publish()
        env.cr.rollback()
        carousel.invalidate_recordset()
        check.assertEqual(stages, ['', '1', '2'])
        check.assertEqual(carousel.state, 'sent')
        fake.env = env(user=env.ref('base.public_user').id, su=False)
        with patch.object(media, 'request', fake):
            check.assertEqual(media.SocialMedia().image(token, index=0).status_code, 404)
        # Probe real MP4 bytes rather than trusting a filename or browser MIME hint.
        import subprocess

        video_path = Path(directory) / 'qa-reel.mp4'
        subprocess.run(
            [
                'ffmpeg',
                '-v',
                'error',
                '-f',
                'lavfi',
                '-i',
                'color=c=blue:s=180x320:r=24:d=3',
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-y',
                str(video_path),
            ],
            check=True,
            timeout=20,
        )
        reel = Publications.create(
            {
                'name': 'Reel QA',
                'connection_id': ig.id,
                'format': 'reel',
                'body': 'Video caption',
                'reason': 'QA',
                'media_ids': [
                    fields.Command.create(
                        {
                            'kind': 'video',
                            'name': 'qa-reel.mp4',
                            'file': base64.b64encode(video_path.read_bytes()).decode('ascii'),
                        }
                    )
                ],
            }
        )
        reel.action_submit()
        check.assertEqual(reel.payload['media'][0]['mime'], 'video/mp4')
        check.assertEqual(reel.payload['media'][0]['duration'], 3.0)
        broken = Publications.create(
            {
                'name': 'Broken MP4',
                'connection_id': ig.id,
                'format': 'reel',
                'body': 'Caption',
                'reason': 'QA',
                'media_ids': [
                    fields.Command.create(
                        {
                            'kind': 'video',
                            'name': 'fake.mp4',
                            'file': base64.b64encode(image.getvalue()).decode('ascii'),
                        }
                    )
                ],
            }
        )
        with check.assertRaises(UserError):
            broken.action_submit()
        story = Publications.create(
            {
                'name': 'Story QA',
                'connection_id': ig.id,
                'format': 'story',
                'reason': 'QA',
                'media_ids': [
                    fields.Command.create(
                        {'name': 'qa-story.jpg', 'file': base64.b64encode(image.getvalue()).decode('ascii')}
                    )
                ],
            }
        )
        story.action_submit()
        check.assertEqual(story.payload['body'], '')
        check.assertEqual(story.payload['format'], 'story')
        # Webhook credentials stay in the vault; public requests cannot forge receipts.
        ig.action_configure_webhook('synthetic-app-secret-123456')
        check.assertIn('/omni/social/webhook/', ig.webhook_url)
        check.assertEqual(ig._bundle()['webhook_secret'], 'synthetic-app-secret-123456')
        with check.assertRaises(AccessError):
            ig.with_user(operator).action_configure_webhook('synthetic-app-secret-123456')
        with check.assertRaises(AccessError):
            ig.write({'webhook_pending': True})
        route = ig.sudo().webhook_route
        from odoo.addons.omni_social.controllers import webhook as hook_controller
        import hashlib, hmac, json

        raw = json.dumps(
            {'object': 'instagram', 'entry': [{'id': '1000', 'time': 123, 'changes': [{'field': 'comments'}]}]}
        ).encode()
        header = 'sha256=' + hmac.new(b'synthetic-app-secret-123456', raw, hashlib.sha256).hexdigest()

        def webhook_request(body, signature):
            return SimpleNamespace(
                env=env(user=env.ref('base.public_user').id, su=False),
                httprequest=SimpleNamespace(
                    method='POST', stream=io.BytesIO(body), headers={'X-Hub-Signature-256': signature}
                ),
                not_found=lambda: http.Response(status=404),
                make_response=lambda raw='', headers=None, status=200: http.Response(
                    raw, headers=headers, status=status
                ),
            )

        with patch.object(hook_controller, 'request', webhook_request(raw, 'wrong')):
            check.assertEqual(hook_controller.SocialWebhook().incoming(route).status_code, 403)
        for repeat in range(2):
            with patch.object(hook_controller, 'request', webhook_request(raw, header)):
                check.assertEqual(hook_controller.SocialWebhook().incoming(route).status_code, 200)
        check.assertEqual(env['omni.social.webhook.receipt'].search_count([('connection_id', '=', ig.id)]), 1)
        check.assertTrue(ig.webhook_pending)
        with (
            patch.object(Instagram, 'read', return_value=([incoming], 'Webhook fixture')),
            patch.object(Instagram, 'execute', side_effect=AssertionError('Webhook must never publish')),
        ):
            env['omni.social.connection']._cron_webhooks()
        ig.invalidate_recordset()
        check.assertFalse(ig.webhook_pending)
        check.assertEqual(
            env['omni.social.activity'].search_count([('connection_id', '=', ig.id), ('external_key', '=', 'mid.QA')]),
            1,
        )
        ig.action_disable_webhook()
        with patch.object(hook_controller, 'request', webhook_request(raw, header)):
            check.assertEqual(hook_controller.SocialWebhook().incoming(route).status_code, 404)
        ancient = internal(env['omni.social.activity']).create(
            {
                'connection_id': ig.id,
                'external_key': 'ancient',
                'kind': 'post',
                'body': 'Old',
                'occurred_at': fields.Datetime.now() - timedelta(days=100),
            }
        )
        ig._purge_activity()
        check.assertFalse(ancient.exists())
        another = env['res.company'].create({'name': 'Other Social Company'})
        hidden = env['omni.social.connection'].create(
            {'name': 'Other company', 'provider': 'linkedin', 'company_id': another.id, 'purpose_id': team.id}
        )
        with check.assertRaises(AccessError):
            hidden.with_user(manager).read(['name'])
        for user in (outsider, portal):
            with check.assertRaises(AccessError):
                account.with_user(user).read(['name'])
        env.cr.commit()
        env['ir.module.module'].search([('name', '=', 'omni_instagram')]).button_immediate_uninstall()
        ig.invalidate_recordset()
        check.assertTrue(ig.exists())
        check.assertFalse(ig.active)
        check.assertFalse(ig.connected)
        check.assertEqual(ig.provider, 'unavailable')
        check.assertTrue(photo.exists())
        for row in env['ir.ui.view'].search(
            [('model', 'in', ['omni.social.connection', 'omni.social.activity', 'omni.social.publication'])]
        ):
            row._check_xml()
        print(
            'PASS: install/upgrade/views, native form, scopes, evidence forgery, distinct approver, immutable payload, committed claim, no duplicate or uncertain retry, stale account, private consent revocation, ordered media immutability, durable automatic stages, real MP4/JPEG validation, signed webhook dedup/disable/inbound-only cron',
            flush=True,
        )


def main():
    database = 'social_qa_' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='social-qa-') as directory:
        config.parse_config(
            [
                '-c',
                str(ROOT / 'odoo.conf'),
                '--data-dir',
                directory,
                '--no-http',
                '--log-level',
                'critical',
                '--log-handler',
                'py.warnings:ERROR',
            ],
            setup_logging=True,
        )
        logging.basicConfig(level=logging.CRITICAL)
        with (
            patch('requests.Session.request', side_effect=AssertionError('External request blocked')),
            patch('requests.Session.get', side_effect=AssertionError('External GET blocked')),
            patch('requests.Session.post', side_effect=AssertionError('External POST blocked')),
        ):
            try:
                db.create(database, demo=False, user_password=secrets.token_urlsafe(32), lang='en_US')
                registry = Registry(database)
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    env['ir.module.module'].search(
                        [
                            (
                                'name',
                                'in',
                                [
                                    'omni_instagram',
                                    'omni_linkedin',
                                    'omni_telegram',
                                    'omni_whatsapp',
                                    'omni_slack',
                                    'omni_teams',
                                ],
                            )
                        ]
                    ).button_immediate_install()
                registry = Registry(database)
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    assert not env.ref('base.module_omni_social').application
                    hidden = {
                        env.ref('omni_social.' + name).id
                        for name in ('menu_social', 'menu_activity', 'menu_publishing', 'menu_accounts')
                    }
                    assert hidden.isdisjoint(env['ir.ui.menu']._visible_menu_ids())
                    env.ref('omni_social.connection_form')._check_xml()
                    env['ir.module.module'].search(
                        [('name', 'in', ['omni_instagram', 'omni_linkedin'])]
                    ).button_immediate_upgrade()
                registry = Registry(database)
                with registry.cursor() as cr:
                    exercise(api.Environment(cr, api.SUPERUSER_ID, {}), directory)
            finally:
                if db.exist(database):
                    db.drop(database)
                print('Disposable Social database removed', flush=True)


if __name__ == '__main__':
    main()
