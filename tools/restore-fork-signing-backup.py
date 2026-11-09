#!/usr/bin/env python3
"""Restore the owner's signing backup locally; never run on a public CI runner.

Requires Python 3 and cryptography (python -m pip install cryptography).
Usage: python restore-fork-signing-backup.py --backup BACKUP.zip \
       --recipient-private recipient-private.pem --out PRIVATE_DIRECTORY
The recipient private key is delivered privately, never included in this repo.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import zipfile
from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--backup',type=Path,required=True)
ap.add_argument('--recipient-private',type=Path,required=True)
ap.add_argument('--out',type=Path,required=True)
a=ap.parse_args()
if a.out.exists():
    raise SystemExit('Output directory already exists; refusing to overwrite private material.')
if a.backup.suffix.lower()=='.zip':
    with zipfile.ZipFile(a.backup) as z:
        info=z.getinfo('signing-key-backup.sealed.json')
        if info.file_size>1024*1024:
            raise SystemExit('Unexpected backup size')
        b=json.loads(z.read(info))
else:
    b=json.loads(a.backup.read_text(encoding='utf-8'))
if b.get('schema')!=1 or b.get('algorithm')!='RSA-OAEP-SHA256+A256CBC+HMAC-SHA256':
    raise SystemExit('Unsupported backup format')
recipient=serialization.load_pem_private_key(a.recipient_private.read_bytes(),password=None)
key=recipient.decrypt(base64.b64decode(b['wrappedKey'],validate=True),rsa_padding.OAEP(mgf=rsa_padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
if len(key)!=64:
    raise SystemExit('Invalid wrapped key')
iv=base64.b64decode(b['iv'],validate=True)
ciphertext=base64.b64decode(b['ciphertext'],validate=True)
if len(iv)!=16:
    raise SystemExit('Invalid IV')
mac=hmac.new(key[32:],b'DSHA-FORK-KEY-BACKUP-V1\0'+iv+ciphertext,hashlib.sha256).digest()
if not hmac.compare_digest(mac,base64.b64decode(b['mac'],validate=True)):
    raise SystemExit('Backup authentication failed; refusing to decrypt')
d=Cipher(algorithms.AES(key[:32]),modes.CBC(iv)).decryptor()
padded=d.update(ciphertext)+d.finalize()
u=padding.PKCS7(128).unpadder()
p=json.loads(u.update(padded)+u.finalize())
store=base64.b64decode(p['keystoreBase64'],validate=True)
private,cert,_=load_key_and_certificates(store,p['password'].encode())
fingerprint=cert.fingerprint(hashes.SHA256()).hex()
if private is None or fingerprint!=b['certificateSha256'] or fingerprint!=p['certificateSha256'] or p['applicationId']!='io.github.foreveryf.dsha':
    raise SystemExit('Backup certificate/identity mismatch')
os.umask(0o077)
a.out.mkdir(mode=0o700,parents=True)
(a.out/'dsha-fork.p12').write_bytes(store)
(a.out/'DSHA_FORK_KEYSTORE_BASE64.txt').write_text(p['keystoreBase64'])
(a.out/'DSHA_FORK_KEYSTORE_PASSWORD.txt').write_text(p['password'])
(a.out/'README.txt').write_text('PRIVATE SIGNING BACKUP - DO NOT COMMIT OR SHARE\nApplication: io.github.foreveryf.dsha\nAlias: dsha-fork\nFormat: PKCS12\nCertificate SHA-256: '+fingerprint+'\nFor future releases, set repository Actions secrets DSHA_FORK_KEYSTORE_BASE64 and DSHA_FORK_KEYSTORE_PASSWORD using the corresponding private text files. Keep an offline encrypted backup.\n')
print('Restored and verified private signing backup. Certificate SHA-256: '+fingerprint)
