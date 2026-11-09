"""The HOD is the owner's department manager: proposal approvers keep only Finance and CEO (board 7, 2026-11-09)."""


def migrate(cr, version):
    cr.execute("DELETE FROM mi_approver WHERE role = 'hod'")
