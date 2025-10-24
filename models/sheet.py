# -*- coding: utf-8 -*-
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class PayrollSheetLine(models.Model):
    _name = "payroll.sheet.line"
    _description = "Payroll Sheet Line"
    _order = "id desc"

    sheet_id = fields.Many2one("payroll.sheet", required=True, ondelete="cascade")
    employee_id = fields.Many2one("employee3c.employee.base", string="Employee", required=True)

    # Liên kết tiện ích từ nhân sự để hiển thị trên lưới
    employee_calendar2_id = fields.Many2one(
        'employee3c.calendar2', string='Lịch làm việc',
        related='employee_id.calendar2_id', readonly=True, store=False)

    # JSON gốc
    values = fields.Text(string="Values")

    # Cột CỐ ĐỊNH (không cho sửa): không có inverse, readonly=True
    emp_code = fields.Char(string="Employee Code", compute="_compute_from_values", readonly=True, store=False)
    department_name = fields.Char(string="Department", compute="_compute_from_values", readonly=True, store=False)

    # Cột CHO PHÉP SỬA: có inverse, readonly=False
    work_day = fields.Float(string="Công chuẩn", compute="_compute_from_values",
                            inverse="_inv_work_day", readonly=False, store=False)
    points = fields.Float(string="Công thực tế", compute="_compute_from_values",
                          inverse="_inv_points", readonly=False, store=False)
    unpaid_lf_point = fields.Float(string="Unpaid Leave", compute="_compute_from_values",
                                   inverse="_inv_unpaid_lf_point", readonly=False, store=False)
    sum_late = fields.Integer(string="Sum Late", compute="_compute_from_values",
                              inverse="_inv_sum_late", readonly=False, store=False)

    other_values = fields.Text(string="Other Values", compute="_compute_from_values", store=False)

    @api.depends('values')
    def _compute_from_values(self):
        for rec in self:
            data = {}
            if rec.values:
                try:
                    data = json.loads(rec.values)
                except Exception:
                    _logger.warning("Invalid JSON in payroll.sheet.line %s", rec.id)
            # Mã nhân viên: chấp nhận nhiều khóa lịch sử để hiển thị ổn định
            rec.emp_code = (
                data.get('emp_code')
                or data.get('employee_code')
                or data.get('code')
                or data.get('emp_no')
                or data.get('employee_no')
                or data.get('employee_ref')
                or False
            )
            # Nếu JSON không có, fallback sang mã nhân sự chuẩn của employee_3c
            if not rec.emp_code and rec.employee_id:
                rec.emp_code = getattr(rec.employee_id, 'employee_index', '') or ''
            # chấp nhận cả 'department_name' và 'area_name'
            rec.department_name = data.get('department_name') or data.get('area_name') or False
            rec.work_day = float(data.get('work_day') or 0.0)
            rec.points = float(data.get('points') or 0.0)
            rec.unpaid_lf_point = float(data.get('unpaid_lf_point') or 0.0)
            rec.sum_late = int(data.get('sum_late') or 0)

            known = {'emp_code', 'department_name', 'area_name', 'work_day', 'points', 'unpaid_lf_point', 'sum_late'}
            extras = [f"{k}={v}" for k, v in sorted(data.items()) if k not in known]
            rec.other_values = ", ".join(extras) if extras else False

    # luôn merge 1 key và lấy values hiện tại từ DB để không mất các key khác
    def _json_merge(self, rec, key, value):
        if rec.id:
            current = rec.with_context(prefetch_fields=False).sudo().read(['values'])[0]['values']
        else:
            current = rec.values
        try:
            data = json.loads(current or "{}")
        except Exception:
            data = {}
        # nếu người dùng xoá để trống -> không xóa key cũ
        if value not in (None, False, ""):
            data[key] = value
        rec.values = json.dumps(data, ensure_ascii=False)

    # inverse chỉ cho các cột được sửa
    def _inv_work_day(self):
        for rec in self:
            self._json_merge(rec, 'work_day', float(rec.work_day or 0.0))

    def _inv_points(self):
        for rec in self:
            self._json_merge(rec, 'points', float(rec.points or 0.0))

    def _inv_unpaid_lf_point(self):
        for rec in self:
            self._json_merge(rec, 'unpaid_lf_point', float(rec.unpaid_lf_point or 0.0))

    def _inv_sum_late(self):
        for rec in self:
            self._json_merge(rec, 'sum_late', int(rec.sum_late or 0))

