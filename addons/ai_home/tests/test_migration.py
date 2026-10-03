import importlib.util
from pathlib import Path
from uuid import uuid4

from psycopg2 import sql

from odoo.tests import TransactionCase


class TestAiHomeMigration(TransactionCase):
    def test_rename_preserves_records_permissions_and_relations(self):
        path = Path(__file__).resolve().parents[1] / 'migrations/1.1/pre-rename-model.py'
        spec = importlib.util.spec_from_file_location('ai_home_rename_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        cr = self.env.cr
        schema = 'test_ai_home_' + uuid4().hex
        cr.execute('SHOW search_path')
        original_search_path = cr.fetchone()[0]
        cr.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            cr.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            cr.execute('CREATE TABLE work_dashboard_item (id integer PRIMARY KEY, name text)')
            cr.execute("INSERT INTO work_dashboard_item VALUES (7, 'Preserved card')")
            cr.execute('CREATE TABLE res_groups_work_dashboard_item_rel '
                       '(work_dashboard_item_id integer REFERENCES work_dashboard_item(id), '
                       'res_groups_id integer)')
            cr.execute('INSERT INTO res_groups_work_dashboard_item_rel VALUES (7, 3)')
            cr.execute('CREATE TABLE ai_home_item_seen_user_rel '
                       '(item_id integer REFERENCES work_dashboard_item(id), user_id integer)')
            cr.execute('INSERT INTO ai_home_item_seen_user_rel VALUES (7, 9)')
            cr.execute('CREATE TABLE ir_model (id integer PRIMARY KEY, model text)')
            cr.execute("INSERT INTO ir_model VALUES (42, 'work.dashboard.item')")
            cr.execute('CREATE TABLE ir_access (model_id integer REFERENCES ir_model(id))')
            cr.execute('INSERT INTO ir_access VALUES (42)')
            cr.execute('CREATE TABLE ir_model_fields (model text, relation text)')
            cr.execute("INSERT INTO ir_model_fields VALUES ('work.dashboard.item', 'res.groups')")
            cr.execute('CREATE TABLE ir_model_data (model text, name text, res_id integer)')
            cr.execute("""INSERT INTO ir_model_data VALUES
                ('ir.model', 'model_work_dashboard_item', 42),
                ('ir.model.fields', 'field_work_dashboard_item__name', 1),
                ('ir.model.fields.selection', 'selection__work_dashboard_item__tone__info', 2),
                ('work.dashboard.item', 'dashboard_recent_customer', 7)
            """)
            migration.migrate(cr, '20.0.1.0')
            migration.migrate(cr, '20.0.1.0')
            cr.execute('SELECT id, name FROM ai_home_item')
            self.assertEqual(cr.fetchall(), [(7, 'Preserved card')])
            cr.execute('SELECT ai_home_item_id, res_groups_id FROM ai_home_item_res_groups_rel')
            self.assertEqual(cr.fetchall(), [(7, 3)])
            cr.execute('SELECT item_id, user_id FROM ai_home_item_seen_user_rel')
            self.assertEqual(cr.fetchall(), [(7, 9)])
            cr.execute('SELECT model FROM ir_model JOIN ir_access ON model_id = id')
            self.assertEqual(cr.fetchone(), ('ai.home.item',))
            cr.execute('SELECT model FROM ir_model_fields')
            self.assertEqual(cr.fetchone(), ('ai.home.item',))
            cr.execute('SELECT model, name, res_id FROM ir_model_data ORDER BY res_id')
            self.assertEqual(cr.fetchall(), [
                ('ir.model.fields', 'field_ai_home_item__name', 1),
                ('ir.model.fields.selection', 'selection__ai_home_item__tone__info', 2),
                ('ai.home.item', 'dashboard_recent_customer', 7),
                ('ir.model', 'model_ai_home_item', 42),
            ])
        finally:
            cr.execute('SELECT set_config(%s, %s, true)', ['search_path', original_search_path])
            cr.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
