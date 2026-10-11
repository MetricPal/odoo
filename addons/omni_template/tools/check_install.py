"""Disposable installation and native Odoo tests, with external I/O blocked."""
import logging
import json
import os
import subprocess
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import odoo
from odoo import api
from odoo.modules import db
from odoo.modules.registry import Registry
from odoo.tools import config

def main():
    database = 'template_qa_' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='template-qa-') as directory:
        config.parse_config(['-c',str(ROOT/'odoo.conf'),'--data-dir',directory,'--no-http','--log-level','critical','--log-handler','py.warnings:ERROR'],setup_logging=True)
        logging.basicConfig(level=logging.CRITICAL)
        with patch('requests.Session.request',side_effect=AssertionError('External request blocked')):
            try:
                db.create(database,demo=False,user_password=secrets.token_urlsafe(32),lang='en_US')
                registry = Registry(database)
                with registry.cursor() as cr:
                    env=api.Environment(cr,api.SUPERUSER_ID,{})
                    env['ir.module.module'].search([('name','=','omni_template')]).button_immediate_install()
                registry = Registry(database)
                with registry.cursor() as cr:
                    env=api.Environment(cr,api.SUPERUSER_ID,{})
                    for row in env['ir.ui.view'].search([('model','=','omni.template')]): row._check_xml()
                    env.ref('base.module_omni_template').button_immediate_upgrade()
                from odoo.addons.omni_template.tests.test_template import TestTemplates
                config['db_name'] = [database]
                import threading
                threading.current_thread().dbname = database
                TestTemplates.registry = Registry(database)
                suite=unittest.defaultTestLoader.loadTestsFromTestCase(TestTemplates)
                result=unittest.TextTestRunner(verbosity=2).run(suite)
                if not result.wasSuccessful(): raise SystemExit(1)
                if os.environ.get('OMNI_NODE_MODULES'):
                    # All access fixtures live only in this disposable database.
                    from odoo.addons.omni_channel.tests.test_users import new_test_user
                    from odoo import fields
                    with Registry(database).cursor() as cr:
                        env=api.Environment(cr,api.SUPERUSER_ID,{})
                        password=secrets.token_urlsafe(32)
                        operator=new_test_user(env,login='template_browser',password=password,groups='omni_channel.group_omni_user')
                        team=env['omni.purpose'].create({'name':'Template UI QA','code':'template_browser','user_ids':[fields.Command.link(operator.id)]})
                        contact=env['res.partner'].create({'name':'Aisha Rahman','company_id':env.company.id})
                        template=env['omni.template'].with_user(operator).create({'name':'Welcome message','purpose_id':team.id,'channel_type_id':env.ref('omni_channel.channel_type_telegram').id,'resource_ref':f'res.partner,{contact.id}','body':'Hi {{ object.name }},\n\nWelcome to {{ company.name }}.\nWe’re happy to help you get started.'})
                        fixture={'database':database,'login':operator.login,'password':password,'template':template.id,'action':env.ref('omni_template.action_templates').id}
                        path=Path(directory)/'fixture.json'
                        path.write_text(json.dumps(fixture));path.chmod(0o600)
                        cr.commit()
                    with open('/tmp/template-browser-server.log','w') as log:
                        server=subprocess.Popen([sys.executable,str(ROOT/'odoo-bin'),'-c',str(ROOT/'odoo.conf'),'-d',database,'--data-dir',directory,'--http-port','8089','--gevent-port','8090','--max-cron-threads','0','--log-level','warn','--log-handler','py.warnings:ERROR'],stdout=log,stderr=log)
                        try:
                            browser_env=dict(os.environ,OMNI_TEMPLATE_FIXTURE=str(path))
                            subprocess.run([os.environ.get('OMNI_NODE','node'),str(Path(__file__).with_name('test_live.cjs'))],env=browser_env,check=True)
                        finally:
                            server.terminate()
                            try: server.wait(timeout=15)
                            except subprocess.TimeoutExpired: server.kill();server.wait()

            finally:
                if db.exist(database): db.drop(database)
                print('Disposable template database removed',flush=True)

if __name__ == '__main__': main()
