#!/usr/bin/env python3
"""Bootstrap the missing Linux member of the already locked AAPT2 release.

Strict Gradle verification stays enabled. An existing Linux pin is never replaced.
The first Linux bytes are fetched from Google Maven and checked against Google's
published SHA-1; the stronger SHA-256 is then committed for subsequent builds.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
VERSION='9.1.1-14792394'
NAME='aapt2-'+VERSION+'-linux.jar'
URL='https://dl.google.com/dl/android/maven2/com/android/tools/build/aapt2/'+VERSION+'/'+NAME
file=ROOT/'gradle/verification-metadata.xml'
text=file.read_text(encoding='utf-8')
root=ET.fromstring(text)
namespace={'v':root.tag.partition('}')[0].lstrip('{')}
components=root.findall('v:components/v:component',namespace)
component=next(c for c in components if c.attrib=={'group':'com.android.tools.build','name':'aapt2','version':VERSION})
existing=next((a for a in component.findall('v:artifact',namespace) if a.get('name')==NAME),None)
if existing is not None:
    assert existing.find('v:sha256',namespace) is not None
    print('Linux AAPT2 already pinned; retaining existing checksum.')
    raise SystemExit(0)
work=ROOT/'app/build/fork-022/output/aapt2-provenance';work.mkdir(parents=True,exist_ok=True)
archive=work/NAME;checksum=work/(NAME+'.sha1')
for source,target in ((URL,archive),(URL+'.sha1',checksum)):
    subprocess.run(['curl','--fail','--location','--retry','3','--retry-all-errors','--connect-timeout','30','--max-time','120','--output',str(target),source],check=True)
published=checksum.read_text().strip().lower()
assert re.fullmatch('[a-f0-9]{40}',published),'INVALID_OFFICIAL_SHA1'
body=archive.read_bytes()
assert hashlib.sha1(body).hexdigest()==published,'OFFICIAL_AAPT2_DIGEST_MISMATCH'
sha256=hashlib.sha256(body).hexdigest()
anchor='      <component group="com.android.tools.build" name="aapt2" version="'+VERSION+'">'
assert text.count(anchor)==1
addition='\n         <artifact name="'+NAME+'">\n            <sha256 value="'+sha256+'" origin="Google Maven HTTPS; published SHA-1 verified by prepare-linux-aapt2-pin.py"/>\n         </artifact>'
file.write_text(text.replace(anchor,anchor+addition),encoding='utf-8')
report={'artifact':NAME,'url':URL,'publishedSha1':published,'sha256':sha256,'bytes':len(body),'strictVerificationRetained':True}
(work/'provenance.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
archive.unlink()
