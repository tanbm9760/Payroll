from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PayrollKpiGroup(models.Model):
    _name = "payroll.kpi_group"
    _description = "KPI Group"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Short code like N1, N2 … used for payroll variables")
    weight = fields.Float(string="Group Weight (%)", default=0.0, help="Contribution percent of this group to total KPI score")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    label_ids = fields.One2many("payroll.kpi_label", "group_id", string="Labels")

    _sql_constraints = [
        ("kpi_group_code_uniq", "unique(code)", "KPI Group code must be unique"),
        ("kpi_group_weight_nonneg", "CHECK(weight >= 0)", "Weight must be >= 0"),
    ]


class PayrollKpiLabel(models.Model):
    _name = "payroll.kpi_label"
    _description = "KPI Label mapped to Project Tag"
    _order = "group_id, id"

    name = fields.Char(required=True)
    group_id = fields.Many2one("payroll.kpi_group", required=True, ondelete="cascade")
    tag_id = fields.Many2one("project3c.tag", string="Project Tag", required=True, ondelete="restrict")
    weight = fields.Float(string="Label Weight", default=1.0, help="Internal weight inside the group")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("kpi_label_weight_nonneg", "CHECK(weight >= 0)", "Weight must be >= 0"),
        ("kpi_label_unique", "unique(group_id, tag_id)", "Each tag can appear only once in a group"),
    ]


class PayrollKpiQualityProfile(models.Model):
    _name = "payroll.kpi_quality_profile"
    _description = "KPI Quality Coefficients"
    _order = "id"

    name = fields.Char(required=True)
    coef_ontime = fields.Float(string="On-time Coef", default=1.0)
    coef_late = fields.Float(string="Late Coef", default=0.5)
    coef_overdue = fields.Float(string="Overdue Coef", default=0.2)
    active = fields.Boolean(default=True)


class PayrollKpiPeriod(models.Model):
    _name = "payroll.kpi_period"
    _description = "KPI Period"
    _order = "date_start desc, id desc"

    name = fields.Char(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    state = fields.Selection([
        ("draft", "Draft"),
        ("computed", "Computed"),
        ("closed", "Closed"),
    ], default="draft", required=True)
    active = fields.Boolean(default=True)

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(_("Start date must be before or equal to End date"))


class PayrollKpiRecord(models.Model):
    _name = "payroll.kpi_record"
    _description = "KPI Result per Employee/Period/Group"
    _order = "period_id desc, employee_id, group_id"

    employee_id = fields.Many2one("employee3c.employee.base", string="Employee", required=True, ondelete="cascade")
    employee_user_id = fields.Many2one(related="employee_id.user_id", comodel_name="res.users", store=True, readonly=True)
    period_id = fields.Many2one("payroll.kpi_period", string="Period", required=True, ondelete="cascade")
    group_id = fields.Many2one("payroll.kpi_group", string="Group", required=True, ondelete="cascade")
    score = fields.Float(string="Score (%)", digits=(16, 4))
    details = fields.Json(string="Details")
    details_html = fields.Html(string="Details Table", compute="_compute_details_html", sanitize=False)

    _sql_constraints = [
        (
            "kpi_record_uniq",
            "unique(employee_id, period_id, group_id)",
            "One KPI record per Employee, Period and Group is allowed",
        ),
    ]

    def _compute_details_html(self):
        for rec in self:
            html = [
                '<div class="o_form_view">',
                '<table class="o_list_view table table-sm table-striped table-hover">',
                '<thead><tr>',
                '<th>Tên nhãn</th>',
                '<th>Tên tag</th>',
                '<th>Nhóm</th>',
                '<th>Công việc được giao</th>',
                '<th>Hoàn thành đúng hạn</th>',
                '<th>Hoàn thành muộn</th>',
                '<th>Quá hạn</th>',
                '<th>Trọng số</th>',
                '<th>Điểm KPI quy đổi (%)</th>',
                '</tr></thead><tbody>'
            ]

            details = rec.details or {}
            labels_info = details.get('labels') or []
            # Map label_id -> record for names and tag
            label_ids = [x.get('label_id') for x in labels_info if x.get('label_id')]
            label_map = {}
            if label_ids:
                Label = rec.env['payroll.kpi_label']
                for lab in Label.browse(label_ids).exists():
                    label_map[lab.id] = lab
            group_code = rec.group_id.code or (details.get('code') if isinstance(details, dict) else '') or ''

            # Build rows
            for row in labels_info:
                lab_id = row.get('label_id')
                lab = label_map.get(lab_id)
                label_name = lab.name if lab else str(lab_id or '')
                tag_name = lab.tag_id.name if (lab and lab.tag_id) else ''
                assigned = int(row.get('assigned') or 0)
                ontime = int(row.get('ontime') or 0)
                late = int(row.get('late') or 0)
                overdue = int(row.get('overdue') or 0)
                weight = float(row.get('weight') or 0.0)
                e_g = float(row.get('E_G') or 0.0)
                kpi_pct = (e_g / assigned * 100.0) if assigned else 0.0

                html.append('<tr>')
                html.append(f'<td>{label_name}</td>')
                html.append(f'<td>{tag_name}</td>')
                html.append(f'<td>{group_code}</td>')
                html.append(f'<td style="text-align:right">{assigned}</td>')
                html.append(f'<td style="text-align:right">{ontime}</td>')
                html.append(f'<td style="text-align:right">{late}</td>')
                html.append(f'<td style="text-align:right">{overdue}</td>')
                html.append(f'<td style="text-align:right">{weight:.2f}</td>')
                html.append(f'<td style="text-align:right">{kpi_pct:.2f}</td>')
                html.append('</tr>')

            html.append('</tbody></table></div>')
            rec.details_html = ''.join(html)
