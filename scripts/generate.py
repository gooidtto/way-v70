#!/usr/bin/env python3
import hashlib,json,os,re,secrets,urllib.parse
from pathlib import Path
D=Path(os.environ.get("DATA_DIR","/data"));D.mkdir(parents=True,exist_ok=True);C=Path(os.environ.get("XRAY_CONFIG","/etc/xray/config.json"))
UUID=os.environ["UUID"].strip();PRIV=os.environ["PRIVATE_KEY"].strip();PUB=os.environ["PUBLIC_KEY"].strip();PUBLIC=(os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("PUBLIC_DOMAIN") or "").strip();TCP_HOST=(os.environ.get("RAILWAY_TCP_PROXY_DOMAIN") or "").strip();TCP_PORT_RAW=(os.environ.get("RAILWAY_TCP_PROXY_PORT") or "").strip();APP_PORT=8080
if not PUBLIC or not TCP_HOST or not TCP_PORT_RAW:raise SystemExit("FATAL: current Railway Public Networking/TCP Proxy unavailable")
try:TCP_PORT=int(TCP_PORT_RAW)
except ValueError:raise SystemExit("FATAL: invalid current Railway TCP proxy port")
if not 1<=TCP_PORT<=65535:raise SystemExit("FATAL: invalid current Railway TCP proxy port")
def first(*names):
    for n in names:
        v=(os.environ.get(n) or "").strip()
        if v:return v
    return ""
FP=first("REALITY_FINGERPRINT") or "chrome";RAW_SNI=(first("REALITY_RAW_SNI") or "www.cloudflare.com").lower().rstrip(".");XHTTP_SNI=(first("REALITY_XHTTP_SNI") or "www.apple.com").lower().rstrip(".");RAW_TARGET=first("REALITY_RAW_TARGET") or "www.cloudflare.com:443";XHTTP_TARGET=first("REALITY_XHTTP_TARGET") or "www.apple.com:443";XPATH=first("XHTTP_PATH") or "/xhttp"
if not XPATH.startswith("/"):raise SystemExit("FATAL: XHTTP_PATH must start with /")
def env_first(*names):return first(*names)
CF_TOKEN=env_first("CLOUDFLARE_TUNNEL_TOKEN","CF_TUNNEL_TOKEN","TUNNEL_TOKEN");CF_ID=env_first("CLOUDFLARE_TUNNEL_ID","CF_TUNNEL_ID","TUNNEL_ID");CF_HOST=env_first("CLOUDFLARE_PUBLIC_HOSTNAME","CF_PUBLIC_HOSTNAME").lower();CF_ORIGIN_RAW=env_first("CLOUDFLARE_ORIGIN_SERVICE","CF_ORIGIN_SERVICE");CF_PORT_RAW=env_first("WS_PORT","CLOUDFLARE_WS_PORT","CF_WS_PORT");CF_PATH=env_first("WS_PATH","CLOUDFLARE_WS_PATH","CF_WS_PATH");CFV=(CF_TOKEN,CF_ID,CF_HOST,CF_ORIGIN_RAW,CF_PORT_RAW,CF_PATH)
CF_INVALID="";CF=all(CFV);CF_PORT=None
if any(CFV) and not CF:CF_INVALID="incomplete Cloudflare Variables: fourth node disabled"
if CF:
    try:CF_PORT=int(CF_PORT_RAW)
    except ValueError:CF=False;CF_INVALID="WS_PORT is not an integer"
    if CF and not 1<=CF_PORT<=65535:CF=False;CF_INVALID="WS_PORT outside 1-65535"
    if CF and CF_PORT in (APP_PORT,10086,10087,10088):CF=False;CF_INVALID="WS_PORT conflicts with local port"
    if CF and (not re.fullmatch(r"[A-Za-z0-9.-]+",CF_HOST) or not CF_PATH.startswith("/")):CF=False;CF_INVALID="invalid Cloudflare hostname/path"
sidfile=D/"reality_short_ids.json"
try:ids=json.loads(sidfile.read_text()) if sidfile.exists() else []
except Exception:ids=[]
ids=[str(x) for x in ids if re.fullmatch(r"[0-9a-fA-F]{2,32}",str(x))]
while len(ids)<2:ids.append(secrets.token_hex(6))
ids=ids[:2];sidfile.write_text(json.dumps(ids,indent=2)+"\n")
def reality(tag,port,network,sni,target,sid,flow=""):
    c={"id":UUID,"level":0};c["flow"]=flow if flow else c.get("flow")
    if not flow:c.pop("flow",None)
    ss={"network":network,"security":"reality","realitySettings":{"show":False,"target":target,"serverNames":[sni],"privateKey":PRIV,"shortIds":[sid]}}
    if network=="xhttp":ss["xhttpSettings"]={"path":XPATH,"mode":"auto"}
    return {"tag":tag,"listen":"127.0.0.1","port":port,"protocol":"vless","settings":{"clients":[c],"decryption":"none"},"streamSettings":ss}
