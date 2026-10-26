"""Exercise scaled/fractional SVG canvases, real holes and per-case reloads."""
import argparse, json, subprocess, tempfile
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--node', default='node')
    ap.add_argument('--browser', required=True)
    a = ap.parse_args()
    script = Path(__file__).with_name('probe_occlusion.mjs')
    with tempfile.TemporaryDirectory() as temp:
        p = Path(temp)
        contract = {'version': 1, 'cases': [
            {'id': f'case{i}', 'foreground': ['front'], 'underlay': ['back'],
             'reason': 'Independent interior sample under foreground',
             'solid_regions': [{'id': 'interior', 'polygon': [[42,32],[48,32],[48,38],[42,38]],
                                'min_alpha': 250, 'forbid_white': True}]}
            for i in range(2)]}
        (p/'contract.json').write_text(json.dumps(contract))
        for name, size, hole in [('unit', '100 80', False), ('scaled', '300 241.5', False),
                                 ('real-hole', '300 241.5', True)]:
            w,h = size.split()
            body = ('<path id="back" d="M10 10H90V70H10Z M40 30V40H50V30Z" fill-rule="evenodd" fill="pink"/>'
                    if hole else '<rect id="back" x="10" y="10" width="80" height="60" fill="pink"/>')
            (p/'drawing.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 100 80.5">{body}<rect id="front" x="35" y="25" width="20" height="20" fill="purple"/></svg>')
            out = p/name
            run = subprocess.run([a.node,str(script),str(p/'drawing.svg'),'--contract',str(p/'contract.json'),
                                  '--out',str(out),'--browser',a.browser], capture_output=True,text=True)
            assert (out/'result.json').exists(), run.stderr
            data = json.loads((out/'result.json').read_text())
            assert data['canvas'] == [100,81]
            assert data['pass'] == (not hole), (name,data)
            assert run.returncode == (2 if hole else 0), run.stderr
            assert all(c['pass'] == (not hole) for c in data['cases'])
            assert all(c['tests'][0]['sampled_pixels'] == 36 for c in data['cases'])
            print(name, 'expected', not hole, 'observed', data['pass'])

if __name__ == '__main__':
    main()
