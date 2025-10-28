# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

ADJ_KIND = [
    ("add", "Cộng"),
    ("sub", "Trừ"),
]

ADJ_SOURCE = [
    ("manual", "Nhập tay"),
    ("auto", "Tự động"),
]

class PayrollKpiAdjustRule(models.Model):
    _name = "payroll.kpi_adjust_rule"
    _description = "KPI Adjustment Rule"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection(ADJ_KIND, default="add", required=True)
    points_per_occurrence = fields.Float(string="Điểm mỗi lần (%)", required=True, default=0.0)
    source_type = fields.Selection(ADJ_SOURCE, default="manual", required=True)
    # For auto rules: retrieve occurrences from variable catalog key
    variable_key = fields.Char(string="Biến tự động", help="Khóa trong Variable Catalog (vd: sum_late)")
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_unique", "unique(code)", "Mã quy tắc phải là duy nhất!"),
    ]

class PayrollKpiAdjustRecord(models.Model):
    _name = "payroll.kpi_adjust_record"
    _description = "KPI Adjustment Record"
    _order = "period_id desc, id desc"

    employee_id = fields.Many2one("employee3c.employee.base", required=True, index=True)
    employee_user_id = fields.Many2one("res.users", related="employee_id.user_id", store=True, readonly=True)
    period_id = fields.Many2one("payroll.kpi_period", required=True, index=True)
    payslip_id = fields.Many2one("payroll.payslip", string="Payslip", index=True, ondelete="cascade")
    rule_id = fields.Many2one("payroll.kpi_adjust_rule", required=True)
    kind = fields.Selection(ADJ_KIND, related="rule_id.kind", store=True, readonly=True)
    source_type = fields.Selection(ADJ_SOURCE, related="rule_id.source_type", store=True, readonly=True)
    points_per_occurrence = fields.Float(related="rule_id.points_per_occurrence", store=False)
    occurrences = fields.Integer(string="Số lần", default=0)
    total_points = fields.Float(string="Điểm quy đổi (%)", compute="_compute_total_points", store=True)
    note = fields.Char(string="Ghi chú")

    @api.depends("occurrences", "rule_id.points_per_occurrence")
    def _compute_total_points(self):
        for rec in self:
            try:
                rec.total_points = float(rec.occurrences or 0) * float(rec.rule_id.points_per_occurrence or 0.0)
            except Exception:
                rec.total_points = 0.0

    # --- Utilities ---
    @api.model
    def sync_auto_for_employee_period(self, employee, period, payslip=None):
        """Upsert auto adjustment records for employee & period based on rules with variable_key.
        occurrences = int(value) where value is fetched from Variable Catalog for the period.
        """
        if not employee or not period:
            return self.browse()
        Rule = self.env["payroll.kpi_adjust_rule"].sudo()
        rules = Rule.search([("active", "=", True), ("source_type", "=", "auto"), ("variable_key", "!=", False)])
        if not rules:
            return self.browse()
        # Use variable catalog to compute aggregates from sources
        var_keys = set(rules.mapped("variable_key"))
        try:
            var_map = self.env['payroll.variable'].compute_values_for_employee(
                employee, period.date_start, period.date_end, keys=var_keys)
        except Exception:
            var_map = {}
        recs = self.browse()
        for r in rules:
            raw = var_map.get(r.variable_key)
            try:
                occ = int(float(raw or 0))
            except Exception:
                occ = 0
            # Upsert record
            domain = [
                ("employee_id", "=", employee.id),
                ("period_id", "=", period.id),
                ("rule_id", "=", r.id),
            ]
            if payslip:
                domain.append(("payslip_id", "=", payslip.id))
            existing = self.search(domain, limit=1)
            vals = {
                "employee_id": employee.id,
                "period_id": period.id,
                "payslip_id": payslip.id if payslip else False,
                "rule_id": r.id,
                "occurrences": occ,
            }
            if existing:
                existing.write(vals)
                recs |= existing
            else:
                recs |= self.create(vals)
        return recs
