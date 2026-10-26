"""Team workload: per person, the open campaign tasks, the campaigns they run and the proofs they review."""

from odoo import fields, models, tools


class Workload(models.Model):
    _name = 'mi.workload'
    _description = 'Marketing workload'
    _auto = False
    _order = 'user_id, deadline'

    user_id = fields.Many2one('res.users', string='Person', readonly=True)
    kind = fields.Selection([('task', 'Task'), ('campaign', 'Campaign'), ('proof', 'Proof to review')],
                            readonly=True)
    name = fields.Char(readonly=True)
    plan_id = fields.Many2one('mi.plan', string='Campaign', readonly=True)
    brand_id = fields.Many2one('mi.brand', string='Brand', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    deadline = fields.Date(readonly=True)
    hours = fields.Float(string='Planned hours', readonly=True)
    late = fields.Boolean(readonly=True)
    task_id = fields.Many2one('project.task', readonly=True)
    proof_id = fields.Many2one('mi.proof', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT row_number() OVER () AS id, w.* FROM (
                    SELECT rel.user_id, 'task' AS kind, t.name::text AS name, p.id AS plan_id, p.brand_id,
                           p.company_id, t.date_deadline::date AS deadline, COALESCE(t.allocated_hours, 0) AS hours,
                           (t.date_deadline IS NOT NULL AND t.date_deadline < now() AT TIME ZONE 'UTC') AS late,
                           t.id AS task_id, NULL::integer AS proof_id
                      FROM project_task t
                      JOIN project_task_user_rel rel ON rel.task_id = t.id
                      JOIN mi_plan p ON p.id = t.mi_plan_id
                     WHERE t.active AND t.state NOT IN ('1_done', '1_canceled') AND p.is_template IS NOT TRUE
                       AND p.state NOT IN ('done', 'cancelled')
                    UNION ALL
                    SELECT p.user_id, 'campaign', p.name, p.id, p.brand_id, p.company_id, p.date_end, 0,
                           false, NULL, NULL
                      FROM mi_plan p
                     WHERE p.state IN ('brief', 'content', 'review', 'scheduled', 'live') AND p.is_template IS NOT TRUE
                    UNION ALL
                    SELECT f.reviewer_id, 'proof', f.name || ' v' || f.version, p.id, p.brand_id, p.company_id,
                           p.date_start, 0, (p.date_start < CURRENT_DATE), NULL, f.id
                      FROM mi_proof f JOIN mi_plan p ON p.id = f.plan_id
                     WHERE f.state = 'review' AND f.reviewer_id IS NOT NULL
                ) w
            )""" % self._table)

    def action_open(self):
        self.ensure_one()
        model, res_id = ('project.task', self.task_id.id) if self.task_id else (
            ('mi.proof', self.proof_id.id) if self.proof_id else ('mi.plan', self.plan_id.id))
        return {'type': 'ir.actions.act_window', 'res_model': model, 'res_id': res_id, 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'current'}
