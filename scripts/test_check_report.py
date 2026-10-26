#!/usr/bin/env python3
"""Browser regressions using only bundled geometry; no visual acceptance claim.

Run with --node PATH --browser PATH --out NEW_DIRECTORY. NODE_PATH is inherited.
The supplied output directory retains fixtures, JSON results and screenshots.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    scripts = Path(__file__).resolve().parent
    example = scripts.parent / 'assets' / 'comparison-report' / 'example'
    results = []

    for case in ['offscreen', 'optional', 'missing-image', 'corrupt-image', 'missing-link']:
        case_dir = root / case
        inputs = case_dir / 'inputs'
        shutil.copytree(example, inputs)
        manifest_path = inputs / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        # Put process imagery well below the initial desktop and narrow viewport.
        manifest['steps'] = [dict(title=f'Geometry step {n}', detail='Generated test geometry only.')
                             for n in range(30)] + manifest['steps']
        if case == 'optional':
            manifest.pop('before_render')
            manifest['regions'] = []
            manifest['steps'] = []
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        report_dir = case_dir / 'report'
        subprocess.run([sys.executable, str(scripts / 'build_report.py'), '--manifest',
                        str(manifest_path), '--out', str(report_dir), '--draft'],
                       check=True, capture_output=True, text=True)
        html = (report_dir / 'index.html').read_text(encoding='utf-8')
        data = json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>',
                                   html, re.S).group(1))
        if case in {'missing-image', 'corrupt-image'}:
            image = report_dir / data['steps'][-1]['image']
            if case == 'missing-image':
                image.unlink()
            else:
                image.write_bytes(b'corrupt generated test image')
        if case == 'missing-link':
            (report_dir / data['files']['review_check']).unlink()
        started = time.monotonic()
        checked = subprocess.run([args.node, str(scripts / 'check_report.mjs'),
                                  str(report_dir / 'index.html'), '--browser', args.browser,
                                  '--out', str(case_dir / 'qa')],
                                 capture_output=True, text=True, timeout=60)
        elapsed = time.monotonic() - started
        summary = json.loads((case_dir / 'qa' / 'check.json').read_text(encoding='utf-8'))
        expected = case in {'offscreen', 'optional'}
        assert (checked.returncode == 0) == expected, checked.stdout + checked.stderr
        assert summary['passed'] == expected, summary
        assert all((case_dir / 'qa' / name).is_file() for name in ['desktop.png', 'narrow.png'])
        if expected:
            assert len(summary['viewports']) == 2, summary
        elif case in {'missing-image', 'corrupt-image'}:
            assert 'initial image decoding:' in summary['errors'][0], summary
            # A known bad offscreen image must resolve to error without waiting
            # for the report's 30-second decode timeout.
            assert elapsed < 20, f'{case} took {elapsed:.1f}s'
        else:
            assert 'local resources:' in summary['errors'][0], summary
        results.append({'case': case, 'passed': True, 'seconds': round(elapsed, 2)})
        print(f'PASS {case} ({elapsed:.2f}s)')
    (root / 'regressions.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
