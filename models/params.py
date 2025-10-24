# -*- coding: utf-8 -*-
from odoo import fields, models


class PayrollVNParams(models.Model):
    _name = "payroll.vn.params"
    _description = "VN Payroll Parameters"

    name = fields.Char(default="Vietnam Payroll Parameters", required=True)
    personal_deduction = fields.Float(string="Personal deduction", default=11000000.0)
    dependent_deduction = fields.Float(string="Dependent deduction", default=4400000.0)
    union_fee_rate = fields.Float(string="Union fee (%)", default=1.0)
    bhxh_rate_emp = fields.Float(string="BHXH Employee %", default=8.0)
    bhxh_rate_cmp = fields.Float(string="BHXH Company %", default=17.5)
    bhyt_rate_emp = fields.Float(string="BHYT Employee %", default=1.5)
    bhyt_rate_cmp = fields.Float(string="BHYT Company %", default=3.0)
    bhtn_rate_emp = fields.Float(string="BHTN Employee %", default=1.0)
    bhtn_rate_cmp = fields.Float(string="BHTN Company %", default=1.0)

    _sql_constraints = [
        ("vn_params_singleton_name_unique", "unique(name)", "VN Parameters must be unique."),
    ]

    def action_open_singleton(self):
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': 'VN Parameters',
            'res_model': 'payroll.vn.params',
            'view_mode': 'form',
            'res_id': rec.id,
            'target': 'current',
        }

    def action_apply_vn_defaults(self):
        for rec in self:
            rec.write({
                'personal_deduction': 11000000.0,
                'dependent_deduction': 4400000.0,
                'union_fee_rate': 1.0,
                'bhxh_rate_emp': 8.0,
                'bhxh_rate_cmp': 17.5,
                'bhyt_rate_emp': 1.5,
                'bhyt_rate_cmp': 3.0,
                'bhtn_rate_emp': 1.0,
                'bhtn_rate_cmp': 1.0,
            })
        return True
