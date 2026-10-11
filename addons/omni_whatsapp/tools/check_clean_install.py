"""Fresh disposable database: install/upgrade WhatsApp without Telegram, then remove it."""
import logging
import secrets
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import odoo
from odoo import api
from odoo.modules import db
from odoo.modules.registry import Registry
from odoo.tools import config


def main():
    database = 'wa_qa_' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='wa-qa-') as directory:
        config.parse_config(['-c', str(ROOT / 'odoo.conf'), '--data-dir', directory,
                             '--no-http', '--log-level', 'error', '--log-handler', 'py.warnings:ERROR'],
                            setup_logging=True)
        logging.basicConfig(level=logging.ERROR)
        with patch('requests.Session.get', side_effect=AssertionError('External GET blocked')), \
             patch('requests.Session.post', side_effect=AssertionError('External POST blocked')):
            try:
                db.create(database, demo=False, user_password=secrets.token_urlsafe(32), lang='en_US')
                registry = Registry(database)
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    env['ir.module.module'].search([('name', '=', 'omni_whatsapp')]).button_immediate_install()
                registry = Registry(database)
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    assert env['ir.module.module'].search([('name', '=', 'omni_whatsapp')]).state == 'installed'
                    assert env['ir.module.module'].search([('name', '=', 'omni_telegram')]).state != 'installed'
                    env.ref('omni_channel.channel_setup_form')._check_xml()
                    print('PASS: clean install and native form; Telegram is not installed', flush=True)
                    env['ir.module.module'].search([('name', '=', 'omni_whatsapp')]).button_immediate_upgrade()
                registry = Registry(database)
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    env.ref('omni_channel.channel_setup_form')._check_xml()
                    print('PASS: repeated WhatsApp upgrade and view validation', flush=True)
                    checker = ROOT / 'addons/omni_whatsapp/tools/check_credentials.py'
                    exec(compile(checker.read_text(), str(checker), 'exec'), {'env': env, 'real_transactions': True})
            finally:
                if db.exist(database):
                    db.drop(database)
                print('Disposable WhatsApp database and filestore removed', flush=True)


if __name__ == '__main__':
    main()
