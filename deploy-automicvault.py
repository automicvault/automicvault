#!/usr/bin/env python3
"""Deploy site/ to automicvault Cloudflare Pages via raw API (MD5 asset keys)."""
import hashlib, json, os, sys, base64, mimetypes, urllib.request, urllib.error, uuid

DIST = '/root/automic-vault-source/site'
TOK  = open(os.path.expanduser('~/.cf_tok')).read().strip()
ACC  = open(os.path.expanduser('~/.cf_acct')).read().strip()
PROJ = 'automicvault'
API  = 'https://api.cloudflare.com/client/v4'

def req(url, method='GET', body=None, headers=None, raw=False):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = body if raw else json.dumps(body).encode()
        if not raw: h['content-type'] = 'application/json'
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f'HTTP {e.code} on {method} {url}: {e.read().decode()[:600]}')

AUTH = {'Authorization': f'Bearer {TOK}'}

# 1. upload token (JWT)
ut = req(f'{API}/accounts/{ACC}/pages/projects/{PROJ}/upload-token', headers=AUTH)['result']['jwt']
JWT = {'Authorization': f'Bearer {ut}'}

# 2. build manifest (MD5 keys) + collect blobs
files, manifest = {}, {}
for root, _, names in os.walk(DIST):
    for n in sorted(names):
        p = os.path.join(root, n)
        rel = '/' + os.path.relpath(p, DIST).replace(os.sep, '/')
        blob = open(p, 'rb').read()
        md5 = hashlib.md5(blob).hexdigest()
        files[md5] = (rel, blob)
        manifest[rel] = md5
        print(f'  {rel}  [{md5[:8]}]')

print(f'to upload: {len(files)} files')

# 3. upload all assets in batches of 25
BATCH = 25
missing = list(files)
for i in range(0, len(missing), BATCH):
    chunk = [{
        'key': h,
        'value': base64.b64encode(files[h][1]).decode(),
        'metadata': {'contentType': mimetypes.guess_type(files[h][0])[0] or 'application/octet-stream'},
        'base64': True
    } for h in missing[i:i+BATCH]]
    up = req('https://api.cloudflare.com/client/v4/pages/assets/upload', 'POST', chunk, JWT)
    assert up.get('success'), up
    print(f'  uploaded batch {i//BATCH+1}: {up["result"]["successful_key_count"]} keys')

# 4. deploy via multipart form
boundary = uuid.uuid4().hex
fields = {
    'manifest':       json.dumps(manifest),
    'branch':         'main',
    'commit_message': 'Deploy Automic Vault site',
    'commit_hash':    '6ea6ab62d13d7dfb6ce8a7b2d9126312e67d9119',
    'commit_dirty':   'false',
}
parts = b''
for k, v in fields.items():
    parts += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
parts += f'--{boundary}--\r\n'.encode()

dep = req(
    f'{API}/accounts/{ACC}/pages/projects/{PROJ}/deployments',
    'POST', parts,
    {'Authorization': f'Bearer {TOK}', 'content-type': f'multipart/form-data; boundary={boundary}'},
    raw=True
)
assert dep.get('success'), dep
res = dep['result']
print(f'\ndeploy_id={res["id"]}')
print(f'preview_url={res["url"]}')
print(f'aliases={res.get("aliases", [])}')
