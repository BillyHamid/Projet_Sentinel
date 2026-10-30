"""End-to-end test against the running LOCAL lab. About three minutes with training."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

BASE = 'http://127.0.0.1:8765'
client = httpx.Client(base_url=BASE, timeout=10, trust_env=False)


def state():
    response = client.get('/api/state')
    response.raise_for_status()
    return response.json()


def action(name):
    response = client.post('/api/control', headers={'X-Lab-Token': state()['token']}, json={'action': name})
    response.raise_for_status()


def observe(seconds):
    rows = {}
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        s = state()
        if s['latest']:
            rows[s['latest']['timestamp']] = s['latest']
        time.sleep(1)
    return list(rows.values())


def summarize(rows):
    return {'windows': len(rows), 'alerts': sum(r['alert'] for r in rows),
            'max_rps': max(r['rps'] for r in rows),
            'max_error_rate': max(r['error_rate'] for r in rows),
            'max_score_ratio': max((r['ratio'] or 0) for r in rows)}


if __name__ == '__main__':
    assert client.post('/api/control', json={'action': 'attack'}).status_code == 403
    assert client.get('/api/state', headers={'Host': 'example.com'}).status_code == 403
    if state()['phase'] != 'ready':
        if state()['phase'] != 'collecting':
            action('calibrate')
        deadline = time.monotonic() + 160
        while state()['phase'] != 'ready':
            s = state()
            if s['phase'] == 'error' or time.monotonic() > deadline:
                raise RuntimeError(s)
            print(f"Calibration : {s['calibration_count']}/{s['calibration_target']} — {s['phase']}", flush=True)
            time.sleep(10)
    action('normal')
    print('Observation du trafic normal...', flush=True)
    normal = observe(16)[2:]
    action('legitimate')
    print('Pic legitime local pendant 25 s...', flush=True)
    legitimate = observe(26)[2:24]
    action('normal')
    observe(4)
    action('attack')
    print('Surcharge locale bornee pendant 25 s...', flush=True)
    attack = observe(26)[2:24]
    delay = state()['detection_seconds']
    action('normal')
    print('Verification du retour a la normale...', flush=True)
    recovery = observe(15)[3:]
    exported = client.get('/api/export')
    export_ok = exported.status_code == 200 and exported.text.startswith('timestamp,rps,') and len(exported.text.splitlines()) > 10
    report = {'timestamp': datetime.now(timezone.utc).isoformat(),
              'model_trained_at': state()['model']['trained_at'],
              'scope': 'Test de fonctionnement local, sans valeur de benchmark scientifique.',
              'normal': summarize(normal), 'legitimate': summarize(legitimate),
              'attack': summarize(attack), 'recovery': summarize(recovery),
              'detection_seconds': delay,
              'checks': {'local_host_guard': True, 'control_token_guard': True, 'csv_export': export_ok,
                         'actual_service_degradation': any(r['error_rate'] > 0 for r in attack),
                         'neural_alert_during_attack': any(r['alert'] for r in attack),
                         'normal_without_confirmed_alert': not any(r['alert'] for r in normal),
                         'legitimate_without_confirmed_alert': not any(r['alert'] for r in legitimate),
                         'recovery_without_confirmed_alert': not any(r['alert'] for r in recovery)}}
    output = Path(__file__).parent / 'artifacts' / 'validation_live.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    assert all(report['checks'].values()), 'Consulter artifacts/validation_live.json'
