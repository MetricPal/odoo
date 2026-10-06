"""Opt-in local capacity characterization; excluded from normal CI."""

import json
import logging
import math
import os
import platform
import time

from odoo.tests import HttpCase, tagged

from .test_provider import SECRET, fixture
from .test_sandbox import TestTelegramSandbox
from odoo.addons.omni_channel.providers.inbound import verified_events

_logger = logging.getLogger(__name__)


@tagged('-standard', 'omni_capacity', 'post_install', '-at_install')
class TestTelegramCapacity(HttpCase, TestTelegramSandbox):
    def test_sustained_ingress_and_burst(self):
        self._activate()
        url = '/omni/inbound/' + self.endpoint.route_key
        headers = {'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': SECRET}
        latencies = []
        start = time.monotonic()
        for index in range(6000):
            delay = start + index / 10 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            payload = fixture()
            payload['update_id'] = 100000 + index
            payload['message']['message_id'] = 100000 + index
            before = time.monotonic()
            response = self.url_open(url, data=json.dumps(payload).encode(), headers=headers)
            latencies.append(time.monotonic() - before)
            self.assertEqual(response.status_code, 200)
            if index % 600 == 599:
                _logger.info('CAPACITY_PROGRESS events=%s elapsed=%.2f', index + 1, time.monotonic() - start)
        sustained_seconds = time.monotonic() - start
        latencies.sort()
        p95 = latencies[math.ceil(len(latencies) * .95) - 1]
        p99 = latencies[math.ceil(len(latencies) * .99) - 1]
        # Drain the sustained phase before measuring the distinct burst.
        events = self.env['omni.webhook.event']
        while events.search_count([('endpoint_id', '=', self.endpoint.id), ('state', '=', 'received')]):
            events._process_batch(limit=100)
        before = time.monotonic()
        for index in range(1000):
            payload = fixture()
            payload['update_id'] = 200000 + index
            payload['message']['message_id'] = 200000 + index
            # Seed an already admitted backlog; the endpoint intentionally caps
            # admission at 600/minute. Do not weaken that production protection.
            normalized, raw_hash = verified_events(
                self.channel.channel_type_id.code, json.dumps(payload).encode(),
                headers, self.endpoint._config(),
            )
            for event in normalized:
                events._store(self.endpoint, event, raw_hash)
        enqueue_seconds = time.monotonic() - before
        before = time.monotonic()
        while events.search_count([('endpoint_id', '=', self.endpoint.id), ('state', '=', 'received')]):
            events._process_batch(limit=100)
        drain_seconds = time.monotonic() - before
        self.assertEqual(events.search_count([('endpoint_id', '=', self.endpoint.id), ('state', '=', 'processed')]), 7000)
        self.assertFalse(any(method == 'sendMessage' for method, _ in self.http.calls))
        _logger.info('CAPACITY_RESULT %s', json.dumps({'events': 6000, 'sustained_seconds': sustained_seconds,
            'p95_seconds': p95, 'p99_seconds': p99, 'burst_events': 1000,
            'burst_enqueue_seconds': enqueue_seconds, 'burst_drain_seconds': drain_seconds,
            'cpu_count': os.cpu_count(), 'machine': platform.machine(),
            'scope': 'local HttpCase shared test transaction; synthetic Telegram; no TLS/proxy/provider latency; burst via ORM'}))
        self.assertLess(sustained_seconds, 610)
        self.assertLess(p95, 1)
        self.assertLess(p99, 2)
        self.assertLess(drain_seconds, 300)
