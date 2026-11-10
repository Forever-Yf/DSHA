#!/usr/bin/env python3
"""Verify actual APK bytes and execute its embedded ARM64 Node/DSH under QEMU.

Software acceptance only, not Android/proot/physical-device acceptance.
"""
import argparse
import hashlib
import json
import posixpath
import re
import shutil
import struct
import subprocess
import tarfile
import zipfile
from pathlib import Path

ap=argparse.ArgumentParser()
ap.add_argument('--apk',type=Path,required=True)
ap.add_argument('--work',type=Path,required=True)
ap.add_argument('--sdk',type=Path,required=True)
args=ap.parse_args()
args.work.mkdir(parents=True,exist_ok=True)
tools=args.sdk/'build-tools/36.0.0'
badging=subprocess.check_output([str(tools/'aapt'),'dump','badging',str(args.apk)],text=True)
assert "name='io.github.foreveryf.dsha'" in badging
assert "versionCode='194'" in badging and "versionName='0.2.2-rc.1-fork.4-dsh0.2.2-rc.1'" in badging
assert "sdkVersion:'30'" in badging and "native-code: 'arm64-v8a'" in badging
assert 'application-debuggable' not in badging
manifest=subprocess.check_output([str(tools/'aapt'),'dump','xmltree',str(args.apk),'AndroidManifest.xml'],text=True)
for line in manifest.splitlines():
    if 'android:debuggable(' in line:
        assert line.strip().endswith('0x0'),line

def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):
            h.update(b)
    return h.hexdigest()

with zipfile.ZipFile(args.apk) as z:
    assert len(z.namelist())==len(set(z.namelist())), 'DUPLICATE_APK_ENTRY'
    descriptor=json.loads(z.read('assets/runtime-descriptor.json'))
    assert descriptor['dshVersion']=='0.2.2-rc.1'
    for name in ('dsh-runtime.bin','offline-rootfs.bin'):
        with z.open('assets/'+name) as f,(args.work/name).open('wb') as out:
            shutil.copyfileobj(f,out)
    runtime_sha=digest_file(args.work/'dsh-runtime.bin')
    assert runtime_sha==descriptor['inputs']['dsh-runtime.bin']
    assert z.read('assets/dsh-runtime.sha256').decode().strip()==runtime_sha
    assert z.read('assets/offline-rootfs.sha256').decode().strip()==digest_file(args.work/'offline-rootfs.bin')
    assert z.read('assets/offline-rootfs.layout').decode().strip()=='split-runtime-v1'
    registry=json.loads(z.read('assets/runtime-patches.json'))
    assert registry['dshVersion']=='0.2.2-rc.1' and len(registry['active'])==49
    assert any(x['asset']=='guard-tools-pipeline-patch.json' for x in registry['active'])
    for row in registry['active']:
        assert json.loads(z.read('assets/'+row['asset']))['dshVersion']=='0.2.2-rc.1'
    assert json.loads(z.read('assets/recovery-recipes/language-patch.json'))['dshVersion']=='0.2.1-rc.2'

runtime=args.work/'runtime'
runtime.mkdir(exist_ok=True)
with tarfile.open(args.work/'dsh-runtime.bin','r:gz') as tar:
    marker=tar.extractfile('usr/local/share/dsha/dsh-runtime.version').read().decode().strip()
    assert marker=='0.2.2-rc.1'
    main='usr/local/lib/node_modules/@deepseek-ai/dsh'
    assert json.load(tar.extractfile(main+'/package.json'))['version']==marker
    pipeline=tar.extractfile(main+'/node_modules/@deepseek-ai/dsh-tools/lib/pipeline.js').read().decode()
    assert 'DSHA_REQUIRED_PIPELINE_POLICY_V1' in pipeline and 'await verifyGlobalConsent(exec)' in pipeline
    tar.extractall(runtime,filter='data')

# Resolve archive links without materializing absolute links into the host.
guest=args.work/'guest'
guest.mkdir(exist_ok=True)
with tarfile.open(args.work/'offline-rootfs.bin','r:gz') as tar:
    entries={}
    def normalized(name):
        while name.startswith('./'):
            name=name[2:]
        if name.startswith('/') or '..' in Path(name).parts:
            raise ValueError('UNSAFE_BASE_ARCHIVE_PATH')
        return posixpath.normpath(name)
    for member in tar.getmembers():
        entries[normalized(member.name)]=member
    def resolve(name):
        name=normalized(name)
        for _ in range(40):
            parts=name.split('/')
            changed=False
            for i in range(1,len(parts)+1):
                prefix='/'.join(parts[:i])
                m=entries.get(prefix)
                if m and (m.issym() or m.islnk()):
                    target=m.linkname
                    target=target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(prefix),target) if m.issym() else target
                    name=normalized(posixpath.normpath(posixpath.join(target,*parts[i:])))
                    changed=True
                    break
            if not changed:
                m=entries[name]
                assert m.isfile(),name
                return tar.extractfile(m).read()
        raise ValueError('ARCHIVE_LINK_CYCLE')
    node_path=next(p for p in ('usr/local/bin/node','usr/bin/node') if p in entries)
    node=resolve(node_path)
    assert node[:4]==b'\x7fELF' and int.from_bytes(node[18:20],'little')==183
    target=guest/'usr/local/bin/node'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(node)
    target.chmod(0o755)
    for name in entries:
        if not (name.startswith(('usr/lib/aarch64-linux-gnu/','lib/aarch64-linux-gnu/')) and '.so' in posixpath.basename(name)):
            continue
        if not (entries[name].isfile() or entries[name].issym() or entries[name].islnk()):
            continue
        body=resolve(name)
        for prefix in ('lib/aarch64-linux-gnu','usr/lib/aarch64-linux-gnu'):
            target=guest/prefix/posixpath.basename(name)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(body)
    phoff=struct.unpack_from('<Q',node,32)[0]
    size,count=struct.unpack_from('<HH',node,54)
    interpreter=None
    for i in range(count):
        ph=struct.unpack_from('<IIQQQQQQ',node,phoff+i*size)
        if ph[0]==3:
            interpreter=node[ph[2]:ph[2]+ph[5]].rstrip(b'\0').decode()
    assert interpreter
    target=guest/interpreter.lstrip('/')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(resolve(interpreter.lstrip('/')))
    target.chmod(0o755)
command=['qemu-aarch64','-L',str(guest),str(guest/'usr/local/bin/node')]
node_version=subprocess.check_output(command+['--version'],text=True,timeout=60).strip()
major,minor=map(int,node_version.lstrip('v').split('.')[:2])
assert major>24 or (major==24 and minor>=9),node_version
core_version=subprocess.check_output(command+[str(runtime/main/'lib/bin.js'),'--version'],text=True,timeout=120).strip()
assert core_version=='0.2.2-rc.1',core_version
result={'schema':1,'status':'PASS','applicationId':'io.github.foreveryf.dsha','versionCode':194,'dshVersion':core_version,'guestNode':node_version,'abi':'arm64-v8a','minSdk':30,'debuggable':False,'runtimeSha256':runtime_sha,'apkSha256':digest_file(args.apk),'apkBytes':args.apk.stat().st_size,'runtimeId':descriptor['runtimeId'],'activePatches':49,'qemuNodeAndCli':True,'physicalDeviceTested':False,'modelApiTested':False}
(args.work/'apk-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
