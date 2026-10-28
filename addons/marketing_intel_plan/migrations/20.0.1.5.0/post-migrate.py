"""Campaigns get a stage of the new lifecycle (Market Research › Planning › Execution › Results › Evaluation).

Campaigns made before the proposal approvals existed keep going where they are: a brief stays in Market Research,
drafts and reviews are in Planning (their proposal counts as approved), scheduled and live campaigns are in
Execution, finished ones in Results.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Plan = env['mi.plan'].with_context(active_test=False, mi_no_phase_sync=True, tracking_disable=True)
    mapping = {'planning': ('content', 'review'), 'execution': ('scheduled', 'live'), 'results': ('done',)}
    for phase, states in mapping.items():
        plans = Plan.search([('state', 'in', states)])
        plans.write({'phase': phase, 'proposal_state': 'approved'})
    # the owner's next step is now worded for the stage (e.g. submit the proposal)
    Plan.search([('is_template', '=', False), ('state', 'not in', ('done', 'cancelled'))])._sync_owner_activity()
