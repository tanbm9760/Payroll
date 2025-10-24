# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PayrollCategory(models.Model):
    _name = "payroll.category"
    _description = "Payroll Category"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    parent_id = fields.Many2one("payroll.category", string="Parent")
    type = fields.Selection(
        [("earn", "Earning"), ("ded", "Deduction"), ("contrib", "Contribution")],
        default="earn",
        required=True,
    )


class PayrollRule(models.Model):
    _name = "payroll.rule"
    _description = "Salary Rule"

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Unique code used in formulas")
    sequence = fields.Integer(default=100)
    category_id = fields.Many2one("payroll.category", required=True)
    active = fields.Boolean(default=True)

    # Minimal formula fields (extend later in Step 4)
    condition = fields.Selection([("always", "Always"), ("python", "Python")], default="always")
    condition_python = fields.Text(default="result = True")
    amount_type = fields.Selection([("fixed", "Fixed"), ("percent", "Percent"), ("python", "Python")], default="fixed")
    amount_fix = fields.Float()
    amount_percent = fields.Float(help="Percent of base amount")
    amount_base_code = fields.Char(help="Rule code used as base for percent")
    amount_python = fields.Text(default="result = 0.0")


class PayrollStructure(models.Model):
    _name = "payroll.structure"
    _description = "Salary Structure"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    rule_ids = fields.Many2many("payroll.rule", string="Salary Rules", relation="payroll_structure_rule_rel")

    # Seed/reset a standard set of VN payroll rules with Python formulas
    def action_load_vn_defaults(self):
        Cat = self.env['payroll.category']
        Rule = self.env['payroll.rule']

        # Ensure categories
        earn = Cat.search([('code', '=', 'EARN')], limit=1)
        if not earn:
            earn = Cat.create({'name': 'Earning', 'code': 'EARN', 'type': 'earn'})
        ded = Cat.search([('code', '=', 'DED')], limit=1)
        if not ded:
            ded = Cat.create({'name': 'Deduction', 'code': 'DED', 'type': 'ded'})
        contrib = Cat.search([('code', '=', 'CONTRIB')], limit=1)
        if not contrib:
            contrib = Cat.create({'name': 'Contribution', 'code': 'CONTRIB', 'type': 'contrib'})

        def upsert(code, name, seq, category, amount_py='result = 0.0'):
            rec = Rule.search([('code', '=', code)], limit=1)
            vals = {
                'name': name,
                'code': code,
                'sequence': seq,
                'category_id': category.id,
                'active': True,
                'condition': 'always',
                'condition_python': 'result = True',
                'amount_type': 'python',
                'amount_python': amount_py,
            }
            if rec:
                rec.write(vals)
                return rec.id
            return Rule.create(vals).id

        # Python formulas
        PY_BASIC_BASE = """
result = float(V.get('base_wage', 0.0) or 0.0)
"""
        PY_SI_BASE = """
result = float(V.get('si_wage', 0.0) or (get_code('BASIC_BASE') or 0.0))
"""
        PY_WORK_DAY = """
result = float(V.get('work_day', V.get('work_day_from_sheet', 0.0)) or 0.0)
"""
        PY_POINTS = """
result = float(V.get('points', V.get('points_from_sheet', 0.0)) or 0.0)
"""
        PY_BASIC = """
base = get_code('BASIC_BASE') or 0.0
wd = get_code('WORK_DAY') or float(V.get('work_day', 0.0) or 0.0)
pt = get_code('POINTS') or float(V.get('points', 0.0) or 0.0)
result = base * (pt / wd) if wd else 0.0
"""
        PY_ALLOW = """
result = 0.0
"""
        PY_INS_EMP = """
p = env['payroll.vn.params'].search([], limit=1)
si_rate = (float(getattr(p,'bhxh_rate_emp', 8.0) or 0.0) + float(getattr(p,'bhyt_rate_emp', 1.5) or 0.0) + float(getattr(p,'bhtn_rate_emp', 1.0) or 0.0)) / 100.0
base = get_code('SI_BASE') or 0.0
result = - round(base * si_rate, 2)
"""
        PY_INS_CMP = """
p = env['payroll.vn.params'].search([], limit=1)
cmp_rate = (float(getattr(p,'bhxh_rate_cmp', 17.5) or 0.0) + float(getattr(p,'bhyt_rate_cmp', 3.0) or 0.0) + float(getattr(p,'bhtn_rate_cmp', 1.0) or 0.0)) / 100.0
base = get_code('SI_BASE') or 0.0
result = round(base * cmp_rate, 2)
"""
        PY_UNION = """
p = env['payroll.vn.params'].search([], limit=1)
rate = float(getattr(p,'union_fee_rate', 1.0) or 0.0) / 100.0
gross = (get_code('BASIC') or 0.0) + (get_code('ALLOW') or 0.0)
result = - round(gross * rate, 2)
"""
        PY_PIT = """
# taxable income = gross - employee SI parts - deductions
p = env['payroll.vn.params'].search([], limit=1)
personal = float(getattr(p,'personal_deduction', 11000000.0) or 0.0)
dep_ded = float(getattr(p,'dependent_deduction', 4400000.0) or 0.0)
dep = int(V.get('dependent_count', 0) or 0)
gross = (get_code('BASIC') or 0.0) + (get_code('ALLOW') or 0.0)
si_nv = - (get_code('INS_EMP') or 0.0)  # make positive
taxable = gross - si_nv - personal - dep * dep_ded
if taxable < 0:
    taxable = 0.0
t = taxable
tax = 0.0
br = [
    (5000000.0, 0.05),
    (10000000.0, 0.10),
    (18000000.0, 0.15),
    (32000000.0, 0.20),
    (52000000.0, 0.25),
    (80000000.0, 0.30),
]
prev = 0.0
for cap, rate in br:
    if t > cap:
        tax += (cap - prev) * rate
        prev = cap
    else:
        tax += (t - prev) * rate
        prev = t
        break
if t > 80000000.0:
    tax += (t - prev) * 0.35
result = - round(tax, 2)
"""
        PY_NET = """
result = round((get_code('BASIC') or 0.0) + (get_code('ALLOW') or 0.0) + (get_code('INS_EMP') or 0.0) + (get_code('UNION') or 0.0) + (get_code('PIT') or 0.0), 2)
"""

        for st in self:
            ids = []
            ids.append(upsert('BASIC_BASE', 'Lương cơ bản', 1, earn, PY_BASIC_BASE))
            ids.append(upsert('SI_BASE', 'Lương đóng BHXH', 2, earn, PY_SI_BASE))
            ids.append(upsert('WORK_DAY', 'Công chuẩn', 3, earn, PY_WORK_DAY))
            ids.append(upsert('POINTS', 'Công thực tế', 4, earn, PY_POINTS))
            ids.append(upsert('BASIC', 'Lương theo công thực tế', 10, earn, PY_BASIC))
            ids.append(upsert('ALLOW', 'Phụ cấp', 20, earn, PY_ALLOW))
            ids.append(upsert('INS_EMP', 'Bảo hiểm (Nhân viên)', 30, ded, PY_INS_EMP))
            ids.append(upsert('INS_CMP', 'Bảo hiểm (Công ty)', 40, contrib, PY_INS_CMP))
            ids.append(upsert('UNION', 'Union Fee', 50, ded, PY_UNION))
            ids.append(upsert('PIT', 'Thuế thu nhập cá nhân', 60, ded, PY_PIT))
            ids.append(upsert('NET', 'Lương NET', 80, earn, PY_NET))
            # Attach to structure (replace set)
            st.write({'rule_ids': [(6, 0, ids)]})
        return True
