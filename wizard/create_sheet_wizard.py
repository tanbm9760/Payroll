# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PayrollCreateSheetWizard(models.TransientModel):
    _name = "payroll.create.sheet.wizard"
    _description = "Create Payroll Sheet Wizard"

    run_id = fields.Many2one("payroll.payslip.run", required=True, readonly=True)
    template_id = fields.Many2one("payroll.template", string="Template", required=True)
    sheet_name = fields.Char(string="Sheet Name", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if not res.get("run_id") and self.env.context.get("active_model") == "payroll.payslip.run":
            res["run_id"] = self.env.context.get("active_id")
        if not res.get("sheet_name") and res.get("run_id"):
            run = self.env["payroll.payslip.run"].browse(res["run_id"]) if res.get("run_id") else False
            if run and run.month and run.year:
                res["sheet_name"] = f"Payroll Sheet {run.month:02d}/{run.year}"
        return res

    def action_create(self):
        self.ensure_one()
        run = self.run_id
        vals = {
            "name": self.sheet_name,
            "run_id": run.id,
            "template_id": self.template_id.id,
            "month": run.month or 0,
            "year": run.year or 0,
            "date_start": run.date_start,
            "date_end": run.date_end,
        }
        sheet = self.env["payroll.sheet"].create(vals)
        sheet.action_generate_lines()
        return {
            "type": "ir.actions.act_window",
            "name": sheet.name,
            "res_model": "payroll.sheet",
            "res_id": sheet.id,
            "view_mode": "form",
            "target": "current",
        }
