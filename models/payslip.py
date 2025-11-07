# -*- coding: utf-8 -*-
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError  # <-- ensure import
from odoo.tools.safe_eval import safe_eval


class PayrollPayslip(models.Model):
    _name = "payroll.payslip"
    _description = "Payslip"

    name = fields.Char(default="/", copy=False)
    run_id = fields.Many2one("payroll.payslip.run", string="Batch", ondelete="set null")
    employee_id = fields.Many2one("employee3c.employee.base", string="Employee", required=True)
    # Store related to support record rules and fast domain filters
    employee_user_id = fields.Many2one(
        "res.users",
        string="Employee User",
        related="employee_id.user_id",
        store=True,
        readonly=True,
    )
    # Convenience related fields for list views/filters
    employee_department_id = fields.Many2one(
        'employee3c.department', string='Phòng ban',
        related='employee_id.department_id', store=True, readonly=True)
    employee_calendar2_id = fields.Many2one(
        'employee3c.calendar2', string='Lịch làm việc',
        related='employee_id.calendar2_id', store=True, readonly=True)
    date_from = fields.Date(string="Date From", required=True)
    date_to = fields.Date(string="Date To", required=True)
    structure_id = fields.Many2one("payroll.structure", string="Structure")
    state = fields.Selection([
        ("draft", "Draft"),
        ("to_approve", "To Approve"),
        ("approved", "Approved"),
        ("done", "Done"),
        ("cancel", "Cancelled"),
    ], default="draft", tracking=False)
    line_ids = fields.One2many("payroll.payslip.line", "payslip_id", string="Lines")
    employee_avatar_html = fields.Html(string="Avatar", compute="_compute_employee_avatar_html", sanitize=False)

    # Payroll Sheet integration (for current employee in this run)
    sheet_line_id = fields.Many2one('payroll.sheet.line', compute='_compute_sheet_line', readonly=True, store=False)
    sheet_work_day = fields.Float(string="Công chuẩn", compute='_compute_sheet_numbers', readonly=True, store=False)
    sheet_points = fields.Float(string="Công thực tế", compute='_compute_sheet_numbers', readonly=True, store=False)
    sheet_values = fields.Text(string="Sheet JSON", compute='_compute_sheet_values', readonly=True, store=False)

    # KPI integration for this payslip period
    kpi_period_id = fields.Many2one('payroll.kpi_period', string='KPI Period', compute='_compute_kpi_period', store=False, readonly=True)
    kpi_record_ids = fields.Many2many('payroll.kpi_record', string='KPI Records', compute='_compute_kpi_records', store=False, readonly=True)
    kpi_total_score = fields.Float(string='KPI Total (%)', compute='_compute_kpi_total', store=False, readonly=True)
    kpi_details_html = fields.Html(string='KPI Breakdown', compute='_compute_kpi_html', sanitize=False)
    # KPI adjustments
    kpi_adj_add = fields.Float(string='KPI Cộng (%)', compute='_compute_kpi_adjustments', store=False, readonly=True)
    kpi_adj_sub = fields.Float(string='KPI Trừ (%)', compute='_compute_kpi_adjustments', store=False, readonly=True)
    kpi_adj_net = fields.Float(string='KPI Cộng/Trừ (ròng %)', compute='_compute_kpi_adjustments', store=False, readonly=True)
    kpi_final_total = fields.Float(string='KPI Cuối cùng (%)', compute='_compute_kpi_adjustments', store=False, readonly=True)
    adjust_record_ids = fields.One2many('payroll.kpi_adjust_record', 'payslip_id', string='KPI Adjustments')

    def _compute_employee_user(self):
        """Deprecated: replaced by related field 'employee_user_id'. Keep for backward compatibility."""
        for rec in self:
            pass

    def _compute_employee_avatar_html(self):
        for rec in self:
            # render a simple circle avatar using employee name initials if no image field available
            name = (rec.employee_id and getattr(rec.employee_id, "name", False)) or ""
            initials = "".join([p[0].upper() for p in name.split() if p])[:2] if name else "?"
            rec.employee_avatar_html = f"<div style='width:64px;height:64px;border-radius:50%;background:#ddd;display:flex;align-items:center;justify-content:center;font-weight:bold;'>{initials}</div>"

    @api.model
    def create(self, vals):
        # Ensure a meaningful name
        if not vals.get('name') or vals.get('name') == '/':
            vals['name'] = '/'
        rec = super().create(vals)
        if rec.name == '/' or not rec.name:
            # derive year/month from date_from or today
            try:
                d = fields.Date.from_string(rec.date_from) if rec.date_from else fields.Date.context_today(self)
            except Exception:
                d = fields.Date.context_today(self)
            rec.name = f"PS/{d.year}/{d.month:02d}/{rec.id:04d}"
        return rec

    def _compute_sheet_line(self):
        SheetLine = self.env['payroll.sheet.line']
        for rec in self:
            if rec.run_id and rec.employee_id:
                line = SheetLine.search([
                    ('sheet_id.run_id', '=', rec.run_id.id),
                    ('employee_id', '=', rec.employee_id.id),
                ], limit=1)
                rec.sheet_line_id = line.id if line else False
            else:
                rec.sheet_line_id = False

    def _compute_sheet_numbers(self):
        for rec in self:
            try:
                work_day, points, _base = rec._get_sheet_values()
            except Exception:
                work_day, points = 0.0, 0.0
            rec.sheet_work_day = work_day or 0.0
            rec.sheet_points = points or 0.0

    def _compute_sheet_values(self):
        for rec in self:
            rec.sheet_values = rec.sheet_line_id.values if rec.sheet_line_id else False

    def _compute_kpi_period(self):
        Period = self.env['payroll.kpi_period'].sudo()
        for rec in self:
            if rec.date_from and rec.date_to:
                period = Period.search([
                    ('date_start', '=', rec.date_from),
                    ('date_end', '=', rec.date_to),
                ], limit=1)
                rec.kpi_period_id = period.id if period else False
            else:
                rec.kpi_period_id = False

    def _compute_kpi_records(self):
        Record = self.env['payroll.kpi_record']
        for rec in self:
            if rec.employee_id and rec.kpi_period_id:
                records = Record.search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('period_id', '=', rec.kpi_period_id.id),
                ])
                rec.kpi_record_ids = [(6, 0, records.ids)]
            else:
                rec.kpi_record_ids = [(6, 0, [])]

    def _compute_kpi_adjustments(self):
        Adjust = self.env['payroll.kpi_adjust_record']
        for rec in self:
            add_total = 0.0
            sub_total = 0.0
            if rec.employee_id and rec.kpi_period_id:
                # Ensure auto adjustments are synced
                try:
                    self.env['payroll.kpi_adjust_record'].sudo().sync_auto_for_employee_period(rec.employee_id, rec.kpi_period_id, payslip=rec)
                except Exception:
                    pass
                # Compute totals only from lines attached to this payslip
                lines = rec.adjust_record_ids
                for l in lines:
                    pts = float(l.total_points or 0.0)
                    if l.kind == 'add':
                        add_total += pts
                    else:
                        sub_total += pts
            net = add_total - sub_total
            rec.kpi_adj_add = add_total
            rec.kpi_adj_sub = sub_total
            rec.kpi_adj_net = net
            rec.kpi_final_total = (rec.kpi_total_score or 0.0) + net

    def _compute_kpi_total(self):
        for rec in self:
            total = 0.0
            try:
                for r in rec.kpi_record_ids:
                    total += float(getattr(r, 'score', 0.0) or 0.0)
            except Exception:
                total = 0.0
            rec.kpi_total_score = total

    def _compute_kpi_html(self):
        for rec in self:
            # Build a consolidated label-level table across all KPI records of this payslip
            header = (
                '<div class="o_form_view">'
                '<table class="o_list_view table table-sm table-striped table-hover">'
                '<thead><tr>'
                '<th>Mô tả</th>'
                '<th>Tên tag</th>'
                '<th>Nhóm</th>'
                '<th>Được giao</th>'
                '<th>Đúng hạn</th>'
                '<th>Hoàn thành muộn</th>'
                '<th>Quá hạn</th>'
                '<th>Trọng số</th>'
                '<th>Điểm KPI quy đổi(%)</th>'
                '</tr></thead><tbody>'
            )
            rows_html = []
            # Collect labels from all kpi_record_ids
            label_rows = []
            label_ids = set()
            for r in rec.kpi_record_ids:
                details = r.details or {}
                group_code = r.group_id.code or (details.get('code') if isinstance(details, dict) else '') or ''
                for row in (details.get('labels') or []):
                    lab_id = row.get('label_id')
                    if lab_id:
                        label_ids.add(lab_id)
                    label_rows.append((group_code, row))

            # Map label_id -> label record (for names and tag)
            labels_map = {}
            if label_ids:
                Label = rec.env['payroll.kpi_label'].sudo()
                for lab in Label.browse(list(label_ids)).exists():
                    labels_map[lab.id] = lab

            # Sort by group, then label name
            def _sort_key(item):
                gcode, row = item
                lab = labels_map.get(row.get('label_id'))
                lname = lab.name if lab else ''
                return (gcode or '', lname)

            label_rows.sort(key=_sort_key)

            # Pre-compute per-group stats for proper distribution within group
            group_stats = {}
            for gcode, row in label_rows:
                lab = labels_map.get(row.get('label_id'))
                if gcode not in group_stats:
                    group_stats[gcode] = {
                        'label_count': 0,
                        'total_weight': 0.0,
                        'total_assigned': 0.0,
                        'total_E_G': 0.0,
                        'sum_weight_times_assigned': 0.0,
                        'sum_EG_times_weight': 0.0,
                        'group_weight': 0.0,
                    }
                st = group_stats[gcode]
                st['label_count'] += 1
                # label configured weight
                try:
                    w = float(row.get('weight') or (lab.weight if lab else 0.0) or 0.0)
                except Exception:
                    w = 0.0
                st['total_weight'] += w
                # sums for ratio
                try:
                    assigned_v = float(row.get('assigned') or 0.0)
                    st['total_assigned'] += assigned_v
                except Exception:
                    assigned_v = 0.0
                try:
                    e_g_v = float(row.get('E_G') or 0.0)
                    st['total_E_G'] += e_g_v
                except Exception:
                    e_g_v = 0.0
                # accumulate E_G * weight for weighted ratio (match engine)
                try:
                    st['sum_EG_times_weight'] += float(w) * float(e_g_v)
                except Exception:
                    pass
                # denominator for contribution share inside group: weight * assigned
                try:
                    st['sum_weight_times_assigned'] += float(w) * float(assigned_v)
                except Exception:
                    pass
                # group weight (%) from model
                try:
                    st['group_weight'] = float(lab.group_id.weight or 0.0) if lab and lab.group_id else (st['group_weight'] or 0.0)
                except Exception:
                    pass

            for group_code, row in label_rows:
                lab = labels_map.get(row.get('label_id'))
                label_name = lab.name if lab else str(row.get('label_id') or '')
                tag_name = lab.tag_id.name if (lab and lab.tag_id) else ''
                assigned = int(row.get('assigned') or 0)
                ontime = int(row.get('ontime') or 0)
                late = int(row.get('late') or 0)
                overdue = int(row.get('overdue') or 0)
                weight = float(row.get('weight') or (lab.weight if lab else 0.0) or 0.0)
                e_g = float(row.get('E_G') or 0.0)
                # Distribution inside group: share by (label weight * assigned)
                st = group_stats.get(group_code, {})
                total_w = float(st.get('total_weight') or 0.0)
                cnt = int(st.get('label_count') or 0)
                denom = float(st.get('sum_weight_times_assigned') or 0.0)
                if denom > 0.0:
                    share = (weight * float(assigned)) / denom
                else:
                    # Fallback when no assignments at all: use weight proportion or equal share
                    share = (weight / total_w) if total_w > 0.0 else (1.0 / cnt if cnt else 0.0)
                # Group achieved ratio (weighted to match engine): num/den
                num_w = float(st.get('sum_EG_times_weight') or 0.0)
                den_w = float(st.get('sum_weight_times_assigned') or 0.0)
                ratio_g = (num_w / den_w) if den_w else 0.0
                group_weight = float(st.get('group_weight') or 0.0)
                # Final contribution of this label within group's weighted KPI
                kpi_pct_weighted = share * ratio_g * group_weight
                rows_html.append(
                    '<tr>'
                    f'<td>{label_name}</td>'
                    f'<td>{tag_name}</td>'
                    f'<td>{group_code}</td>'
                    f'<td style="text-align:center">{assigned}</td>'
                    f'<td style="text-align:center">{ontime}</td>'
                    f'<td style="text-align:center">{late}</td>'
                    f'<td style="text-align:center">{overdue}</td>'
                    f'<td style="text-align:center">{weight:.2f}</td>'
                    f'<td style="text-align:center">{kpi_pct_weighted:.2f}</td>'
                    '</tr>'
                )

            footer = '</tbody></table></div>'
            rec.kpi_details_html = header + ''.join(rows_html) + footer if rows_html else False

    # ---------- Helper to expose KPI figures as variables for formulas ----------
    def _build_kpi_variables(self):
        """Return a dict of dynamic KPI variables for this payslip instance.
        Keys:
          - 'KPI_TOTAL' (and 'kpi_total')
          - 'KPI_<GROUP_CODE>' for each KPI group code present (also lowercase alias)
        Values are floats (percent scores, same as kpi_record.score).
        """
        self.ensure_one()
        res = {}
        try:
            total = float(self.kpi_total_score or 0.0)
            res['KPI_TOTAL'] = total
            res['kpi_total'] = total
        except Exception:
            pass
        try:
            for r in (self.kpi_record_ids or self.env['payroll.kpi_record']):
                code = ((r.group_id and r.group_id.code) or '').strip()
                if not code:
                    continue
                key_up = f"KPI_{code.upper()}"
                key_lo = f"kpi_{code.lower()}"
                val = float(getattr(r, 'score', 0.0) or 0.0)
                res[key_up] = val
                res[key_lo] = val
        except Exception:
            pass
        return res

    def _get_sheet_values(self):
        """Return (work_day, points, base_wage_resolved) for this slip's employee.
        base_wage_resolved priority:
        1) value stored in Payroll Sheet JSON (key 'base_wage')
        2) VN Params 'use_source' selection: employee.standard_salary or payroll.salary.profile.base_wage
        3) fallback: None
        """
        self.ensure_one()
        SheetLine = self.env['payroll.sheet.line']
        line = SheetLine.search([
            ('sheet_id.run_id', '=', self.run_id.id),
            ('employee_id', '=', self.employee_id.id),
        ], limit=1)
        if not line:
            # no sheet line: still try to resolve base_wage from params source
            base_from_source = self._resolve_base_wage_from_params()
            return (0.0, 0.0, base_from_source)
        try:
            data = json.loads(line.values or '{}')
        except Exception:
            data = {}
        work_day = float(data.get('work_day') or 0.0)           # ngày công chuẩn
        points = float(data.get('points') or 0.0)               # điểm công (thực tế)
        base_wage_sheet = data.get('base_wage')                 # nếu có trong sheet
        try:
            base_wage_sheet = float(base_wage_sheet) if base_wage_sheet is not None else None
        except Exception:
            base_wage_sheet = None
        # If sheet lacks base_wage, use params-configured source
        if base_wage_sheet is None:
            base_wage_sheet = self._resolve_base_wage_from_params()
        return (work_day, points, base_wage_sheet)

    def _resolve_base_wage_from_params(self):
        """Resolve base wage per VN params.use_source setting.
        - 'employee': employee.standard_salary
        - 'payroll': payroll.salary.profile.base_wage
        Returns float or None.
        """
        self.ensure_one()
        Params = self.env['payroll.vn.params']
        params = Params.search([], limit=1)
        source = getattr(params, 'use_source', None) or 'employee'
        # employee source
        if source == 'employee':
            try:
                val = getattr(self.employee_id, 'standard_salary', None)
                return float(val) if val not in (None, False, '') else None
            except Exception:
                return None
        # payroll profile source
        if source == 'payroll':
            prof = self.env['payroll.salary.profile'].search([('employee_id', '=', self.employee_id.id)], limit=1)
            if prof:
                try:
                    return float(getattr(prof, 'base_wage', None) or 0.0)
                except Exception:
                    return None
        return None

    def action_compute_lines(self):
        """Compute/update lines strictly from active salary rules in the structure.
        - Only evaluate configured rules (no post-process overrides, no fallbacks)
        - Expose variable catalog as V/vars for Python formulas
        - Resulting lines match active rules only
        """
        for slip in self:
            # Validate structure and rules
            if not slip.structure_id:
                raise UserError(_("Phiếu lương thiếu Cấu trúc lương (Salary Structure). Hãy chọn cấu trúc trước khi Compute."))
            active_rules = slip.structure_id.rule_ids.filtered(lambda r: r.active)
            if not active_rules:
                raise UserError(_("Cấu trúc lương '%s' chưa có Salary Rule đang Active.") % (slip.structure_id.display_name))
            # 1) Build rule-based lines
            new_lines = []
            codes = {}
            # Chuẩn bị biến catalog cho công thức (V/vars)
            try:
                var_map = self.env['payroll.variable'].with_context(run_id=slip.run_id.id).compute_values_for_employee(
                    slip.employee_id, slip.date_from, slip.date_to)
            except Exception:
                var_map = {}
            # Bổ sung biến KPI động cho kỳ lương hiện tại: KPI_TOTAL và KPI_<GROUP_CODE>
            try:
                kpi_vars = slip._build_kpi_variables()
                if kpi_vars:
                    var_map.update(kpi_vars)
            except Exception:
                # Không chặn nếu không lấy được KPI
                pass
            rules = active_rules.sorted(key=lambda r: (r.sequence, r.id))
            local_base = {
                'slip': slip,
                'employee': slip.employee_id,
                'env': self.env,
                'get_code': lambda c: codes.get(c, 0.0),
                'V': var_map,
                'vars': var_map,
            }
            for rule in rules:
                # Condition
                passed = True
                if rule.condition == 'python':
                    loc = dict(local_base)
                    try:
                        safe_eval(rule.condition_python or 'result = True', loc, mode='exec', nocopy=True)
                        passed = bool(loc.get('result', False))
                    except Exception:
                        passed = False
                if not passed:
                    continue
                # Amount
                amount = 0.0
                qty = 1.0
                if rule.amount_type == 'fixed':
                    amount = float(rule.amount_fix or 0.0)
                elif rule.amount_type == 'percent':
                    base_amt = float(codes.get(rule.amount_base_code or '', 0.0))
                    amount = base_amt * float(rule.amount_percent or 0.0) / 100.0
                elif rule.amount_type == 'python':
                    loc = dict(local_base)
                    try:
                        safe_eval(rule.amount_python or 'result = 0.0', loc, mode='exec', nocopy=True)
                        amount = float(loc.get('result', 0.0))
                    except Exception:
                        # If formula fails, keep amount=0 but continue building other lines
                        amount = 0.0
                # Accumulate and stage line
                codes[rule.code] = amount
                new_lines.append({
                    'name': rule.name,
                    'code': rule.code,
                    'sequence': rule.sequence,
                    'amount': amount,
                    'quantity': qty,
                    'category_id': rule.category_id.id,
                    'rule_id': rule.id,
                })

            # Replace existing lines with computed ones
            slip.write({'line_ids': [(5, 0, 0)] + [(0, 0, vals) for vals in new_lines]})
        return True

    def _compute_statutory_and_net(self, gross_salary, base_wage_used):
        """Deprecated: Computation now fully driven by salary rules. Keep for backward-compatibility (no-op)."""
        return True

    def action_save_kpi_adjustments(self):
        """Explicit save/sync action for KPI adjustments on this payslip.
        - Re-sync auto adjustments for this payslip
        - Return a UI notification
        """
        for rec in self:
            try:
                self.env['payroll.kpi_adjust_record'].sudo().sync_auto_for_employee_period(
                    rec.employee_id, rec.kpi_period_id, payslip=rec)
            except Exception:
                # Do not block UI on sync errors; values will remain as-is
                pass
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('Đã lưu và cập nhật cộng/trừ KPI.'),
                'type': 'success',
                'sticky': False,
            }
        }

    @staticmethod
    def _vn_pit_progressive(taxable):
        """Vietnam monthly PIT progressive computation without quick deduction.
        Brackets (VND):
          0-5m: 5%
          5-10m: 10%
          10-18m: 15%
          18-32m: 20%
          32-52m: 25%
          52-80m: 30%
          >80m: 35%
        """
        t = float(taxable or 0.0)
        if t <= 0:
            return 0.0
        brackets = [
            (5_000_000.0, 0.05),
            (10_000_000.0, 0.10),
            (18_000_000.0, 0.15),
            (32_000_000.0, 0.20),
            (52_000_000.0, 0.25),
            (80_000_000.0, 0.30),
        ]
        tax = 0.0
        prev_cap = 0.0
        for cap, rate in brackets:
            if t > cap:
                tax += (cap - prev_cap) * rate
                prev_cap = cap
            else:
                tax += (t - prev_cap) * rate
                return tax
        # above last cap
        tax += (t - prev_cap) * 0.35
        return tax

    # Header actions for state changes
    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_set_to_approve(self):
        self.write({'state': 'to_approve'})
        return True

    def action_approve(self):
        self.write({'state': 'approved'})
        return True

    def action_done(self):
        self.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancel'})
        return True

    def unlink(self):
        for rec in self:
            # Business rule: do not allow deleting completed payslips
            if rec.state == 'done':
                raise UserError(_("Không thể xóa phiếu lương ở trạng thái Done."))
        return super().unlink()


