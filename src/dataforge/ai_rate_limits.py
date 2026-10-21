"""Provider feedback is advisory; request slots, token quotas and capacity differ."""
from __future__ import annotations

import math
import re
import threading
from datetime import datetime
from email.utils import parsedate_to_datetime


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def _reset(value, now):
    if not isinstance(value, str):
        return None
    duration = re.fullmatch(r'(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?', value)
    if duration and any(duration.groups()):
        return now + float(duration[1] or 0) * 60 + float(duration[2] or 0)
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.timestamp() if date.tzinfo else None
    except ValueError:
        return None


def normalize_rate_limits(provider, headers, *, now):
    h = {k.lower(): v for k, v in headers.items()}
    retry = _number(h.get('retry-after'))
    if retry is not None:
        wait_until = now + retry
    else:
        try:
            wait_until = max(now, parsedate_to_datetime(h['retry-after']).timestamp())
        except (KeyError, ValueError, TypeError, OverflowError):
            wait_until = now
    buckets = {}
    prefix = 'anthropic-ratelimit-' if provider == 'Anthropic' else 'x-ratelimit-'
    for kind in ('requests', 'tokens', 'input-tokens', 'output-tokens'):
        remaining_key = prefix + kind + '-remaining' if provider == 'Anthropic' else prefix + 'remaining-' + kind
        reset_key = prefix + kind + '-reset' if provider == 'Anthropic' else prefix + 'reset-' + kind
        remaining = _number(h.get(remaining_key))
        if remaining is not None:
            buckets[kind] = {'remaining': remaining, 'reset': _reset(h.get(reset_key), now) or now + 60}
    return {'wait_until': wait_until, 'buckets': buckets, 'observed_at': now, 'source': 'response_headers'}


def retry_delay(attempt, headers, *, now, jitter=0):
    hint = normalize_rate_limits('', headers, now=now)['wait_until'] - now
    return max(hint, min(60, 2 ** min(attempt, 6)) + max(0, jitter))


def quota_scope(profile):
    # Endpoint-wide is deliberately conservative when upstream account/model is hidden.
    return 'group:' + profile.quota_group if profile.quota_group else 'endpoint:' + profile.base_url


class QuotaRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._snapshots = {}

    def observe(self, scope, snapshot):
        with self._lock:
            old = self._snapshots.get(scope, {})
            observed = snapshot['observed_at']
            buckets = {k: dict(v) for k, v in old.get('buckets', {}).items() if v['reset'] > observed}
            for kind, value in snapshot.get('buckets', {}).items():
                value = dict(value)
                if kind in buckets:
                    value['remaining'] = min(value['remaining'], buckets[kind]['remaining'])
                    value['reset'] = max(value['reset'], buckets[kind]['reset'])
                buckets[kind] = value
            self._snapshots[scope] = {**snapshot, 'buckets': buckets,
                'wait_until': max(old.get('wait_until', 0), snapshot.get('wait_until', 0))}

    def admit(self, scope, *, estimated_input, reserved_output, now):
        with self._lock:
            snapshot = self._snapshots.get(scope, {})
            wait = max(now, snapshot.get('wait_until', now))
            costs = {'requests': 1, 'tokens': estimated_input + reserved_output,
                     'input-tokens': estimated_input, 'output-tokens': reserved_output}
            buckets = snapshot.get('buckets', {})
            for kind, bucket in list(buckets.items()):
                if bucket['reset'] <= now:
                    del buckets[kind]
                elif bucket['remaining'] < costs[kind]:
                    wait = max(wait, bucket['reset'])
            if wait <= now:
                for kind, bucket in buckets.items():
                    bucket['remaining'] = max(0, bucket['remaining'] - costs[kind])
            return wait


QUOTAS = QuotaRegistry()
