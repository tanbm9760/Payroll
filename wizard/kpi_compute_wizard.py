from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayrollKpiComputeWizard(models.TransientModel):
    _name = 'payroll.kpi.compute.wizard'
    _description = 'Compute KPI by Period'

    period_id = fields.Many2one('payroll.kpi_period', string='KPI Period', required=True)
    quality_profile_id = fields.Many2one('payroll.kpi_quality_profile', string='Quality Profile')
    employee_ids = fields.Many2many('employee3c.employee.base', string='Employees',
                                    domain="[('user_id', '!=', False)]")
    overdue_threshold_days = fields.Integer(string='Overdue threshold (days)', default=7)

    def _ensure_quality_profile(self):
        self.ensure_one()
        if self.quality_profile_id:
            return self.quality_profile_id
        prof = self.env['payroll.kpi_quality_profile'].search([('active', '=', True)], limit=1)
        if not prof:
            raise UserError(_("No KPI Quality Profile configured."))
        self.quality_profile_id = prof.id
        return prof

    def action_compute(self):
        self.ensure_one()
        period = self.period_id
        if not period:
            raise UserError(_("Please select a KPI Period."))
        qprof = self._ensure_quality_profile()

        Engine = self.env['payroll.kpi_engine']
        Group = self.env['payroll.kpi_group']
        Label = self.env['payroll.kpi_label']

        groups = Group.search([('active', '=', True)])
        labels = Label.search([('active', '=', True)])

        employees = self.employee_ids
        if not employees:
            employees = self.env['employee3c.employee.base'].search([('user_id', '!=', False)])
        if not employees:
            raise UserError(_("No employees selected or available to compute KPI."))

        for emp in employees:
            counts = Engine.aggregate_employee_label_counts(emp, period, labels, overdue_threshold_days=int(self.overdue_threshold_days or 7))
            metrics = Engine.compute_group_metrics(counts, qprof, groups)
            Engine.upsert_kpi_records(emp, period, metrics)

        # Open KPI records for the selection
        domain = [('period_id', '=', period.id)]
        if employees:
            domain.append(('employee_id', 'in', employees.ids))
        return {
            'type': 'ir.actions.act_window',
            'name': _('KPI Records'),
            'res_model': 'payroll.kpi_record',
            'view_mode': 'tree,form',
            'domain': domain,
            'target': 'current',
        }
