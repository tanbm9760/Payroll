# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PayrollSalaryProfile(models.Model):
    _name = 'payroll.salary.profile'
    _description = 'Payroll Salary Profile'
    _order = 'employee_id'

    employee_id = fields.Many2one('employee3c.employee.base', string='Employee', required=True, ondelete='cascade', index=True)
    department_id = fields.Many2one('employee3c.department', string='Department', related='employee_id.department_id', store=True, index=True)
    employee_code = fields.Char(string='Employee Code', related='employee_id.employee_index', store=True, index=True)
    employee_avatar_html = fields.Html(string='Employee', related='employee_id.avatar_name_job', sanitize=False)
    base_wage = fields.Float(string='Base Wage')
    si_wage = fields.Float(string='Social Insurance Wage')
    dependent_count = fields.Integer(string='Dependents')
    note = fields.Char()

    _sql_constraints = [
        ('unique_employee', 'unique(employee_id)', 'Each employee can have only one salary profile.'),
    ]


class PayrollParams(models.Model):
    _inherit = 'payroll.vn.params'

    use_source = fields.Selection([
        ('employee', 'Use Employee Module'),
        ('payroll', 'Use Payroll Profiles'),
    ], string='Profile Source', default='employee', help='Choose where to read base wage, SI wage, dependents.')
