#!/usr/bin/env python3
"""Reproducible release gates. Offline CI is not native GUI qualification."""
import argparse
import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from endurance import source_digest, atomic_json, utc_now

ROOT = Path(__file__).resolve().parents[1]


def policies():
    manifest = json.loads((ROOT/'manifest.json').read_text())
    assert manifest['id']=='owee.weather' and manifest['license']=='MIT'
    assert manifest['schemaVersion']==1 and manifest['kinds']==['bar-widget']
    assert (ROOT/manifest['entryPoints']['barWidget']).is_file()
    assert manifest['version'] in (ROOT/'Panel.qml').read_text()
    assert manifest['version'] in (ROOT/'BarWidget.qml').read_text()
    for name in ('LICENSE','README.md','PRIVACY.md','SOURCES.md'):
        assert (ROOT/name).is_file(), name
    for path in ROOT.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                assert not (isinstance(node.func, ast.Name) and node.func.id in ('eval','exec')), str(path)
                assert not any(k.arg=='shell' and isinstance(k.value,ast.Constant) and k.value.value is True for k in node.keywords), str(path)
    for path in ROOT.rglob('*'):
        if '.git' in path.parts or 'reports' in path.parts: continue
        assert not path.is_symlink(), str(path)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',action='store_true')
    parser.add_argument('--quality-python',type=Path,help='Python with pinned development tools installed')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/qualification')
    args=parser.parse_args();out=args.report_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    before,_=source_digest(ROOT)
    report={'status':'running','kind':'native' if args.native else 'offline','started_at':utc_now(),'source_sha256':before,'checks':[]}
    atomic_json(out/'summary.json',report)
    try:
        manifest=policies();report['version']=manifest['version']
        commands=[('python',[sys.executable,'-B','-m','unittest','discover','-s','tests','-v'])]
        if args.quality_python:
            quality=str(args.quality_python.absolute())
            os.environ['COVERAGE_FILE']=str(out/'.coverage')
            commands += [('lint',[quality,'-m','ruff','check','.']),
                         ('types',[quality,'-m','mypy']),
                         ('branches',[quality,'-m','coverage','run','-m','unittest','discover','-s','tests']),
                         ('branch-report',[quality,'-m','coverage','report']),
                         ('branch-xml',[quality,'-m','coverage','xml','-o',str(out/'coverage.xml')])]
        if args.native:
            commands += [('manifest',['omarchy','plugin','validate',str(ROOT)]),
                ('qml',['qmllint','-I','/usr/share/omarchy/shell',*[str(p) for p in sorted(ROOT.glob('*.qml'))]]),
                ('runtime',[sys.executable,'-B','qa/runtime_qml.py','--expected-version',manifest['version'],'--log',str(out/'runtime.log')]),
                ('ui',[sys.executable,'-B','qa/ui_layout/run.py','--output',str(out/'ui')]),
                ('ui150',[sys.executable,'-B','qa/ui_layout/run.py','--output',str(out/'ui150'),'--scale','1.5']),
                ('raster',[sys.executable,'-B','qa/ui_layout/run.py','--raster','--output',str(out/'raster')]),
                ('search',[sys.executable,'-B','qa/city_search/run.py']),
                ('drag',[sys.executable,'-B','qa/cards_drag/run.py']),
                ('cities',[sys.executable,'-B','qa/city_list_tests.py']),
                ('coverage',[sys.executable,'-B','qa/coverage/run.py']),
                ('motion',[sys.executable,'-B','qa/weather_motion/run.py','--native']),
                ('formats',[sys.executable,'-B','qa/formats/run.py']),
                ('preferences',[sys.executable,'-B','qa/native_preferences/run.py','--output',str(out/'preferences')]),
                ('preferences150',[sys.executable,'-B','qa/native_preferences/run.py','--scale','1.5','--output',str(out/'preferences150')]),
                ('favorite-cities',[sys.executable,'-B','qa/favorite_cities/run.py','--output',str(out/'favorite-cities')]),
                ('favorite-cities150',[sys.executable,'-B','qa/favorite_cities/run.py','--scale','1.5','--output',str(out/'favorite-cities150')])]
        for name,command in commands:
            start=time.monotonic()
            result=subprocess.run(command,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=150)
            (out/(name+'.log')).write_text(result.stdout)
            report['checks'].append({'name':name,'exit_code':result.returncode,'seconds':round(time.monotonic()-start,2)})
            atomic_json(out/'summary.json',report)
            print(name+': '+('PASS' if result.returncode==0 else 'FAIL'),flush=True)
            if result.returncode: raise RuntimeError(name+' failed; inspect '+str(out/(name+'.log')))
        if source_digest(ROOT)[0]!=before: raise RuntimeError('Source changed during qualification')
        report['status']='passed'
    except Exception as error:
        report.update(status='failed',error=str(error))
    report['finished_at']=utc_now();atomic_json(out/'summary.json',report)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':sys.exit(main())
