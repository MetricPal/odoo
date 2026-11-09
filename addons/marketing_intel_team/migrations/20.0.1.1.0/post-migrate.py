"""The marketing team record becomes its department (owner, 2026-11-09: "no Team, everything under the department")."""


def _table_exists(cr, name):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", [name])
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _table_exists(cr, 'mi_team'):
        return
    cr.execute("""
        UPDATE hr_department d
           SET mi_is_marketing = TRUE,
               mi_senior_budget_limit = t.senior_budget_limit,
               mi_senior_audience_limit = t.senior_audience_limit
          FROM mi_team t
         WHERE t.department_id = d.id
    """)
    if _table_exists(cr, 'mi_channel_mi_team_rel'):
        cr.execute("""
            INSERT INTO hr_department_mi_channel_rel (department_id, channel_id)
            SELECT t.department_id, r.mi_channel_id
              FROM mi_channel_mi_team_rel r JOIN mi_team t ON t.id = r.mi_team_id
             WHERE t.department_id IS NOT NULL
            ON CONFLICT DO NOTHING
        """)
