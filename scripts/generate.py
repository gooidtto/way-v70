#!/usr/bin/env python3
import hashlib,json,os,re,secrets,urllib.parse
from pathlib import Path
D=Path(os.environ.get('DATA_DIR','/data'));D.mkdir(parents=True,exist_ok=True);C=Path(os.environ.get('XRAY_CONFIG','/etc/xray/config.json'))
UUID=os.environ['UUID'].strip();PRIV=os.environ['PRIVATE_KEY'].strip();PUB=os.environ['PUBLIC_KEY'].strip()
PUBLIC=(os.environ.get('RAILWAY_PUBLIC_DOMAIN') or '').strip().lower().rstrip('.')
TCP_HOST=(os.environ.get('RAILWAY_TCP_PROXY_DOMAIN') or '').strip().lower().rstrip('.')
TCP_PORT_RAW=(os.environ.get('RAILWAY_TCP_PROXY_PORT') or '').strip();APP_PORT_RAW=(os.environ.get('RAILWAY_TCP_APPLICATION_PORT') or '').strip()
if not PUBLIC: raise SystemExit('FATAL: Railway Generate Domain unavailable; enable Public Networking and redeploy')
bootstrap=not (TCP_HOST and TCP_PORT_RAW and APP_PORT_RAW)
if bootstrap:
    TCP_HOST='';TCP_PORT=None;APP_PORT=None
else:
    try: TCP_PORT=int(TCP_PORT_RAW);APP_PORT=int(APP_PORT_RAW)
    except ValueError: raise SystemExit('FATAL: invalid current Railway Networking port')
    if not 1<=TCP_PORT<=65535 or not 1<=APP_PORT<=65535: raise SystemExit('FATAL: current Railway Networking port out of range')
def env(name,default=''): return (os.environ.get(name) or default).strip()
FP=env('REALITY_FINGERPRINT','chrome');RAW_SNI=env('REALITY_RAW_SNI','www.cloudflare.com').lower().rstrip('.');XHTTP_SNI=env('REALITY_XHTTP_SNI','www.apple.com').lower().rstrip('.');RAW_TARGET=env('REALITY_RAW_TARGET','www.cloudflare.com:443');XHTTP_TARGET=env('REALITY_XHTTP_TARGET','www.apple.com:443');XPATH=env('XHTTP_PATH','/xhttp')
if not XPATH.startswith('/'): raise SystemExit('FATAL: XHTTP_PATH must start with /')
CF_NAMES=('CLOUDFLARE_TUNNEL_TOKEN','CLOUDFLARE_TUNNEL_ID','CLOUDFLARE_PUBLIC_HOSTNAME','CLOUDFLARE_ORIGIN_SERVICE','WS_PORT','WS_PATH');CF={n:env(n) for n in CF_NAMES};CF_CONFIGURED=any(CF.values());CF_ENABLED=all(CF.values())
if CF_CONFIGURED and not CF_ENABLED: raise SystemExit('FATAL: incomplete Cloudflare Variables; either set all six or none')
CF_PORT=None
if CF_ENABLED:
    try: CF_PORT=int(CF['WS_PORT'])
    except ValueError: raise SystemExit('FATAL: WS_PORT is not an integer')
    if not 1<=CF_PORT<=65535 or CF_PORT in (10086,10087,10088,APP_PORT): raise SystemExit('FATAL: invalid/conflicting WS_PORT')
    if not re.fullmatch(r'[A-Za-z0-9.-]+',CF['CLOUDFLARE_PUBLIC_HOSTNAME']): raise SystemExit('FATAL: invalid Cloudflare hostname')
    if not CF['WS_PATH'].startswith('/'): raise SystemExit('FATAL: WS_PATH must start with /')
sid_file=D/'reality_short_ids.json'
try: ids=json.loads(sid_file.read_text()) if sid_file.exists() else []
except Exception: ids=[]
ids=[str(x) for x in ids if re.fullmatch(r'[0-9a-fA-F]{2,32}',str(x))]
while len(ids)<2: ids.append(secrets.token_hex(6))
ids=ids[:2];sid_file.write_text(json.dumps(ids,indent=2)+'\n')
def inbound(tag,port,network,security='none',sni=None,target=None,sid=None,flow=None,path=None):
    client={'id':UUID,'level':0};
    if flow: client['flow']=flow
    stream={'network':network,'security':security}
    if security=='reality': stream['realitySettings']={'show':False,'target':target,'serverNames':[sni],'privateKey':PRIV,'shortIds':[sid]}
    if network=='xhttp': stream['xhttpSettings']={'path':path,'mode':'auto'}
    if network=='ws': stream['wsSettings']={'path':path}
    return {'tag':tag,'listen':'127.0.0.1','port':port,'protocol':'vless','settings':{'clients':[client],'decryption':'none'},'streamSettings':stream}
inbounds=[inbound('node-01-xhttp',10086,'xhttp',path=XPATH)]
if not bootstrap:
    inbounds += [inbound('node-02-raw-reality',10087,'tcp','reality',RAW_SNI,RAW_TARGET,ids[0],'xtls-rprx-vision'),inbound('node-03-xhttp-reality',10088,'xhttp','reality',XHTTP_SNI,XHTTP_TARGET,ids[1],path=XPATH)]
    if CF_ENABLED: inbounds.append(inbound('node-04-cloudflare-ws',CF_PORT,'ws',path=CF['WS_PATH']))
