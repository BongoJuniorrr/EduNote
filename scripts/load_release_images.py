"""Import verified prebuilt root filesystems with their original Docker configuration.
No application build or external image registry is needed. Healthchecks are in Compose.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
LABEL='org.edunote.runtime.archive-sha256'


def matches(item,tag):
    result=subprocess.run(['docker','image','inspect',tag,'--format','{{json .Config.Labels}}'],capture_output=True,text=True)
    if result.returncode:return False
    return (json.loads(result.stdout) or {}).get(LABEL)==item['archive_sha256']


def changes(item):
    cfg=item['config'];result=[]
    for entry in cfg.get('Env') or []:
        name,value=entry.split('=',1)
        result.append('ENV '+name+'='+json.dumps(value))
    for name in ['Entrypoint','Cmd']:
        if cfg.get(name):result.append(name.upper()+' '+json.dumps(cfg[name]))
    if cfg.get('WorkingDir'):result.append('WORKDIR '+json.dumps(cfg['WorkingDir']))
    if cfg.get('User'):result.append('USER '+cfg['User'])
    if cfg.get('StopSignal'):result.append('STOPSIGNAL '+cfg['StopSignal'])
    if cfg.get('Volumes'):result.append('VOLUME '+json.dumps(list(cfg['Volumes'])))
    if cfg.get('ExposedPorts'):result.append('EXPOSE '+' '.join(cfg['ExposedPorts']))
    for name,value in (cfg.get('Labels') or {}).items():result.append('LABEL '+name+'='+json.dumps(value))
    result.append('LABEL '+LABEL+'='+json.dumps(item['archive_sha256']))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',help='Import only this image tag (validation/maintenance)')
    parser.add_argument('--tag-prefix',default='',help='Import under a separate tag namespace for validation')
    args=parser.parse_args()
    manifest=ROOT/'runtime/manifest.json'
    if not manifest.exists():raise SystemExit('Extract every runtime ZIP part, or build from source using README.md.')
    data=json.loads(manifest.read_text())
    if data.get('format')!='edunote-rootfs-v1':raise SystemExit('Unsupported runtime manifest format')
    selected=[item for item in data['images'] if not args.image or item['tag']==args.image]
    if not selected:raise SystemExit('Requested image is absent from the release manifest')
    for item in selected:
        tag=args.tag_prefix+item['tag']
        if matches(item,tag):
            print('Verified existing image: '+tag,flush=True);continue
        paths=[];combined=hashlib.sha256()
        for part in item['parts']:
            if Path(part['name']).name!=part['name']:raise SystemExit('Invalid runtime part name')
            path=ROOT/'runtime'/part['name']
            if not path.is_file():raise SystemExit('Missing runtime part: '+part['name'])
            part_digest=hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda:stream.read(8*1024*1024),b''):
                    combined.update(block);part_digest.update(block)
            if part_digest.hexdigest()!=part['sha256']:raise SystemExit('Checksum mismatch: '+part['name'])
            paths.append(path)
        if combined.hexdigest()!=item['archive_sha256']:raise SystemExit('Image archive checksum mismatch')
        command=['docker','image','import','--platform',data['platform']]
        for change in changes(item):command+=['--change',change]
        command+=['-',tag]
        process=subprocess.Popen(command,stdin=subprocess.PIPE)
        try:
            for path in paths:
                with path.open('rb') as stream:
                    for block in iter(lambda:stream.read(8*1024*1024),b''):process.stdin.write(block)
            process.stdin.close()
            if process.wait():raise SystemExit('Image import failed: '+tag)
        except BaseException:
            process.terminate();process.wait();raise
        if not matches(item,tag):raise SystemExit('Imported image metadata verification failed')
        print('Verified and imported: '+tag,flush=True)


if __name__=='__main__':main()
