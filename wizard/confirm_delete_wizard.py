# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class PayrollConfirmDelete(models.TransientModel):
    _name = 'payroll.confirm.delete.wizard'
    _description = 'Confirm Delete Wizard'

    model = fields.Char(string='Model', required=True)
    res_ids = fields.Char(string='Record IDs', required=True)
    message = fields.Text(string='Message', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        model = self.env.context.get('default_model')
        active_ids = self.env.context.get('active_ids') or []
        if model:
            res['model'] = model
        if active_ids:
            res['res_ids'] = ','.join(str(i) for i in active_ids)
        res['message'] = self.env.context.get('message') or 'Bạn có chắc chắn muốn xóa các bản ghi đã chọn?'
        return res

    def action_confirm(self):
        self.ensure_one()
        model = self.model
        if not model:
            raise UserError('Thiếu thông tin model để xóa.')
        ids = []
        if self.res_ids:
            try:
                ids = [int(x) for x in self.res_ids.split(',') if x]
            except Exception:
                ids = []
        recs = self.env[model].browse(ids)
        if not recs:
            return {'type': 'ir.actions.act_window_close'}
        # Business rules already enforced in each model.unlink()
        recs.unlink()
        return {'type': 'ir.actions.act_window_close'}
