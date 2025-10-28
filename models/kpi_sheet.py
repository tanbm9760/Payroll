from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json


class PayrollKpiSheetLine(models.Model):
    _name = "payroll.kpi_sheet.line"
    _description = "Payroll KPI Sheet Line"
    _order = "id desc"

    sheet_id = fields.Many2one("payroll.kpi_sheet", required=True, ondelete="cascade")
    employee_id = fields.Many2one("employee3c.employee.base", string="Employee", required=True)
    total_score = fields.Float(string="Total KPI (%)", digits=(16, 4))
    details = fields.Json(string="Details")  # metrics dict: total_score + groups breakdown


class PayrollKpiSheet(models.Model):
    _name = "payroll.kpi_sheet"
    _description = "Payroll KPI Sheet (per payroll cycle)"
    _order = "id desc"

    name = fields.Char(required=True)
    run_id = fields.Many2one("payroll.payslip.run", string="Cycle", required=True, ondelete="cascade")
    period_id = fields.Many2one("payroll.kpi_period", string="KPI Period", required=True, ondelete="cascade")
    quality_profile_id = fields.Many2one(
        "payroll.kpi_quality_profile", string="Quality Profile", required=True, ondelete="restrict"
    )
    state = fields.Selection([
        ("draft", "Draft"),
        ("done", "Done"),
    ], default="draft")

    line_ids = fields.One2many("payroll.kpi_sheet.line", "sheet_id", string="Lines")

    @api.onchange("run_id")
    def _onchange_run_id_fill_name_and_period(self):
        for rec in self:
            if rec.run_id:
                rec.name = rec.run_id.name or rec.name
                # Derive or create period from run's date range
                d_from = getattr(rec.run_id, 'date_start', None) or getattr(rec.run_id, 'date_from', None)
                d_to = getattr(rec.run_id, 'date_end', None) or getattr(rec.run_id, 'date_to', None)
                if d_from and d_to:
                    Period = self.env['payroll.kpi_period']
                    period = Period.search([
                        ('date_start', '=', d_from),
                        ('date_end', '=', d_to),
                    ], limit=1)
                    if not period:
                        period = Period.create({
                            'name': f"KPI {d_from} - {d_to}",
                            'date_start': d_from,
                            'date_end': d_to,
                            'state': 'draft',
                        })
                    rec.period_id = period.id

    def _ensure_quality_profile(self):
        self.ensure_one()
        if self.quality_profile_id:
            return self.quality_profile_id
        prof = self.env['payroll.kpi_quality_profile'].search([('active', '=', True)], limit=1)
        if not prof:
            raise UserError(_("No KPI Quality Profile configured."))
        self.quality_profile_id = prof.id
        return prof

    def action_compute_kpi(self):
        """Compute KPI for all employees in the linked payroll cycle and persist records.
        - Aligns KPI period with the payroll run date range.
        - Uses selected quality profile (or first active).
        - Updates/creates kpi_sheet lines with totals and details JSON.
        """
        Engine = self.env['payroll.kpi_engine']
        Group = self.env['payroll.kpi_group']
        Label = self.env['payroll.kpi_label']

        for sheet in self:
            if not sheet.run_id:
                raise UserError(_("KPI Sheet must be linked to a Payroll Cycle."))
            # Ensure period from run dates
            d_from = getattr(sheet.run_id, 'date_start', None) or getattr(sheet.run_id, 'date_from', None)
            d_to = getattr(sheet.run_id, 'date_end', None) or getattr(sheet.run_id, 'date_to', None)
            if not (d_from and d_to):
                raise UserError(_("Payroll Cycle is missing date range."))

            # Ensure period exists
            period = sheet.period_id
            if not period:
                Period = self.env['payroll.kpi_period']
                period = Period.search([
                    ('date_start', '=', d_from),
                    ('date_end', '=', d_to),
                ], limit=1)
                if not period:
                    period = Period.create({
                        'name': f"KPI {d_from} - {d_to}",
                        'date_start': d_from,
                        'date_end': d_to,
                        'state': 'draft',
                    })
                sheet.period_id = period.id

            # Ensure quality profile
            qprof = sheet._ensure_quality_profile()

            # Scope of groups/labels
            groups = Group.search([('active', '=', True)])
            labels = Label.search([('active', '=', True)])

            # Employees from run
            employees = sheet.run_id.slip_ids.mapped('employee_id')
            if not employees:
                # Clear lines if no employees
                if sheet.line_ids:
                    sheet.line_ids.unlink()
                continue

            # Index existing lines by employee to update
            lines_by_emp = {l.employee_id.id: l for l in sheet.line_ids}
            keep_emp_ids = set()

            for emp in employees:
                counts = Engine.aggregate_employee_label_counts(emp, period, labels)
                metrics = Engine.compute_group_metrics(counts, qprof, groups)
                _records, total = Engine.upsert_kpi_records(emp, period, metrics)

                details = {
                    'total_score': total,
                    'groups': metrics.get('groups', {}),
                }

                if emp.id in lines_by_emp:
                    line = lines_by_emp[emp.id]
                    line.write({'total_score': total, 'details': details})
                else:
                    self.env['payroll.kpi_sheet.line'].create({
                        'sheet_id': sheet.id,
                        'employee_id': emp.id,
                        'total_score': total,
                        'details': details,
                    })
                keep_emp_ids.add(emp.id)

            # Remove lines for employees no longer in run
            lines_to_remove = sheet.line_ids.filtered(lambda l: l.employee_id.id not in keep_emp_ids)
            if lines_to_remove:
                lines_to_remove.unlink()

            sheet.state = 'done'
        return True
