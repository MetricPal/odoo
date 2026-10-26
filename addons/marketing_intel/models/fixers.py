"""Who may fix what a guidance text points at.

A message that sends someone to a setting (the approvers of an approval type, a brand's accounts) only helps a
person who may change that setting: they get the link or button. Everyone else is told whom to ask instead.
"""

APPROVALS = 'approval_center.group_approval_center_manager'
BRANDS = 'marketing_intel.group_mi_manager'


def can_fix(user, group):
    """True when ``user`` may change what a ``group`` (xmlid) manages."""
    return bool(user) and user.has_group(group)


def whom_to_ask(env, group, company=None, limit=3):
    """Names of the people who may fix it (``group`` xmlid), for a message to someone who may not."""
    record = env.ref(group, raise_if_not_found=False)
    users = record.sudo().all_user_ids if record else env['res.users']
    users = users.filtered(lambda u: u.active and not u.share and (not company or company in u.company_ids))
    if not users:
        return env._('your administrator')
    names = ', '.join(users[:limit].mapped('name'))
    return env._('%s or another manager', names) if len(users) > limit else names
