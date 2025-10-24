# -*- coding: utf-8 -*-
{
    'name': 'Payroll 3C',
    'summary': 'Payroll 3C – scaffold with roles, menus, sequences',
    'version': '17.0.1.0.0',
    'author': '3C',
    'website': '',
    'category': 'payroll',
    'license': 'LGPL-3',
    'depends': ['base', 'Employee_3c'],  # use Employee_3c as employee source instead of hr
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        # Actions first to satisfy menu references
        'views/actions.xml',
    'data/sequence.xml',
    'data/vn_params_data.xml',
    'data/rule_structure_data.xml',
    'data/rule_updates.xml',
    'data/payslip_server_actions.xml',
    'data/refresh_variable_catalog_action.xml',
    'data/delete_actions.xml',
        'views/wizard_views.xml',
    'views/salary_profile_views.xml',
        'views/variable_views.xml',
        'views/template_views.xml',
        'views/sheet_views.xml',
        'views/rule_views.xml',
        'views/params_views.xml',
        'views/payslip_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'payroll_3c/static/src/scss/payroll_template.scss',
            'payroll_3c/static/src/scss/payroll_template_fix.scss',
        ],
    },
    'installable': True,
    'application': True,
    'images': ['static/description/icon.svg'],
}
