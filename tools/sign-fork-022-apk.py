#!/usr/bin/env python3
"""Sign the independent fork without impersonating the original publisher.

First issuance seals the key to an owner-held recipient. Later issuance requires
that same key from repository secrets; never regenerate an existing identity.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

ap=argparse.ArgumentParser()
for name in ('apk','sdk','out','sealed-out','recipient','identity'):
    ap.add_argument('--'+name,type=Path,required=True)
args=ap.parse_args()
args.out.mkdir(parents=True,exist_ok=True)
args.sealed_out.mkdir(parents=True,exist_ok=True)
os.umask(0o077)
tools=args.sdk/'build-tools/36.0.0'
assert "name='io.github.foreveryf.dsha'" in subprocess.check_output([str(tools/'aapt'),'dump','badging',str(args.apk)],text=True)
prior=json.loads(args.identity.read_text()) if args.identity.is_file() else None
store_blob=os.environ.get('DSHA_FORK_KEYSTORE_BASE64','')
password=os.environ.get('DSHA_FORK_KEYSTORE_PASSWORD','')
if prior and (not store_blob or not password):
    raise SystemExit('EXISTING_FORK_KEY_REQUIRED: refusing to generate a new signing identity')
if bool(store_blob)!=bool(password):
    raise SystemExit('INCOMPLETE_FORK_SIGNING_SECRETS')
with tempfile.TemporaryDirectory(prefix='dsha-fork-key-',dir=os.environ.get('RUNNER_TEMP')) as directory:
    private=Path(directory)
    store=private/'dsha-fork.p12'
    env=dict(os.environ)
    if store_blob:
        store.write_bytes(base64.b64decode(store_blob,validate=True))
    else:
        if not args.recipient.is_file():
            raise SystemExit('ENCRYPTED_BACKUP_RECIPIENT_REQUIRED')
        password=secrets.token_urlsafe(36)
        env['DSHA_LOCAL_SIGN_PASS']=password
        subprocess.run(['keytool','-genkeypair','-keystore',str(store),'-storetype','PKCS12','-storepass:env','DSHA_LOCAL_SIGN_PASS','-keypass:env','DSHA_LOCAL_SIGN_PASS','-alias','dsha-fork','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=Forever-Yf DSHA Fork, O=Personal Fork','-noprompt'],env=env,check=True,capture_output=True)
    env['DSHA_LOCAL_SIGN_PASS']=password
    certificate=subprocess.check_output(['keytool','-exportcert','-keystore',str(store),'-storepass:env','DSHA_LOCAL_SIGN_PASS','-alias','dsha-fork'],env=env,stderr=subprocess.PIPE)
    fingerprint=hashlib.sha256(certificate).hexdigest()
    if prior and prior['certificateSha256']!=fingerprint:
        raise SystemExit('FORK_CERTIFICATE_MISMATCH')
    if not store_blob:
        payload=json.dumps({'keystoreBase64':base64.b64encode(store.read_bytes()).decode(),'password':password,'alias':'dsha-fork','storeType':'PKCS12','applicationId':'io.github.foreveryf.dsha','certificateSha256':fingerprint},separators=(',',':')).encode()
        key=secrets.token_bytes(64)
        iv=secrets.token_bytes(16)
        ciphertext=subprocess.check_output(['openssl','enc','-aes-256-cbc','-K',key[:32].hex(),'-iv',iv.hex()],input=payload,stderr=subprocess.PIPE)
        wrapped=subprocess.check_output(['openssl','pkeyutl','-encrypt','-pubin','-inkey',str(args.recipient),'-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],input=key,stderr=subprocess.PIPE)
        mac=hmac.new(key[32:],b'DSHA-FORK-KEY-BACKUP-V1\0'+iv+ciphertext,hashlib.sha256).digest()
        backup={'schema':1,'algorithm':'RSA-OAEP-SHA256+A256CBC+HMAC-SHA256','wrappedKey':base64.b64encode(wrapped).decode(),'iv':base64.b64encode(iv).decode(),'ciphertext':base64.b64encode(ciphertext).decode(),'mac':base64.b64encode(mac).decode(),'certificateSha256':fingerprint}
        (args.sealed_out/'signing-key-backup.sealed.json').write_text(json.dumps(backup,indent=2)+'\n')
    aligned=private/'aligned.apk'
    subprocess.run([str(tools/'zipalign'),'-P','16','-f','4',str(args.apk),str(aligned)],check=True)
    signed=args.out/'dsha-0.2.2-rc.1-fork.1-arm64.apk'
    subprocess.run([str(tools/'apksigner'),'sign','--ks',str(store),'--ks-key-alias','dsha-fork','--ks-pass','env:DSHA_LOCAL_SIGN_PASS','--key-pass','env:DSHA_LOCAL_SIGN_PASS','--v1-signing-enabled','true','--v2-signing-enabled','true','--v3-signing-enabled','true','--v4-signing-enabled','false','--out',str(signed),str(aligned)],env=env,check=True)
    verification=subprocess.check_output([str(tools/'apksigner'),'verify','--min-sdk-version','23','--verbose','--print-certs',str(signed)],text=True)
    assert fingerprint in verification.lower()
    for v in (1,2,3):
        assert re.search(r'Verified using v'+str(v)+r' scheme[^\n]*: true',verification),verification
    subprocess.run([str(tools/'zipalign'),'-c','-P','16','4',str(signed)],check=True)
    (args.out/'signature-verification.txt').write_text(verification)
    (args.out/'fork-signing-certificate.der').write_bytes(certificate)
    identity={'schema':1,'applicationId':'io.github.foreveryf.dsha','alias':'dsha-fork','certificateSha256':fingerprint,'upstreamCertificate':False,'requiresExistingPrivateKeyForUpdates':True}
    args.identity.parent.mkdir(parents=True,exist_ok=True)
    args.identity.write_text(json.dumps(identity,indent=2)+'\n')
    h=hashlib.sha256()
    with signed.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):
            h.update(b)
    sha=h.hexdigest()
    (args.out/(signed.name+'.sha256')).write_text(sha+'  '+signed.name+'\n')
    print(json.dumps({'signedApk':str(signed),'sha256':sha,'certificateSha256':fingerprint,'bytes':signed.stat().st_size,'newSigningIdentity':not bool(store_blob),'encryptedBackupCreated':not bool(store_blob)}))
