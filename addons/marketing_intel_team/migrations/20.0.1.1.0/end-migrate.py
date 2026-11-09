"""Remove the tables of the former marketing team (its data moved to the department in post-migrate). The models are
no longer defined at this point; Odoo removes their registrations afterwards."""


def migrate(cr, version):
    cr.execute('DROP TABLE IF EXISTS mi_team_member, mi_channel_mi_team_rel, mi_team CASCADE')
