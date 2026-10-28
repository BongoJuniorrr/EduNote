#!/usr/bin/env python3
"""Create one owner credential without printing it or replacing existing access."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,default=Path('.edunote-access'));a=p.parse_args()
os.umask(0o077)
a.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
a.directory.chmod(0o700)
password_path=a.directory/'password.txt';hash_path=a.directory/'owner.htpasswd'
if password_path.exists() or hash_path.exists():
    if not (password_path.is_file() and hash_path.is_file()):raise SystemExit('Incomplete credential pair; repair deliberately before proceeding')
    password_path.chmod(0o600)
    hash_path.chmod(0o644)
    print('Existing owner credential retained.')
else:
    password=secrets.token_urlsafe(32)
    # SHA512 crypt is supported by nginx/libcrypt; use a random salt and feed
    # the secret on stdin, never in argv or shell command text.
    hashed=subprocess.run(['openssl','passwd','-6','-salt',secrets.token_hex(12),'-stdin'],input=password+'\n',text=True,capture_output=True,check=True).stdout.strip()
    password_path.write_text(password+'\n');password_path.chmod(0o600)
    hash_path.write_text('owner:'+hashed+'\n');hash_path.chmod(0o644)
    print('Owner credential created. Username: owner. Password is stored only in '+str(password_path.resolve()))