class PayrollPayslipLine(models.Model):
    _name = "payroll.payslip.line"
    _description = "Payslip Line"
    _order = "sequence, id"

    payslip_id = fields.Many2one("payroll.payslip", required=True, ondelete="cascade")
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=100)
    amount = fields.Float()
    quantity = fields.Float(default=1.0)
    total = fields.Float(compute="_compute_total", store=False)
    category_id = fields.Many2one("payroll.category", string="Category")
    rule_id = fields.Many2one("payroll.rule", string="Rule")

    @api.depends("amount", "quantity")
    def _compute_total(self):
        for rec in self:
            try:
                rec.total = float(rec.amount or 0.0) * float(rec.quantity or 0.0)
            except Exception:
                rec.total = 0.0


class PayrollPayslipRun(models.Model):
    _name = "payroll.payslip.run"
    _description = "Payroll Batch"

    name = fields.Char(required=True, default="/", copy=False)
    month = fields.Integer(string="Month", help="1-12")
    year = fields.Integer(string="Year")
    select_days = fields.Boolean(string="Chọn ngày cụ thể?")
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    slip_ids = fields.One2many("payroll.payslip", "run_id", string="Payslips")
    sheet_ids = fields.One2many("payroll.sheet", "run_id", string="Payroll Sheets")
    sheet_id = fields.Many2one("payroll.sheet", string="Payroll Sheet", compute="_compute_sheet_id", store=False, readonly=True)

    def _compute_sheet_id(self):
        Sheet = self.env['payroll.sheet']
        for rec in self:
            sheet = Sheet.search([('run_id', '=', rec.id)], limit=1)
            rec.sheet_id = sheet.id if sheet else False

    @api.model
    def create(self, vals):
        if not vals.get("name") or vals.get("name") == "/":
            vals["name"] = self.env["ir.sequence"].next_by_code("payroll.payslip.run") or "/"
        rec = super().create(vals)
        # Auto create or update the linked payroll sheet
        rec._create_or_update_sheet()
        return rec

    @api.onchange("month", "year", "select_days")
    def _onchange_month_year(self):
        for rec in self:
            if rec.month and rec.year and not rec.select_days:
                try:
                    y = int(rec.year)
                    m = int(rec.month)
                    if m in (1, 3, 5, 7, 8, 10, 12):
                        last_day = 31
                    elif m in (4, 6, 9, 11):
                        last_day = 30
                    else:
                        leap = (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0))
                        last_day = 29 if leap else 28
                    rec.date_start = fields.Date.from_string(f"{y:04d}-{m:02d}-01")
                    rec.date_end = fields.Date.from_string(f"{y:04d}-{m:02d}-{last_day:02d}")
                except Exception:
                    rec.date_start = False
                    rec.date_end = False

    def action_compute_payslips(self):
        """Compute lines for all payslips in this batch."""
        for run in self:
            if run.slip_ids:
                run.slip_ids.action_compute_lines()
        return True

    def _get_month_year(self):
        self.ensure_one()
        y = self.year
        m = self.month
        try:
            if not (y and m) and self.date_start:
                ds = fields.Date.from_string(self.date_start)
                y = y or ds.year
                m = m or ds.month
        except Exception:
            pass
        return int(y or 0), int(m or 0)

    def _get_or_create_default_template(self):
        Template = self.env['payroll.template']
        tmpl = Template.search([], limit=1)
        if tmpl:
            return tmpl
        # Create a minimal default template if none exists
        return Template.create({
            'name': 'Default Payroll Template',
        })

    def _create_or_update_sheet(self):
        for run in self:
            # Find existing sheet
            Sheet = run.env['payroll.sheet']
            sheet = Sheet.search([('run_id', '=', run.id)], limit=1)
            # Determine month/year
            year, month = run._get_month_year()
            # Ensure we have a template
            tmpl = run._get_or_create_default_template()
            vals = {
                'name': f"{run.name} - Payroll Sheet",
                'run_id': run.id,
                'template_id': tmpl.id,
                'month': month or 0,
                'year': year or 0,
                'date_start': run.date_start,
                'date_end': run.date_end,
            }
            if sheet:
                # Update existing
                sheet.write(vals)
            else:
                # Create new
                Sheet.create(vals)

    def write(self, vals):
        res = super().write(vals)
        # After updates (name/dates/month/year), sync the sheet
        self._create_or_update_sheet()
        return res

    def unlink(self):
        for rec in self:
            # If any payslip in batch is done, block deletion
            if rec.slip_ids.filtered(lambda s: s.state == 'done'):
                raise UserError(_("Không thể xóa batch có phiếu lương ở trạng thái Done."))  # make translatable
        return super().unlink()

    # ---------- UI helpers: open wizards via object methods to avoid load-time XMLID resolution ----------
    def _open_action(self, xmlid, ctx_update=None):
        self.ensure_one()
        action = self.env.ref(xmlid).sudo().read()[0]
        ctx = dict(self.env.context or {})
        if ctx_update:
            ctx.update(ctx_update)
        action['context'] = ctx
        return action

    def action_open_generate_payslips_wizard(self):
        return self._open_action(
            'payroll_3c.action_generate_payslips_wizard',
            {
                'default_run_id': self.id,
                'default_date_start': self.date_start,
                'default_date_end': self.date_end,
            }
        )

    def action_open_create_sheet_wizard(self):
        return self._open_action(
            'payroll_3c.action_create_sheet_wizard',
            {
                'default_run_id': self.id,
            }
        )

    def action_open_confirm_delete_batch(self):
        # Reuse confirm delete wizard action but ensure correct model context
        return self._open_action(
            'payroll_3c.action_confirm_delete_batch',
            {
                'default_model': 'payroll.payslip.run',
            }
        )

    def action_open_payslips_list(self):
        self.ensure_one()
        action = self.env.ref('payroll_3c.action_payroll_payslips').sudo().read()[0]
        # Focus the list on this batch and keep search view filters (department, etc.)
        raw_ctx = action.get('context') or {}
        if isinstance(raw_ctx, str):
            try:
                raw_ctx = safe_eval(raw_ctx)
            except Exception:
                raw_ctx = {}
        ctx = dict(raw_ctx)
        ctx.update({
            'default_run_id': self.id,
            'search_default_run_id': self.id,
        })
        action['context'] = ctx
        action['domain'] = [('run_id', '=', self.id)]
        return action

    def action_sync_sheet_and_compute(self):
        """Ensure sheet exists, sync timesheet points, then compute all payslips."""
        for run in self:
            # Ensure sheet exists or updated
            run._create_or_update_sheet()
            sheet = run.sheet_id
            if sheet:
                # Sync points/work_day from timesheet
                try:
                    sheet.action_sync_timesheet_points()
                except Exception:
                    # Don't block compute if sync fails; you can still compute
                    pass
            # Compute all payslips
            if run.slip_ids:
                run.slip_ids.action_compute_lines()
        return True
