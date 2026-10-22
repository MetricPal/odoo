def migrate(cr, version):
    """Templates were a read-only SQL view; they are now a table (built-ins plus saved templates)."""
    cr.execute("SELECT relkind FROM pg_class WHERE relname = 'workflow_template'")
    row = cr.fetchone()
    if row and row[0] == 'v':
        cr.execute('DROP VIEW workflow_template')
