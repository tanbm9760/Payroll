# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from .variable import VAR_KIND, VAR_DTYPE


class PayrollTemplate(models.Model):
    _name = "payroll.template"
    _description = "Payroll Sheet Template"
    _order = "name"

    name = fields.Char(required=True)
    column_ids = fields.One2many("payroll.template.column", "template_id", string="Cột")
    note = fields.Text()
    # Quick-pick variables panel on the right
    variable_select_ids = fields.Many2many(
        "payroll.variable",
        string="Chọn nhanh biến",
        help="Chọn các biến từ Catalog để thêm nhanh vào template.")
    # Helper list to show all active variables in embedded list view
    variable_helper_ids = fields.Many2many(
        "payroll.variable",
        string="Biến hệ thống",
        compute="_compute_variable_helper_ids",
        store=False,
        help="Danh sách tất cả biến đang hoạt động để chọn nhanh.")

    def action_open_variables(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Variable Catalog",
            "res_model": "payroll.variable",
            "view_mode": "tree,form",
            "target": "current",
        }

    def action_autofill_from_catalog(self):
        """Thêm cột dựa trên toàn bộ catalog (bỏ qua cột đã có cùng payroll_key)."""
        Variable = self.env["payroll.variable"]
        for template in self:
            existing_keys = set(template.column_ids.mapped("payroll_key"))
            todo = Variable.search([("active", "=", True)])
            new_lines = []
            for v in todo:
                if v.payroll_key in existing_keys:
                    continue
                new_lines.append((0, 0, {
                    "sequence": 999,
                    "variable_id": v.id,
                    "display_name": v.name,
                    "system_key": v.system_key,
                    "payroll_key": v.payroll_key,
                    "var_type": v.kind,
                    "data_type": v.data_type,
                    "definition": v.definition,
                    "description": v.description,
                }))
            if new_lines:
                template.write({"column_ids": new_lines})
        return True

    def action_add_selected_variables(self):
        """Thêm các biến đã chọn ở panel bên phải vào cột của template."""
        for template in self:
            if not template.variable_select_ids:
                continue
            existing_keys = set(template.column_ids.mapped("payroll_key"))
            new_lines = []
            for v in template.variable_select_ids:
                if not v.active:
                    continue
                if v.payroll_key in existing_keys:
                    continue
                new_lines.append((0, 0, {
                    "sequence": 999,
                    "variable_id": v.id,
                    "display_name": v.name,
                    "system_key": v.system_key,
                    "payroll_key": v.payroll_key,
                    "var_type": v.kind,
                    "data_type": v.data_type,
                    "definition": v.definition,
                    "description": v.description,
                }))
            if new_lines:
                template.write({"column_ids": new_lines})
            # Optional: clear selections after adding
            template.variable_select_ids = [(5, 0, 0)]
        return True

    def _compute_variable_helper_ids(self):
        Variable = self.env["payroll.variable"]
        all_vars = Variable.search([("active", "=", True)], order="category, name")
        for rec in self:
            rec.variable_helper_ids = [(6, 0, all_vars.ids)]


class PayrollTemplateColumn(models.Model):
    _name = "payroll.template.column"
    _description = "Payroll Template Column"
    _order = "sequence, id"

    template_id = fields.Many2one("payroll.template", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    variable_id = fields.Many2one("payroll.variable", string="Biến")
    display_name = fields.Char("Tên hiển thị")
    system_key = fields.Char("ID hệ thống", required=True)
    payroll_key = fields.Char("ID", required=True, index=True)
    var_type = fields.Selection(VAR_KIND, string="Loại", required=True)
    data_type = fields.Selection(VAR_DTYPE, string="Loại dữ liệu", required=True)
    definition = fields.Text("Định nghĩa")
    description = fields.Char("Miêu tả")
    visible = fields.Boolean("Hiển thị", default=True)

    _sql_constraints = [
        ("unique_key_per_template", "unique(template_id, payroll_key)", "ID trong template phải duy nhất."),
    ]

    @api.onchange("variable_id")
    def _onchange_variable_id(self):
        v = self.variable_id
        if v:
            self.display_name = v.name
            self.system_key = v.system_key
            self.payroll_key = v.payroll_key
            self.var_type = v.kind
            self.data_type = v.data_type
            self.definition = v.definition
            self.description = v.description

    @api.constrains("var_type", "definition")
    def _check_column_formula_definition(self):
        for rec in self:
            if rec.var_type == "formula" and not (rec.definition and rec.definition.strip()):
                raise ValidationError("Cột có Loại 'Công thức' bắt buộc phải nhập Định nghĩa (công thức).")
