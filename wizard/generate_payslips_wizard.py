# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayrollGeneratePayslipsWizard(models.TransientModel):
    _name = "payroll.generate.payslips.wizard"
    _description = "Generate Payslips for Batch"

    run_id = fields.Many2one("payroll.payslip.run", required=True, string="Batch")
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    # Deprecated selections (kept for compatibility; not shown in view)
    department_id = fields.Many2one("employee3c.department", string="Department")
    employee_ids = fields.Many2many("employee3c.employee.base", string="Employees")
    structure_id = fields.Many2one("payroll.structure", string="Structure", required=True)

    @api.onchange("run_id")
    def _onchange_run(self):
        for w in self:
            if w.run_id:
                w.date_start = w.run_id.date_start
                w.date_end = w.run_id.date_end

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Auto select current batch (date_start <= today <= date_end), else latest by date_end
        Run = self.env['payroll.payslip.run']
        today = fields.Date.context_today(self)
        current = Run.search([('date_start', '<=', today), ('date_end', '>=', today)], order='date_end desc', limit=1)
        if not current:
            current = Run.search([], order='date_end desc', limit=1)
        if current:
            res['run_id'] = current.id
            res['date_start'] = current.date_start
            res['date_end'] = current.date_end
        return res

    def action_generate(self):
        self.ensure_one()
        if self.date_start > self.date_end:
            raise UserError(_("Start date must be before end date."))
        # Filter employees: only 'probation' or 'official'
        domain = [('state', 'in', ['probation', 'official'])]
        employees = self.env["employee3c.employee.base"].search(domain)
        if not employees:
            raise UserError(_("No employees match the selection."))
        created = self.env["payroll.payslip"]
        for emp in employees:
            # Avoid duplicate payslip for same employee in the same batch
            exists = created.search([('employee_id', '=', emp.id), ('run_id', '=', self.run_id.id)], limit=1)
            if exists:
                continue
            vals = {
                "employee_id": emp.id,
                "date_from": self.date_start,
                "date_to": self.date_end,
                "structure_id": self.structure_id.id if self.structure_id else False,
                "run_id": self.run_id.id,
            }
            created |= created.create(vals)
        action = self.env.ref("payroll_3c.action_payroll_payslips").read()[0]
        action["domain"] = [("id", "in", created.ids)]
        return action
