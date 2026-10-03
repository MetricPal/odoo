"""Preserve AI Home records and metadata when renaming its item model."""

from psycopg2 import sql

from odoo.tools.sql import column_exists, table_exists


def migrate(cr, version):
    old_model = 'work.dashboard.item'
    new_model = 'ai.home.item'
    for old_table, new_table in (
        ('work_dashboard_item', 'ai_home_item'),
        ('res_groups_work_dashboard_item_rel', 'ai_home_item_res_groups_rel'),
    ):
        if table_exists(cr, old_table):
            if table_exists(cr, new_table):
                raise RuntimeError(f'Cannot rename {old_table}: {new_table} already exists')
            cr.execute(sql.SQL('ALTER TABLE {} RENAME TO {}').format(
                sql.Identifier(old_table), sql.Identifier(new_table),
            ))

    if column_exists(cr, 'ai_home_item_res_groups_rel', 'work_dashboard_item_id'):
        cr.execute('ALTER TABLE ai_home_item_res_groups_rel '
                   'RENAME COLUMN work_dashboard_item_id TO ai_home_item_id')

    # Preserve IDs so ir.access and other model/field foreign keys stay valid.
    for table, column in (
        ('ir_model', 'model'),
        ('ir_model_fields', 'model'),
        ('ir_model_fields', 'relation'),
        ('ir_model_data', 'model'),
        ('ir_ui_view', 'model'),
        ('ir_act_window', 'res_model'),
        ('ir_attachment', 'res_model'),
        ('ir_filters', 'model_id'),
        ('ir_exports', 'resource'),
    ):
        if column_exists(cr, table, column):
            cr.execute(sql.SQL('UPDATE {} SET {} = %s WHERE {} = %s').format(
                sql.Identifier(table), sql.Identifier(column), sql.Identifier(column),
            ), [new_model, old_model])

    cr.execute("""
        UPDATE ir_model_data
           SET name = replace(name, 'work_dashboard_item', 'ai_home_item')
         WHERE model IN ('ir.model', 'ir.model.fields', 'ir.model.fields.selection')
           AND (name = 'model_work_dashboard_item'
                OR starts_with(name, 'field_work_dashboard_item__')
                OR starts_with(name, 'selection__work_dashboard_item__'))
    """)
