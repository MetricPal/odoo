"""Request counter for the System overview: requests, response times and server errors per hour and route.

Each worker counts in memory and writes its totals at most once a minute (on a request, with its own cursor), so a
request pays only a dictionary update. Routes are grouped (numbers become ":id") to keep the table small.
"""

import logging
import re
import threading
import time
from collections import defaultdict

from werkzeug.exceptions import HTTPException

from odoo import api, fields, models
from odoo.http import request

_logger = logging.getLogger(__name__)

BUCKETS = (100, 300, 1000, 3000)          # ms: under 100, 300, 1000, 3000, and slower
FLUSH_SECONDS = 60
_lock = threading.Lock()
_pending = defaultdict(lambda: [0, 0.0, 0, [0] * (len(BUCKETS) + 1)])  # (db, hour, route) -> count, ms, errors, buckets
_last_flush = {'at': time.monotonic()}
DIGITS = re.compile(r'\d+')


def _route():
    path = request.httprequest.path or '/'
    return DIGITS.sub(':id', path)[:120]


def _record(duration_ms, error):
    if not request or not getattr(request, 'db', None):
        return
    hour = fields.Datetime.now().replace(minute=0, second=0, microsecond=0)
    bucket = next((i for i, limit in enumerate(BUCKETS) if duration_ms < limit), len(BUCKETS))
    with _lock:
        row = _pending[(request.db, hour, _route())]
        row[0] += 1
        row[1] += duration_ms
        row[2] += 1 if error else 0
        row[3][bucket] += 1
        due = time.monotonic() - _last_flush['at'] >= FLUSH_SECONDS
    if due:
        _flush(request.db)


def _flush(dbname):
    with _lock:
        items = [(key, value) for key, value in _pending.items() if key[0] == dbname]
        for key, _value in items:
            del _pending[key]
        _last_flush['at'] = time.monotonic()
    if not items:
        return
    try:
        from odoo.modules.registry import Registry
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, api.SUPERUSER_ID, {})
            if 'ai.home.request.stat' in env:
                env['ai.home.request.stat']._add(items)
    except Exception:  # noqa: BLE001 - counting must never break a request
        _logger.debug('Could not write request counters', exc_info=True)


class AiHomeRequestStat(models.Model):
    _name = 'ai.home.request.stat'
    _description = 'Requests per hour and route'
    _order = 'hour desc'

    hour = fields.Datetime(required=True, index=True)
    route = fields.Char(required=True, index=True)
    count = fields.Integer()
    total_ms = fields.Float()
    errors = fields.Integer()
    bucket_0 = fields.Integer('Under 100 ms')
    bucket_1 = fields.Integer('Under 300 ms')
    bucket_2 = fields.Integer('Under 1 s')
    bucket_3 = fields.Integer('Under 3 s')
    bucket_4 = fields.Integer('3 s or more')

    _unique_hour_route = models.Constraint('unique(hour, route)', 'One row per hour and route.')

    @api.model
    def _add(self, items):
        for (_db, hour, route), (count, total_ms, errors, buckets) in items:
            row = self.search([('hour', '=', hour), ('route', '=', route)], limit=1)
            values = {f'bucket_{i}': value for i, value in enumerate(buckets)}
            if row:
                row.write({'count': row.count + count, 'total_ms': row.total_ms + total_ms,
                           'errors': row.errors + errors,
                           **{key: row[key] + value for key, value in values.items()}})
            else:
                self.create({'hour': hour, 'route': route, 'count': count, 'total_ms': total_ms, 'errors': errors,
                             **values})

    @api.model
    def _p95(self, buckets):
        """Upper bound (ms) of the bucket holding the 95th percentile."""
        total = sum(buckets)
        if not total:
            return 0
        seen = 0
        for index, value in enumerate(buckets):
            seen += value
            if seen >= 0.95 * total:
                return BUCKETS[index] if index < len(BUCKETS) else BUCKETS[-1]
        return BUCKETS[-1]

    @api.autovacuum
    def _gc_old_rows(self):
        self.search([('hour', '<', fields.Datetime.now() - __import__('datetime').timedelta(days=90))]).unlink()


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        request._ai_home_started = time.perf_counter()
        return super()._pre_dispatch(rule, args)

    @classmethod
    def _post_dispatch(cls, response):
        result = super()._post_dispatch(response)
        started = getattr(request, '_ai_home_started', None)
        if started is not None:
            status = getattr(response, 'status_code', 200) or 200
            _record((time.perf_counter() - started) * 1000, status >= 500)
            request._ai_home_started = None
        return result

    @classmethod
    def _handle_error(cls, exception):
        started = getattr(request, '_ai_home_started', None)
        if started is not None:
            server_error = not isinstance(exception, HTTPException) or (exception.code or 500) >= 500
            _record((time.perf_counter() - started) * 1000, server_error)
            request._ai_home_started = None
        return super()._handle_error(exception)
