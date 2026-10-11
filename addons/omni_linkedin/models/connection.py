from odoo import fields, models
class Connection(models.Model):
    _inherit='omni.social.connection'
    provider=fields.Selection(selection_add=[('linkedin','LinkedIn')],ondelete={'linkedin':lambda records: records._retire_provider()})
