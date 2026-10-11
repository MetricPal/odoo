from odoo import fields, models
class Connection(models.Model):
    _inherit='omni.social.connection'
    provider=fields.Selection(selection_add=[('instagram','Instagram')],ondelete={'instagram':lambda records: records._retire_provider()})
