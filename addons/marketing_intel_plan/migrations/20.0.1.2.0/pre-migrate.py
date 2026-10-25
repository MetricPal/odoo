def migrate(cr, version):
    # Draft / Ready / Running became Brief / Content / Review / Scheduled / Live. Old "Running" was set by hand,
    # so it maps to Content when nothing went out; the hourly sync moves it on from what the apps report.
    cr.execute("""
        UPDATE mi_plan SET state = CASE state WHEN 'draft' THEN 'brief' WHEN 'prepared' THEN 'content'
                                              WHEN 'running' THEN 'content' ELSE state END
         WHERE state IN ('draft', 'prepared', 'running')
    """)
