from datetime import timedelta
from odoo import models, fields


class PayrollKpiEngine(models.AbstractModel):
    _name = "payroll.kpi_engine"
    _description = "Helpers for KPI classification"

    def kpi_classify_task(self, task, overdue_threshold_days=7):
        """
        Classify a task completion status for KPI purposes.

        Returns one of: 'ontime', 'late', 'overdue', or None (excluded).

        Rules:
        - Only completed tasks are considered (task.state == 'done' and task.done_date is set).
        - Requires a deadline (task.due_date). If missing, exclude (return None).
        - On-time: done_date <= due_date.
        - Late: done_date > due_date and (done_date - due_date).days <= overdue_threshold_days.
        - Overdue: done_date > due_date and delay_days > overdue_threshold_days.

        Notes:
        - Odoo datetimes are stored in UTC; comparing server-side is consistent.
        - Threshold can be tuned later or sourced from a KPI setting/profile if needed.
        """
        # Must be completed with a completion timestamp
        if not getattr(task, "state", None) == "done":
            return None
        if not getattr(task, "done_date", None):
            return None

        due = getattr(task, "due_date", None)
        done = task.done_date
        if not due:
            # Spec: missing deadline -> excluded from E_G
            return None

        # Normalize to datetime (already datetime fields)
        if done <= due:
            return "ontime"

        delay = done - due
        # Use days with ceiling for partial days: > 0 means late at least
        delay_days = delay.days if delay.seconds == 0 else delay.days + 1
        if delay_days <= overdue_threshold_days:
            return "late"
        return "overdue"

    def aggregate_employee_label_counts(self, employee, period, labels, overdue_threshold_days=7):
        """
        Aggregate assigned and completed counts per KPI label for a given employee and period.

        Returns a dict keyed by label.id with:
        {
          'label_id': int,
          'group_id': int,
          'weight': float,
          'assigned': int,
          'ontime': int,
          'late': int,
          'overdue': int,
        }

        Assumptions:
        - Assigned = tasks where assignee_id == employee.user_id and due_date in [start, end].
        - A task can count toward multiple labels if it has multiple tags configured.
        - Completed classification uses kpi_classify_task rules; tasks w/o deadline or not done are excluded from ontime/late/overdue.
        """
        res = {}
        if not employee or not employee.user_id:
            return res

        Task = self.env["project3c.task"]
        # Date boundaries: include the whole end day
        start_dt = fields.Datetime.to_datetime(period.date_start)
        end_dt = fields.Datetime.end_of(fields.Datetime.to_datetime(period.date_end), "day")

        # Pre-build counters per label
        label_by_tag = {}
        tag_ids = set()
        for lab in labels:
            res[lab.id] = {
                "label_id": lab.id,
                "group_id": lab.group_id.id if lab.group_id else False,
                "weight": lab.weight or 1.0,
                "assigned": 0,
                "ontime": 0,
                "late": 0,
                "overdue": 0,
            }
            if lab.tag_id:
                label_by_tag.setdefault(lab.tag_id.id, []).append(lab)
                tag_ids.add(lab.tag_id.id)

        if not tag_ids:
            return res

        domain = [
            ("assignee_id", "=", employee.user_id.id),
            ("due_date", ">=", start_dt),
            ("due_date", "<=", end_dt),
            ("tag_ids", "in", list(tag_ids)),
        ]
        tasks = Task.search(domain)

        # Iterate tasks and update per-label counters
        classify = self.kpi_classify_task
        for t in tasks:
            # Assigned per matching label
            for tag in t.tag_ids:
                labs = label_by_tag.get(tag.id)
                if not labs:
                    continue
                for lab in labs:
                    entry = res[lab.id]
                    entry["assigned"] += 1

            # Completed breakdown per matching label
            bucket = classify(t, overdue_threshold_days=overdue_threshold_days)
            if bucket in ("ontime", "late", "overdue"):
                for tag in t.tag_ids:
                    labs = label_by_tag.get(tag.id)
                    if not labs:
                        continue
                    for lab in labs:
                        entry = res[lab.id]
                        entry[bucket] += 1

        return res

    def compute_group_metrics(self, counts_by_label, quality_profile, groups):
        """
        Compute E_G per label and aggregate per-group metrics.

        Params:
        - counts_by_label: dict keyed by label.id with keys: label_id, group_id, weight, assigned, ontime, late, overdue
        - quality_profile: record with coef_ontime, coef_late, coef_overdue
        - groups: recordset payroll.kpi_group OR dict {group_id: {code,name,weight}}

        Returns dict:
        {
          'total_score': float,                 # sum of group scores (percent)
          'groups': {
             group_id: {
               'group_id': int,
               'code': str,
               'name': str,
               'weight': float,                # group weight (%)
               'num': float,
               'den': float,
               'ratio': float,
               'score': float,                 # ratio * weight
               'labels': [
                 { 'label_id': int, 'weight': float, 'assigned': int,
                   'ontime': int, 'late': int, 'overdue': int, 'E_G': float }
               ]
             },
          }
        }
        """
        # Normalize groups into a mapping
        group_map = {}
        if isinstance(groups, dict):
            for gid, info in groups.items():
                group_map[gid] = {
                    'group_id': gid,
                    'code': info.get('code'),
                    'name': info.get('name'),
                    'weight': float(info.get('weight', 0.0)),
                    'num': 0.0,
                    'den': 0.0,
                    'labels': [],
                }
        else:
            # assume recordset
            for g in groups:
                group_map[g.id] = {
                    'group_id': g.id,
                    'code': g.code,
                    'name': g.name,
                    'weight': float(g.weight or 0.0),
                    'num': 0.0,
                    'den': 0.0,
                    'labels': [],
                }

        coef_on = float(quality_profile.coef_ontime or 0.0)
        coef_late = float(quality_profile.coef_late or 0.0)
        coef_over = float(quality_profile.coef_overdue or 0.0)

        # Compute E_G per label and roll-up per group
        for lab_id, data in (counts_by_label or {}).items():
            gid = data.get('group_id')
            if gid not in group_map:
                # Skip labels whose group is not in scope
                continue
            assigned = float(data.get('assigned', 0) or 0)
            ontime = float(data.get('ontime', 0) or 0)
            late = float(data.get('late', 0) or 0)
            overdue = float(data.get('overdue', 0) or 0)
            w_label = float(data.get('weight', 1.0) or 1.0)

            e_g = ontime * coef_on + late * coef_late + overdue * coef_over

            gentry = group_map[gid]
            gentry['num'] += e_g * w_label
            gentry['den'] += assigned * 1.0 * w_label
            gentry['labels'].append({
                'label_id': lab_id,
                'weight': w_label,
                'assigned': int(assigned),
                'ontime': int(ontime),
                'late': int(late),
                'overdue': int(overdue),
                'E_G': e_g,
            })

        # Finalize ratios and scores
        total = 0.0
        for gid, g in group_map.items():
            den = g['den']
            ratio = (g['num'] / den) if den else 0.0
            score = ratio * g['weight']  # group weight is in percent
            g['ratio'] = ratio
            g['score'] = score
            total += score

        return {
            'total_score': total,
            'groups': group_map,
        }

    def upsert_kpi_records(self, employee, period, metrics):
        """
        Persist KPI records per group for an employee and period using computed metrics.

        - Creates or updates payroll.kpi_record for each group in metrics['groups'].
        - Stores group breakdown (num/den/ratio/weight and label details) in details JSON.
        - Returns recordset of created/updated records and the total_score.
        """
        if not employee or not period or not metrics:
            return self.env["payroll.kpi_record"], 0.0

        KpiRecord = self.env["payroll.kpi_record"]
        records = self.env["payroll.kpi_record"]
        total = float(metrics.get('total_score', 0.0) or 0.0)

        groups = metrics.get('groups') or {}
        for gid, g in groups.items():
            vals = {
                'employee_id': employee.id,
                'period_id': period.id,
                'group_id': gid,
                'score': float(g.get('score', 0.0) or 0.0),
                'details': {
                    'code': g.get('code'),
                    'name': g.get('name'),
                    'weight': float(g.get('weight', 0.0) or 0.0),
                    'num': float(g.get('num', 0.0) or 0.0),
                    'den': float(g.get('den', 0.0) or 0.0),
                    'ratio': float(g.get('ratio', 0.0) or 0.0),
                    'labels': g.get('labels', []),
                }
            }

            existing = KpiRecord.search([
                ('employee_id', '=', employee.id),
                ('period_id', '=', period.id),
                ('group_id', '=', gid),
            ], limit=1)
            if existing:
                existing.write(vals)
                records |= existing
            else:
                rec = KpiRecord.create(vals)
                records |= rec

        return records, total