# Trong PayrollSheet.action_generate_lines, bảo đảm ghi các khóa cố định khi tạo/cập nhật dòng:
class PayrollSheet(models.Model):
    _name = "payroll.sheet"
    _description = "Payroll Sheet"
    _order = "year desc, month desc, id desc"

    name = fields.Char(required=True)
    run_id = fields.Many2one("payroll.payslip.run", string="Cycle", required=True, ondelete="cascade")
    template_id = fields.Many2one("payroll.template", string="Template", required=True)
    month = fields.Integer(string="Month", required=True)
    year = fields.Integer(string="Year", required=True)
    date_start = fields.Date(string="Date Start", required=True)
    date_end = fields.Date(string="Date End", required=True)
    line_ids = fields.One2many("payroll.sheet.line", "sheet_id", string="Lines")
    state = fields.Selection([
        ("draft", "Draft"),
        ("done", "Done"),
    ], default="draft")

    # Grid UI removed

    @api.model
    def _first_last_day(self, year, month):
        def _last_day(y, m):
            if m in (1, 3, 5, 7, 8, 10, 12):
                return 31
            if m in (4, 6, 9, 11):
                return 30
            # February
            leap = (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0))
            return 29 if leap else 28

        last_day = _last_day(int(year), int(month))
        # Build python date via fields.Date from string to avoid direct imports
        start = fields.Date.from_string(f"{int(year):04d}-{int(month):02d}-01")
        end = fields.Date.from_string(f"{int(year):04d}-{int(month):02d}-{last_day:02d}")
        return start, end

    def action_generate_lines(self):
        Variable = self.env["payroll.variable"]
        for sheet in self:
            # Only include employees that have payslips in the linked batch
            run = sheet.run_id
            employees = run.slip_ids.mapped("employee_id") if run else self.env["employee3c.employee.base"]
            # If no payslips, do nothing
            if not employees:
                _logger.info("[payroll.sheet] generate_lines skipped: no employees for sheet %s (run_id=%s)", sheet.id, getattr(run, 'id', None))
                continue
            # Build variable map for fast lookup
            vars_by_key = {v.payroll_key: v for v in Variable.search([("active", "=", True)])}
            # Prepare existing to avoid duplicates
            existing_lines_by_emp = {l.employee_id.id: l for l in sheet.line_ids}
            existing_emp_ids = set(existing_lines_by_emp.keys())
            target_emp_ids = set(employees.ids)
            # Remove lines for employees not in current payslips set
            lines_to_remove = sheet.line_ids.filtered(lambda l: l.employee_id.id not in target_emp_ids)
            if lines_to_remove:
                lines_to_remove.unlink()
            lines_to_create = []
            for emp in employees:
                new_values_json = sheet._resolve_values_for_employee(emp, vars_by_key)
                # Compute fixed keys safely
                emp_code = ''
                for a in ('employee_index', 'emp_code', 'code', 'employee_code', 'employee_ref', 'ref', 'identification_id'):
                    v = getattr(emp, a, None)
                    if v:
                        emp_code = v
                        break
                dept_name = (
                    getattr(emp, 'department_name', None)
                    or getattr(emp, 'area_name', None)
                    or getattr(getattr(emp, 'department_id', None), 'name', None)
                    or ''
                )

                if emp.id in existing_emp_ids:
                    # Merge new keys from template into existing values without overwriting existing keys
                    line = existing_lines_by_emp[emp.id]
                    try:
                        existing_data = json.loads(line.values or "{}")
                    except Exception:
                        existing_data = {}
                    try:
                        new_data = json.loads(new_values_json or "{}")
                    except Exception:
                        new_data = {}
                    changed = False
                    # Ensure fixed keys are set/updated
                    if existing_data.get('emp_code') != emp_code:
                        existing_data['emp_code'] = emp_code
                        changed = True
                    if existing_data.get('department_name') != dept_name:
                        existing_data['department_name'] = dept_name
                        changed = True
                    for k, v in new_data.items():
                        if k not in existing_data:
                            existing_data[k] = v
                            changed = True
                    if changed:
                        line.values = json.dumps(existing_data, ensure_ascii=False)
                else:
                    # Merge template values with fixed keys when creating
                    try:
                        base_data = json.loads(new_values_json or "{}")
                    except Exception:
                        base_data = {}
                    if emp_code:
                        base_data['emp_code'] = emp_code
                    if dept_name:
                        base_data['department_name'] = dept_name
                    lines_to_create.append((0, 0, {
                        "employee_id": emp.id,
                        "values": json.dumps(base_data, ensure_ascii=False),
                    }))
            if lines_to_create:
                sheet.write({"line_ids": lines_to_create})
        return True

    def action_sync_timesheet_points(self):
        """Pull final attendance data from timesheet_3c into this Payroll Sheet.
        - points: sum of shift_point (actual points, respects edits)
        - work_day: sum of standard_shift_point (expected points)
        Only updates these two keys in JSON, preserves other keys.
        """
        # Validate model availability
        try:
            TS = self.env['timesheet3c.sheet']
        except Exception:
            raise UserError(_("Module timesheet_3c is required to sync timesheet points."))

        for sheet in self:
            if sheet.state != 'draft':
                raise UserError(_("Chỉ có thể đồng bộ công khi sheet ở trạng thái Draft."))
            if not (sheet.date_start and sheet.date_end):
                raise UserError(_("Thiếu khoảng thời gian của Payroll Sheet."))

            d_from, d_to = sheet.date_start, sheet.date_end
            for line in sheet.line_ids:
                # Aggregate per employee over date range
                recs = TS.search([
                    ('employee_id', '=', line.employee_id.id),
                    ('date', '>=', d_from),
                    ('date', '<=', d_to),
                ])
                points_sum = 0.0
                workday_sum = 0.0
                for r in recs:
                    try:
                        points_sum += float(getattr(r, 'shift_point', 0.0) or 0.0)
                    except Exception:
                        pass
                    try:
                        workday_sum += float(getattr(r, 'standard_shift_point', 0.0) or 0.0)
                    except Exception:
                        pass
                # Merge into JSON
                try:
                    data = json.loads(line.values or '{}')
                except Exception:
                    data = {}
                data['points'] = points_sum
                data['work_day'] = workday_sum
                line.values = json.dumps(data, ensure_ascii=False)
        return True

    def action_open_timesheet_cycle(self):
        """Open the timesheet monthly cycle view filtered by this sheet's month/year."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Timesheet Cycle'),
            'res_model': 'timesheet3c.point.sum',
            'view_mode': 'tree,form',
            'domain': [('month', '=', self.month), ('year', '=', self.year)],
            'target': 'current',
        }

    def unlink(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError("Không thể xóa Payroll Sheet ở trạng thái Done.")
        return super().unlink()

    def _resolve_values_for_employee(self, employee, vars_by_key):
        """Resolve values for all variables for a given employee.
        Only 'auto' variables are fetched; 'formula' left blank for later computation.
        'input' left blank.
        """
        res = {}
        # Precompute timesheet aggregates when relevant
        def _aggregate_timesheet(emp, d_from, d_to):
            try:
                ts = self.env['timesheet3c.sheet']
            except Exception:
                return None
            recs = ts.search([
                ('employee_id', '=', emp.id),
                ('date', '>=', d_from),
                ('date', '<=', d_to),
            ])
            points_sum = 0.0
            workday_sum = 0.0
            for r in recs:
                # shift_point is actual point of the day (honors edits)
                points_sum += float(getattr(r, 'shift_point', 0.0) or 0.0)
                # standard_shift_point is expected point of the day
                workday_sum += float(getattr(r, 'standard_shift_point', 0.0) or 0.0)
            return {'points': points_sum, 'work_day': workday_sum}

        # For each variable in template columns only (faster)
        keys = set(self.template_id.column_ids.mapped("payroll_key"))
        # Prefer template columns; if none configured, fallback to all active variables
        if not keys:
            keys = set(k for k in vars_by_key.keys() if k)
        for key in keys:
            v = vars_by_key.get(key)
            if not v:
                continue
            if v.kind != "auto":
                res[key] = None
                continue
            # Parse system_key: model:field
            if not v.system_key or ":" not in v.system_key:
                res[key] = None
                continue
            model_name, field_name = v.system_key.split(":", 1)
            value = None
            try:
                if model_name == "employee3c.employee.base":
                    value = getattr(employee, field_name, None)
                elif model_name == "payroll.salary.profile":
                    prof = self.env['payroll.salary.profile'].search([
                        ("employee_id", "=", employee.id)
                    ], limit=1)
                    if prof:
                        value = getattr(prof, field_name, None)
                elif model_name in ("timesheet3c.monthly.sheet", "timesheet3c.sheet"):
                    # Support both monthly summary and per-day aggregation
                    value = None
                    if model_name == "timesheet3c.monthly.sheet":
                        try:
                            ts_model = self.env[model_name]
                            ts_rec = ts_model.search([
                                ("employee_id", "=", employee.id),
                                ("month", "=", self.month),
                                ("year", "=", self.year),
                            ], limit=1)
                            if ts_rec:
                                value = getattr(ts_rec, field_name, None)
                        except Exception:
                            value = None
                    # If not found or model not present, aggregate per-day sheets in date range
                    if value is None and self.date_start and self.date_end:
                        agg = _aggregate_timesheet(employee, self.date_start, self.date_end)
                        if agg and field_name in agg:
                            value = agg[field_name]
                else:
                    # Other sources not handled yet
                    value = None
            except Exception:
                value = None
            # Convert value to JSON-safe primitive based on variable data type
            res[key] = self._to_json_safe(value, v.data_type)
        return json.dumps(res, ensure_ascii=False)

    def _to_json_safe(self, value, data_type):
        """Convert Odoo values (recordsets, dates, decimals) to JSON-safe primitives.
        data_type is one of VAR_DTYPE: char, integer, float, date, boolean, monetary.
        """
        # None stays None
        if value is None:
            return None

        # Handle Odoo recordsets (many2one/one2many/many2many)
        if hasattr(value, "ids") and hasattr(value, "_name"):
            # Many2one: len == 1
            if len(value) <= 1:
                rec = value[0] if len(value) == 1 else None
                if not rec:
                    return None
                if data_type == "char":
                    # Use display_name for readability
                    return rec.display_name
                if data_type in ("integer",):
                    return rec.id
                if data_type in ("float", "monetary"):
                    # No numeric meaning; fallback to id
                    return float(rec.id)
                # Default: string name
                return rec.display_name
            # One2many/Many2many
            if data_type == "char":
                names = [r.display_name for r in value]
                return ", ".join(names)
            # Default: list of IDs
            return list(value.ids)

        # Booleans
        if isinstance(value, bool):
            return bool(value)

        # Decimals: rely on float() conversion in numeric branches below

        # Dates (fields.Date gives string in Odoo domains; but if python date, stringify)
        # Prefer Odoo helpers when possible
        # If value looks like datetime/date object with isoformat
        to_string = getattr(fields.Date, "to_string", None)
        if data_type == "date":
            # If already a string, return as-is
            if isinstance(value, str):
                return value
            try:
                if to_string:
                    return to_string(value)
            except Exception:
                pass
            # Fallback: try isoformat
            try:
                return value.isoformat()
            except Exception:
                return str(value)

        # Numbers
        if data_type in ("integer",):
            try:
                return int(value)
            except Exception:
                return 0
        if data_type in ("float", "monetary"):
            try:
                return float(value)
            except Exception:
                return 0.0

        # Everything else -> string for char
        if data_type == "char":
            return str(value)

    @api.model
    def get_grid_data(self, sheet_id):
        """Return dynamic columns from template and rows from sheet lines."""
        Sheet = self.env['payroll.sheet'].browse(sheet_id)
        if not Sheet.exists():
            return {}
        Sheet.check_access_rights('read')
        Sheet.check_access_rule('read')

        # Build columns from template
        tmpl = Sheet.template_id
        dynamic_cols = []
        if tmpl and hasattr(tmpl, 'column_ids'):
            cols = tmpl.column_ids.sorted(key=lambda c: getattr(c, 'sequence', 10))
            for c in cols:
                if hasattr(c, 'visible') and not c.visible:
                    continue
                key = getattr(c, 'payroll_key', None) or getattr(c, 'key', None) or getattr(c, 'system_key', None)
                if not key:
                    continue
                label = getattr(c, 'name', key) or key
                data_type = getattr(c, 'data_type', 'char') or 'char'
                dynamic_cols.append({'key': key, 'label': label, 'type': data_type})

        # Prepend Employee column
        columns = [{'key': '_employee', 'label': 'Employee', 'type': 'char'}, *dynamic_cols]

        # Build rows from sheet lines (values JSON)
        rows = []
        for line in Sheet.line_ids:
            try:
                vals = json.loads(line.values or '{}')
            except Exception:
                vals = {}
            row = {'_employee': line.employee_id.display_name}
            for col in columns:
                if col['key'] == '_employee':
                    continue
                key = col['key']
                v = vals.get(key)
                t = (col.get('type') or 'char').lower()
                try:
                    if v in (None, ''):
                        pass
                    elif t in ('integer',):
                        v = int(v)
                    elif t in ('float', 'monetary'):
                        v = float(v)
                    elif t in ('boolean',):
                        v = bool(v)
                    # char/date left as-is (strings)
                except Exception:
                    # leave original if cast fails
                    pass
                row[key] = v
            rows.append(row)

        return {
            'sheet': {'id': Sheet.id, 'name': Sheet.name, 'month': Sheet.month, 'year': Sheet.year},
            'columns': columns,
            'rows': rows,
        }
