#!/usr/bin/env python3
"""Run exact Gradle and real-runtime acceptance; never weaken source integrity gates."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
props = dict(line.split('=', 1) for line in (ROOT / 'gradle/wrapper/gradle-wrapper.properties').read_text().splitlines() if '=' in line)
url = props['distributionUrl'].replace('\\:', ':')
match = re.fullmatch(r'https://services\.gradle\.org/distributions/gradle-([0-9.]+)-bin\.zip', url)
if not match or not re.fullmatch('[a-f0-9]{64}', props.get('distributionSha256Sum', '')):
    raise SystemExit('UNRECOGNIZED_LOCKED_GRADLE_DISTRIBUTION')
version = match.group(1)
work = ROOT / 'app/build/fork-gradle'
work.mkdir(parents=True, exist_ok=True)
archive = work / ('gradle-' + version + '-bin.zip')
expected = props['distributionSha256Sum']
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1048576), b''): h.update(data)
    return h.hexdigest()
if not archive.is_file() or digest(archive) != expected:
    for source in (url.replace('services.gradle.org', 'downloads.gradle.org'), url):
        partial = archive.with_suffix('.partial')
        result = subprocess.run(['curl', '--fail', '--location', '--retry', '4', '--retry-all-errors', '--connect-timeout', '30', '--max-time', '300', '--output', str(partial), source])
        if result.returncode == 0 and digest(partial) == expected:
            partial.replace(archive)
            break
        partial.unlink(missing_ok=True)
    else:
        raise SystemExit('LOCKED_GRADLE_DOWNLOAD_OR_CHECKSUM_FAILED')
with zipfile.ZipFile(archive) as z:
    for member in z.infolist():
        path = Path(member.filename)
        if path.is_absolute() or '..' in path.parts or path.parts[0] != 'gradle-' + version:
            raise SystemExit('UNSAFE_GRADLE_ARCHIVE_MEMBER')
    z.extractall(work)
binary = work / ('gradle-' + version) / 'bin/gradle'
binary.chmod(0o755)
print('Verified Gradle ' + version + ' SHA-256: ' + expected, flush=True)
managed = Path(json.loads((ROOT / 'app/build/test-runtimes/current.json').read_text())['managed'])
subprocess.run(['node', 'tools/test-dsh-022-acceptance.mjs', str(managed)], cwd=ROOT, check=True)
subprocess.run(['node', 'tools/test-storage-json-proroot-dirent.mjs', str(managed / 'node_modules/@deepseek-ai/dsh-storage-json/lib/index.js')], cwd=ROOT, check=True)
subprocess.run([sys.executable, 'tools/prepare-linux-aapt2-pin.py'], cwd=ROOT, check=True)
subprocess.run([str(binary), *sys.argv[1:]], cwd=ROOT, check=True)
playwright = managed / 'node_modules/playwright'
subprocess.run(['node', str(playwright / 'cli.js'), 'install', '--with-deps', 'chromium'], cwd=ROOT, check=True)
env = dict(os.environ, DSHA_PLAYWRIGHT=str(playwright))
subprocess.run(['node', 'tools/smoke-dsh-runtime.mjs', str(managed), 'app/build/fork-022/output/browser', '--builtins', '--browser'], cwd=ROOT, env=env, check=True)
print('PASS APK assembly and real mobile browser initialization; physical-device tests remain separate.', flush=True)
