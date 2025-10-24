# -*- coding: utf-8 -*-
import json
from odoo import api, fields, models
from odoo.exceptions import ValidationError

VAR_KIND = [
    ("auto", "Tự động"),
    ("formula", "Công thức"),
    ("input", "Nhập ngoài"),
]

VAR_DTYPE = [
    ("char", "Văn bản"),
    ("integer", "Số nguyên"),
    ("float", "Số"),
    ("date", "Ngày"),
    ("boolean", "Đúng/Sai"),
    ("monetary", "Tiền"),
]

VAR_CATEGORY = [
    ("hr", "Thông tin nhân sự"),
    ("salary", "Thông tin lương"),
    ("tax", "Thông tin thuế"),
    ("insurance", "Thông tin bảo hiểm"),
    ("timesheet", "Thông tin công"),
]


class PayrollVariable(models.Model):
    _name = "payroll.variable"
    _description = "Payroll Variable Catalog"
    _order = "category, name"

    name = fields.Char("Tên biến", required=True)
    category = fields.Selection(VAR_CATEGORY, string="Nhóm", required=True, index=True)
    system_key = fields.Char("ID hệ thống", help="ID gốc của module nguồn (vd: employee3c.employee.base:tax_code)")
    payroll_key = fields.Char("ID", required=True, help="ID dùng trong module payroll (vd: mst_ca_nhan, work_day)")
    kind = fields.Selection(VAR_KIND, string="Loại", default="auto", required=True)
    data_type = fields.Selection(VAR_DTYPE, string="Loại dữ liệu", default="char", required=True)
    definition = fields.Text("Định nghĩa", help="Công thức hoặc mô tả cách tính", translate=True)
    description = fields.Char("Miêu tả", translate=True)
    source_module = fields.Char("Nguồn", help="Tên module cung cấp (Employee_3c / Timesheet_3c / Payroll_3c)", index=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("payroll_key_unique", "unique(payroll_key)", "ID (payroll_key) phải là duy nhất!"),
    ]

    @api.constrains("kind", "definition")
    def _check_formula_definition(self):
        for rec in self:
            if rec.kind == "formula" and not (rec.definition and rec.definition.strip()):
                raise ValidationError("Biến loại 'Công thức' bắt buộc phải nhập Định nghĩa (công thức).")

    @api.model
    def action_refresh_catalog(self):
        """Nạp/đồng bộ biến từ các nguồn chuẩn. Idempotent: update nếu tồn tại, tạo mới nếu chưa có."""
        defs = []

        # Employee_3c & Payroll_3c — cấu hình mặc định theo ảnh người dùng cung cấp
        defs += [
            # Nhân sự
            {"name": "Mã nhân viên", "category": "hr", "system_key": "employee3c.employee.base:employee_index",
             "payroll_key": "employee_index", "kind": "auto", "data_type": "char", "source_module": "Employee_3c"},
            {"name": "Tên phòng ban", "category": "hr", "system_key": "employee3c.employee.base:department_id",
             "payroll_key": "department_id", "kind": "auto", "data_type": "char", "source_module": "Employee_3c",
             "description": "Tên Phòng ban"},
            # Lương & bảo hiểm lấy từ hồ sơ lương (Payroll_3c)
            {"name": "Lương cơ bản", "category": "salary", "system_key": "payroll.salary.profile:base_wage",
             "payroll_key": "base_wage", "kind": "auto", "data_type": "monetary", "source_module": "Payroll_3c"},
            {"name": "Lương đóng BHXH", "category": "insurance", "system_key": "payroll.salary.profile:si_wage",
             "payroll_key": "si_wage", "kind": "auto", "data_type": "monetary", "source_module": "Payroll_3c"},
            {"name": "Số người phụ thuộc", "category": "tax", "system_key": "payroll.salary.profile:dependent_count",
             "payroll_key": "dependent_count", "kind": "auto", "data_type": "integer", "source_module": "Employee_3c"},
        ]

        # Payroll_3c — biến lương nội bộ bổ sung (tuỳ chọn)
        defs += [
            {"name": "Kiểu lương (Gross/Net)", "category": "salary", "system_key": "payroll.employee.profile:wage_type",
             "payroll_key": "wage_type", "kind": "auto", "data_type": "char", "source_module": "Payroll_3c"},
            {"name": "Phụ cấp ăn trưa", "category": "salary", "system_key": "payroll.employee.allowance:lunch",
             "payroll_key": "allow_lunch", "kind": "auto", "data_type": "monetary", "source_module": "Payroll_3c"},
        ]

        # Timesheet_3c — thông tin công (ví dụ từ ảnh: work_day, points, nghỉ, OT…)
        defs += [
            {"name": "Công chuẩn", "category": "timesheet", "system_key": "timesheet3c.monthly.sheet:work_day",
             "payroll_key": "work_day", "kind": "auto", "data_type": "float", "source_module": "Timesheet_3c",
             "description": "Số công chuẩn trong kỳ (standard_shift_point)"},
            {"name": "Công thực tế", "category": "timesheet", "system_key": "timesheet3c.monthly.sheet:points",
             "payroll_key": "points", "kind": "auto", "data_type": "float", "source_module": "Timesheet_3c",
             "description": "Số công thực tế (shift_point)"},
            {"name": "Nghỉ không lương (ngày)", "category": "timesheet", "system_key": "timesheet3c.monthly.sheet:unpaid_leave_day",
             "payroll_key": "unpaid_lf_point", "kind": "auto", "data_type": "float", "source_module": "Timesheet_3c"},
            {"name": "Số lần đi muộn", "category": "timesheet", "system_key": "timesheet3c.monthly.sheet:sum_late",
             "payroll_key": "sum_late", "kind": "auto", "data_type": "integer", "source_module": "Timesheet_3c"},
        ]

        for d in defs:
            rec = self.search([("payroll_key", "=", d["payroll_key"])], limit=1)
            if rec:
                rec.write(d)
            else:
                self.create(d)
        # Sau khi nạp danh mục cơ bản, tự động sinh biến _id cho các trường quan hệ (many2one)
        self._action_normalize_many2one_id_variants()
        return True

    # ============== Chuẩn hoá biến: sinh biến _id cho many2one ==============
    def _get_field_type(self, model_name, field_name):
        try:
            model = self.env[model_name]
            fld = model._fields.get(field_name)
            return getattr(fld, 'type', None)
        except Exception:
            return None

    def _ensure_id_variant(self, var_rec):
        """Nếu biến trỏ tới trường many2one, đảm bảo có biến bổ sung dạng *_id (data_type=integer)."""
        if not (var_rec.system_key and ":" in var_rec.system_key):
            return
        model_name, field_name = var_rec.system_key.split(":", 1)
        ftype = self._get_field_type(model_name, field_name)
        if ftype != 'many2one':
            return
        # Xác định payroll_key cho biến id: ưu tiên <payroll_key>_id nếu chưa kết thúc bằng _id
        base_key = var_rec.payroll_key or field_name
        id_key = base_key if base_key.endswith('_id') else f"{base_key}_id"
        # Nếu đã tồn tại, bỏ qua
        exists = self.search([("payroll_key", "=", id_key)], limit=1)
        if exists:
            return
        # Tạo biến *_id
        self.create({
            'name': f"{var_rec.name} (ID)",
            'category': var_rec.category,
            'system_key': var_rec.system_key,
            'payroll_key': id_key,
            'kind': var_rec.kind,
            'data_type': 'integer',
            'definition': var_rec.definition,
            'description': (var_rec.description or '') + ' [ID variant]',
            'source_module': var_rec.source_module,
            'active': var_rec.active,
        })

    def _action_normalize_many2one_id_variants(self):
        """Quét toàn bộ danh mục biến và sinh biến *_id cho các trường many2one nếu chưa có.
        Mục tiêu: công thức Salary Rule có thể dùng ID thay vì tên.
        """
        for var_rec in self.search([]):
            self._ensure_id_variant(var_rec)

    # ============== Tính giá trị biến theo nhân sự & khoảng thời gian ==============
    def _to_primitive(self, value, data_type):
        """Chuyển giá trị Odoo thành kiểu nguyên thuỷ dùng trong công thức theo data_type."""
        if value is None:
            return None
        # recordset
        if hasattr(value, 'ids') and hasattr(value, '_name'):
            if len(value) <= 1:
                rec = value[0] if len(value) == 1 else None
                if not rec:
                    return None
                if data_type == 'integer':
                    return rec.id
                if data_type in ('float', 'monetary'):
                    try:
                        return float(rec.id)
                    except Exception:
                        return 0.0
                # char/date/boolean -> tên hiển thị
                return rec.display_name
            # Nhiều bản ghi
            if data_type == 'char':
                return ", ".join(r.display_name for r in value)
            return list(value.ids)
        # nguyên thuỷ
        if data_type == 'integer':
            try:
                return int(value)
            except Exception:
                return 0
        if data_type in ('float', 'monetary'):
            try:
                return float(value)
            except Exception:
                return 0.0
        if data_type == 'boolean':
            return bool(value)
        if data_type == 'date':
            if isinstance(value, str):
                return value
            to_string = getattr(fields.Date, 'to_string', None)
            try:
                return to_string(value) if to_string else value.isoformat()
            except Exception:
                return str(value)
        # char / default
        return str(value)

    def compute_values_for_employee(self, employee, date_from=None, date_to=None, keys=None):
        """Trả về dict {payroll_key: value} theo catalog biến (kind=auto) cho 1 nhân sự.
        - Hỗ trợ model nguồn: employee3c.employee.base, payroll.salary.profile, timesheet3c.*
        - Hỗ trợ lấy trực tiếp từ Payroll Sheet sau khi đồng bộ công: payroll.sheet.line:<field>
        - Với many2one, nếu data_type=integer sẽ trả về id; nếu char sẽ trả về tên.
        """
        res = {}
        # Chuẩn bị nhanh: lấy biến theo keys (nếu có)
        domain = [('kind', '=', 'auto')]
        if keys:
            domain.append(('payroll_key', 'in', list(keys)))
        vars_q = self.search(domain)

        # Trợ giúp: tổng hợp timesheet theo ngày
        def _aggregate_timesheet(emp, d_from, d_to):
            try:
                ts = self.env['timesheet3c.sheet']
            except Exception:
                return None
            if not (d_from and d_to):
                return None
            recs = ts.search([
                ('employee_id', '=', emp.id),
                ('date', '>=', d_from),
                ('date', '<=', d_to),
            ])
            points_sum = 0.0
            workday_sum = 0.0
            unpaid = 0.0
            sum_late = 0
            for r in recs:
                points_sum += float(getattr(r, 'shift_point', 0.0) or 0.0)
                workday_sum += float(getattr(r, 'standard_shift_point', 0.0) or 0.0)
                unpaid += float(getattr(r, 'unpaid_leave_day', 0.0) or 0.0)
                try:
                    sum_late += int(getattr(r, 'sum_late', 0) or 0)
                except Exception:
                    pass
            return {
                'points': points_sum,
                'work_day': workday_sum,
                'unpaid_lf_point': unpaid,
                'sum_late': sum_late,
            }

        for v in vars_q:
            value = None
            if not (v.system_key and ':' in v.system_key):
                continue
            model_name, field_name = v.system_key.split(':', 1)
            try:
                if model_name == 'employee3c.employee.base':
                    value = getattr(employee, field_name, None)
                elif model_name == 'payroll.salary.profile':
                    prof = self.env['payroll.salary.profile'].search([
                        ('employee_id', '=', employee.id)
                    ], limit=1)
                    if prof:
                        value = getattr(prof, field_name, None)
                elif model_name == 'payroll.sheet.line':
                    # Lấy giá trị trực tiếp từ Payroll Sheet Line (JSON values) để phản ánh số liệu sau sync
                    ctx = dict(self.env.context or {})
                    SheetLine = self.env['payroll.sheet.line']
                    domain_sl = [('employee_id', '=', employee.id)]
                    sheet_id = ctx.get('sheet_id')
                    run_id = ctx.get('run_id')
                    if sheet_id:
                        domain_sl.append(('sheet_id', '=', sheet_id))
                    elif run_id:
                        domain_sl.append(('sheet_id.run_id', '=', run_id))
                    else:
                        # Fallback: tìm sheet theo tháng/năm của date_from
                        try:
                            if date_from:
                                dt = fields.Date.from_string(date_from)
                                Sheet = self.env['payroll.sheet']
                                sh = Sheet.search([('month', '=', dt.month), ('year', '=', dt.year)], limit=1)
                                if sh:
                                    domain_sl.append(('sheet_id', '=', sh.id))
                        except Exception:
                            pass
                    line = SheetLine.search(domain_sl, limit=1)
                    if line:
                        try:
                            data_json = line.values or '{}'
                            data = json.loads(data_json)
                            value = data.get(field_name)
                        except Exception:
                            value = None
                elif model_name in ('timesheet3c.monthly.sheet', 'timesheet3c.sheet'):
                    # Ưu tiên monthly nếu có, nếu không tổng hợp từ bản ghi ngày
                    if model_name == 'timesheet3c.monthly.sheet':
                        try:
                            ts_model = self.env[model_name]
                            ts_rec = ts_model.search([
                                ('employee_id', '=', employee.id),
                                ('month', '=', date_from and fields.Date.from_string(date_from).month or 0),
                                ('year', '=', date_from and fields.Date.from_string(date_from).year or 0),
                            ], limit=1)
                            if ts_rec:
                                value = getattr(ts_rec, field_name, None)
                        except Exception:
                            value = None
                    if value is None:
                        agg = _aggregate_timesheet(employee, date_from, date_to)
                        if agg and field_name in agg:
                            value = agg[field_name]
                else:
                    value = None
            except Exception:
                value = None
            res[v.payroll_key] = self._to_primitive(value, v.data_type)
        return res

    def action_add_to_template(self):
        """Add this variable as a column into the active payroll template.
        Expects context active_model='payroll.template' and active_id.
        """
        self.ensure_one()
        ctx = dict(self.env.context or {})
        if ctx.get('active_model') != 'payroll.template' or not ctx.get('active_id'):
            return False
        Template = self.env['payroll.template']
        tmpl = Template.browse(ctx['active_id']).exists()
        if not tmpl:
            return False
        # Avoid duplicates by payroll_key within template
        existing_keys = set(tmpl.column_ids.mapped('payroll_key'))
        if self.payroll_key in existing_keys:
            return False
        tmpl.write({
            'column_ids': [(0, 0, {
                'sequence': 999,
                'variable_id': self.id,
                'display_name': self.name,
                'system_key': self.system_key,
                'payroll_key': self.payroll_key,
                'var_type': self.kind,
                'data_type': self.data_type,
                'definition': self.definition,
                'description': self.description,
            })]
        })
        return True
