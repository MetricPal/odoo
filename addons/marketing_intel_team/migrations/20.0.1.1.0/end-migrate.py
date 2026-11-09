"""Remove the tables of the former marketing team (its data moved to the department in post-migrate)."""


def migrate(cr, version):
    cr.execute("SELECT 1 FROM ir_model WHERE model IN ('mi.team', 'mi.team.member')")
    if cr.fetchone():
        return
    cr.execute('DROP TABLE IF EXISTS mi_team_member, mi_channel_mi_team_rel, mi_team CASCADE')