C.write_text(json.dumps({'log':{'loglevel':os.environ.get('XRAY_LOGLEVEL','warning')},'policy':{'levels':{'0':{'handshake':8,'connIdle':900,'uplinkOnly':2,'downlinkOnly':5}}},'inbounds':inbounds,'outbounds':[{'tag':'direct','protocol':'freedom'},{'tag':'block','protocol':'blackhole'}]},indent=2)+'\n')
def q(params): return urllib.parse.urlencode({k:str(v) for k,v in params.items() if v not in (None,'')},safe='')
def link(host,port,params,name): return f'vless://{UUID}@{host}:{port}?{q(params)}#{urllib.parse.quote(name,safe="")}'
lines=[link(PUBLIC,443,{'encryption':'none','security':'tls','sni':PUBLIC,'fp':FP,'alpn':'h2,http/1.1','type':'xhttp','path':XPATH,'mode':'auto'},'Node 01 · Railway XHTTP TLS')]
if not bootstrap:
    lines += [link(TCP_HOST,TCP_PORT,{'encryption':'none','flow':'xtls-rprx-vision','security':'reality','sni':RAW_SNI,'fp':FP,'pbk':PUB,'sid':ids[0],'type':'tcp'},'Node 02 · REALITY Vision · Railway TCP'),link(TCP_HOST,TCP_PORT,{'encryption':'none','security':'reality','sni':XHTTP_SNI,'fp':FP,'alpn':'h2','pbk':PUB,'sid':ids[1],'type':'xhttp','path':XPATH,'mode':'auto'},'Node 03 · XHTTP REALITY · Railway TCP')]
    if CF_ENABLED: lines.append(link(CF['CLOUDFLARE_PUBLIC_HOSTNAME'],443,{'encryption':'none','security':'tls','sni':CF['CLOUDFLARE_PUBLIC_HOSTNAME'],'fp':FP,'alpn':'http/1.1','type':'ws','host':CF['CLOUDFLARE_PUBLIC_HOSTNAME'],'path':CF['WS_PATH']},'Node 04 · Cloudflare WS TLS'))
count=len(lines);dist={'01':'domain-xhttp-tls'};routes={'node01':{'path':XPATH,'port':10086}}
if not bootstrap:
    dist.update({'02':'raw-reality-vision','03':'xhttp-reality'});routes.update({'node02':{'sni':RAW_SNI,'port':10087,'short_id':ids[0]},'node03':{'sni':XHTTP_SNI,'port':10088,'short_id':ids[1]}})
    if CF_ENABLED: dist['04']='cloudflare-ws-tls';routes['node04']={'host':CF['CLOUDFLARE_PUBLIC_HOSTNAME'],'path':CF['WS_PATH'],'port':CF_PORT}
runtime={'schema':32,'build':'way-v70-standard-core','architecture':'standard-three-node-core-plus-optional-node4','bootstrap':bootstrap,'nodes':{'count':count,'distribution':dist},'application_port':APP_PORT,'public_domain':PUBLIC,'tcp_proxy':{'domain':TCP_HOST,'port':TCP_PORT,'application_port':APP_PORT},'railway_networking':{'source':'current-deployment-environment','authoritative':True,'subscription_source':'current-runtime-values','bootstrap_pending':bootstrap},'cloudflare':{'enabled':bool(CF_ENABLED and not bootstrap),'public_hostname':CF['CLOUDFLARE_PUBLIC_HOSTNAME'] if CF_ENABLED and not bootstrap else '','ws_port':CF_PORT if CF_ENABLED and not bootstrap else None,'ws_path':CF['WS_PATH'] if CF_ENABLED and not bootstrap else ''},'routes':routes}
runtime['fingerprint']=hashlib.sha256(json.dumps(runtime,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def atomic(path,text):
    tmp=path.with_name(path.name+'.tmp');tmp.write_text(text);os.chmod(tmp,0o600);os.replace(tmp,path)
rt=json.dumps(runtime,indent=2)+'\n';atomic(D/'runtime.json',rt);atomic(D/'state.json',rt);atomic(D/'subscription.txt','\n'.join(lines)+'\n');atomic(D/'manifest.json',json.dumps({'schema':32,'build':runtime['build'],'node_count':count,'distribution':dist,'railway_networking_source':'current-deployment-environment','subscription_source':'current-runtime-values','node4_enabled':bool(CF_ENABLED and not bootstrap),'bootstrap':bootstrap},indent=2)+'\n')
print('RELEASE=way-v70-standard-core');print('BOOTSTRAP_MODE='+('node01-only' if bootstrap else 'disabled'));print('TOPOLOGY='+str(count));print('NODE4_ENABLED='+str(bool(CF_ENABLED and not bootstrap)).lower());print('CLOUDFLARE='+('enabled' if CF_ENABLED and not bootstrap else 'disabled'));print('RAILWAY_CURRENT_PUBLIC='+PUBLIC);print('RAILWAY_CURRENT_TCP='+(TCP_HOST+':'+str(TCP_PORT) if not bootstrap else 'pending'));print('RAILWAY_CURRENT_APP_PORT='+(str(APP_PORT) if APP_PORT else 'pending'));print('SUBSCRIPTION_SOURCE=current-runtime-values');print('SUBSCRIPTION_COUNT='+str(count));print('NODE_ORDER='+','.join(dist.keys()))
