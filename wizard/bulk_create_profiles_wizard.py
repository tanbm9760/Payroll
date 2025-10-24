# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PayrollBulkCreateProfilesWizard(models.TransientModel):
    _name = 'payroll.bulk.create.profiles.wizard'
    _description = 'Bulk Create Salary Profiles'

    department_id = fields.Many2one('employee3c.department', string='Department')
    include_has_profile = fields.Selection([
        ('all', 'All Employees'),
        ('only_missing', 'Only Employees without Profile'),
        ('only_existing', 'Only Employees with Profile'),
    ], default='only_missing', string='Selection')
    employee_ids = fields.Many2many(
        comodel_name='employee3c.employee.base',
        relation='payroll_prof_wiz_emp_rel',  # short to avoid 63-char limit
        column1='wizard_id',
        column2='employee_id',
        string='Employees'
    )

    @api.onchange('department_id')
    def _onchange_department(self):
        if self.department_id:
            return {'domain': {'employee_ids': [('department_id', '=', self.department_id.id)]}}
        return {'domain': {'employee_ids': []}}

    def _get_employees(self):
        domain = [('state', '!=', 'quit')]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.employee_ids:
            domain.append(('id', 'in', self.employee_ids.ids))
        employees = self.env['employee3c.employee.base'].search(domain)
        if self.include_has_profile == 'only_missing':
            prof_emp_ids = self.env['payroll.salary.profile'].search([]).mapped('employee_id').ids
            employees = employees.filtered(lambda e: e.id not in prof_emp_ids)
        elif self.include_has_profile == 'only_existing':
            prof_emp_ids = self.env['payroll.salary.profile'].search([]).mapped('employee_id').ids
            employees = employees.filtered(lambda e: e.id in prof_emp_ids)
        return employees

    def action_create_profiles(self):
        Profile = self.env['payroll.salary.profile']
        created = 0
        employees = self._get_employees()
        for emp in employees:
            existing = Profile.search([('employee_id', '=', emp.id)], limit=1)
            if existing:
                continue
            Profile.create({
                'employee_id': emp.id,
                'base_wage': getattr(emp, 'standard_salary', 0.0) or 0.0,
                'si_wage': getattr(emp, 'standard_salary', 0.0) or 0.0,
                'dependent_count': 0,
            })
            created += 1
        message = _('%s profiles created.') % created
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Create Profiles'),
                'message': message,
                'sticky': False,
                'type': 'success',
            }
        }
