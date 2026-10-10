"""Test identities never invite real recipients, even outside Odoo's test runner."""
from odoo.tests import new_test_user as odoo_new_test_user


def new_test_user(env, *args, context=None, **kwargs):
    context = dict(context or {})
    context.update(no_reset_password=True, tracking_disable=True, mail_create_nosubscribe=True)
    return odoo_new_test_user(env, *args, context=context, **kwargs)
