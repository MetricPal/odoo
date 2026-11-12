"""The panel's "Assistant and automations" block lists the assistant jobs with their health and opens Jobs and
health (board 11.1)."""

from odoo import _, models



class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    def _automation_rows(self, brands):
        Job = self.env['mi.job']
        labels = dict(Job._fields['health']._description_selection(self.env))
        rows = []
        for job in Job.search([('state', '!=', 'off')]):
            rows.append({'title': job.name, 'subtitle': _('Assistant job · %s', job.owner_id.name or '-'),
                         'value': labels.get(job.health, ''), 'danger': job.health == 'failing',
                         'good': job.health == 'healthy', 'model': 'mi.job', 'res_id': job.id})
        return rows + super()._automation_rows(brands)

    def _block_automation_health(self, brands, plans):
        block = super()._block_automation_health(brands, plans)
        block.update({'action': 'marketing_intel_jobs.action_jobs', 'action_label': _('Jobs and health'),
                      'empty': _('No assistant job is on. Switch one on in Jobs and health.')})
        return block