def xhttp(tag,port):return {"tag":tag,"listen":"127.0.0.1","port":port,"protocol":"vless","settings":{"clients":[{"id":UUID,"level":0}],"decryption":"none"},"streamSettings":{"network":"xhttp","security":"none","xhttpSettings":{"path":XPATH,"mode":"auto"}}}
inbounds=[xhttp("node-01-xhttp",10086),reality("node-02-raw-reality",10087,"tcp",RAW_SNI,RAW_TARGET,ids[0],"xtls-rprx-vision"),reality("node-03-xhttp-reality",10088,"xhttp",XHTTP_SNI,XHTTP_TARGET,ids[1])]
if CF:inbounds.append({"tag":"node-04-cloudflare-ws","listen":"127.0.0.1","port":CF_PORT,"protocol":"vless","settings":{"clients":[{"id":UUID,"level":0}],"decryption":"none"},"streamSettings":{"network":"ws","security":"none","wsSettings":{"path":CF_PATH}}})
C.write_text(json.dumps({"log":{"loglevel":os.environ.get("XRAY_LOGLEVEL","warning")},"policy":{"levels":{"0":{"handshake":8,"connIdle":900,"uplinkOnly":2,"downlinkOnly":5}}},"inbounds":inbounds,"outbounds":[{"tag":"direct","protocol":"freedom"},{"tag":"block","protocol":"blackhole"}]},indent=2)+"\n")
def q(d):return urllib.parse.urlencode({k:str(v) for k,v in d.items() if v not in (None,"")},safe="")
def link(host,port,p,name):return f"vless://{UUID}@{host}:{port}?{q(p)}#{urllib.parse.quote(name,safe='')}"
lines=[link(PUBLIC,443,{"encryption":"none","security":"tls","sni":PUBLIC,"fp":FP,"alpn":"h2,http/1.1","type":"xhttp","path":XPATH,"mode":"auto"},"Node 01 · Railway XHTTP TLS"),link(TCP_HOST,TCP_PORT,{"encryption":"none","flow":"xtls-rprx-vision","security":"reality","sni":RAW_SNI,"fp":FP,"pbk":PUB,"sid":ids[0],"type":"tcp"},"Node 02 · REALITY Vision · Railway TCP"),link(TCP_HOST,TCP_PORT,{"encryption":"none","security":"reality","sni":XHTTP_SNI,"fp":FP,"alpn":"h2","pbk":PUB,"sid":ids[1],"type":"xhttp","path":XPATH,"mode":"auto"},"Node 03 · XHTTP REALITY · Railway TCP")]
if CF:lines.append(link(CF_HOST,443,{"encryption":"none","security":"tls","sni":CF_HOST,"fp":FP,"alpn":"http/1.1","type":"ws","host":CF_HOST,"path":CF_PATH},"Node 04 · Cloudflare WS TLS"))
count=len(lines)
previous={};rf=D/"runtime.json"
if rf.is_file():
    try:previous=json.loads(rf.read_text())
    except Exception:previous={}
oldp=str(previous.get("public_domain",""));ot=previous.get("tcp_proxy",{}) or {};oldt=f"{ot.get('domain','')}:{ot.get('port','')}" if ot else "";current=f"{TCP_HOST}:{TCP_PORT}";state="initial" if not previous else ("unchanged" if oldp==PUBLIC and oldt==current else "changed")
routes={"node01":{"path":XPATH,"port":10086},"node02":{"sni":RAW_SNI,"port":10087,"short_id":ids[0]},"node03":{"sni":XHTTP_SNI,"port":10088,"short_id":ids[1}}
if CF:routes["node04"]={"host":CF_HOST,"path":CF_PATH,"port":CF_PORT}
dist={"01":"domain-xhttp-tls","02":"raw-reality-vision","03":"xhttp-reality"};
if CF:dist["04"]="cloudflare-ws-tls"
runtime={"schema":29,"build":"standard-core-dynamic-networking","architecture":"standard-three-node-core-plus-optional-node4","nodes":{"count":count,"distribution":dist},"application_port":APP_PORT,"public_domain":PUBLIC,"tcp_proxy":{"domain":TCP_HOST,"port":TCP_PORT,"application_port":APP_PORT},"railway_networking":{"source":"current-deployment-environment","authoritative":True,"state":state,"previous_public_domain":oldp,"current_public_domain":PUBLIC,"previous_tcp_proxy":oldt,"current_tcp_proxy":current},"cloudflare":{"enabled":CF,"configured":bool(any(CFV)),"public_hostname":CF_HOST if CF else "","ws_port":CF_PORT if CF else None,"ws_path":CF_PATH if CF else "","validation_error":CF_INVALID},"routes":routes}
runtime["fingerprint"]=hashlib.sha256(json.dumps(runtime,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def atomic(p,t):
    x=p.with_name(p.name+".tmp");x.write_text(t);os.chmod(x,0o600);os.replace(x,p)
rt=json.dumps(runtime,indent=2)+"\n";atomic(D/"runtime.json",rt);atomic(D/"state.json",rt);atomic(D/"subscription.txt","\n".join(lines)+"\n");atomic(D/"manifest.json",json.dumps({"schema":29,"build":runtime["build"],"node_count":count,"distribution":dist,"railway_networking_source":"current-deployment-environment","subscription_source":"current-runtime-values","node4_enabled":CF,"node4_condition":"complete Cloudflare Variables"},indent=2)+"\n")
print("RELEASE=standard-core-dynamic-networking");print("TOPOLOGY="+str(count));print("NODE4_ENABLED="+('true' if CF else 'false'));print("NODE4_CONDITION=complete Cloudflare Variables");print("CLOUDFLARE="+('enabled' if CF else 'disabled'));print("RAILWAY_CURRENT_PUBLIC="+PUBLIC);print("RAILWAY_CURRENT_TCP="+current);print("SUBSCRIPTION_SOURCE=current-runtime-values");print("SUBSCRIPTION_COUNT="+str(count));print("NODE_01=Railway XHTTP TLS");print("NODE_02=Railway TCP REALITY Vision");print("NODE_03=Railway TCP XHTTP REALITY");print("NODE_04="+('Cloudflare WS TLS' if CF else 'disabled'))