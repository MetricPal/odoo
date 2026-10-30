from odoo import fields, models


class MailActivityType(models.Model):
    _inherit = 'mail.activity.type'

    home_decision = fields.Boolean(
        'Decision on Home',
        help='Activities of this type are decisions: Home shows them in "Needs your attention" instead of the '
             'assignee\'s plan.')
