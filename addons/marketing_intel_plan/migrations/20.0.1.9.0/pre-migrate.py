"""Proposal type is mandatory (owner, 2026-11-20). Campaigns without one get Paid when they have a budget or spend
lines (money spent outside), else Owned, before the column becomes NOT NULL."""


def migrate(cr, version):
    cr.execute("""
        UPDATE mi_plan p
           SET proposal_type = CASE
                   WHEN COALESCE(p.budget, 0) > 0
                     OR EXISTS (SELECT 1 FROM mi_plan_spend s WHERE s.plan_id = p.id AND s.amount > 0)
                   THEN 'paid' ELSE 'owned' END
         WHERE p.proposal_type IS NULL
    """)
