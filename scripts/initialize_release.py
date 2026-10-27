"""Initialize private portable runtime state. Does not overwrite existing secrets."""
from pathlib import Path
import os
import secrets
os.umask(0o077)
p=Path('.env');text=p.read_text()
if not any(line.startswith('PRESENTON_POSTGRES_PASSWORD=') and line.split('=',1)[1].strip() for line in text.splitlines()):
    lines=[line for line in text.splitlines() if not line.startswith('PRESENTON_POSTGRES_PASSWORD=')]
    lines.append('PRESENTON_POSTGRES_PASSWORD='+secrets.token_urlsafe(32));p.write_text('\n'.join(lines)+'\n')
p.chmod(0o600)
for name in ['user','knowledge_bases','storage']:(Path('data')/name).mkdir(parents=True,exist_ok=True)
