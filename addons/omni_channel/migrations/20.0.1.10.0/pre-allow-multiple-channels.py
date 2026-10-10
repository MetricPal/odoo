"""Allow several named channels for the same company/team/type."""


def migrate(cr, version):
    cr.execute('ALTER TABLE omni_channel DROP CONSTRAINT IF EXISTS omni_channel_scope_unique')
