#!/usr/bin/env python3
import asyncio,base64,json,logging,os,re,socket,struct,urllib.parse
from pathlib import Path
PORT=int(os.environ.get("GATEWAY_PORT","8080"));D=Path(os.environ.get("DATA_DIR","/data"));SITE=Path("/opt/xray/site/index.html");TOKEN=D/"subscription_token.txt";SUB=D/"subscription.txt";RUNTIME=D/"runtime.json"
MAX_CONNECTIONS=max(16,int(os.environ.get("GATEWAY_MAX_CONNECTIONS","512")));INITIAL_TIMEOUT=max(3.0,float(os.environ.get("GATEWAY_READ_TIMEOUT","20")));UPSTREAM_TIMEOUT=max(3.0,float(os.environ.get("GATEWAY_UPSTREAM_TIMEOUT","15")));IDLE_TIMEOUT=max(30.0,float(os.environ.get("GATEWAY_IDLE_TIMEOUT","900")));MAX_INITIAL=min(262144,max(8192,int(os.environ.get("GATEWAY_MAX_INITIAL","131072"))))
SEM=asyncio.Semaphore(MAX_CONNECTIONS);INIT_SEM=asyncio.Semaphore(max(32,MAX_CONNECTIONS*2));HTTP=(b"GET ",b"POST ",b"HEAD ",b"PUT ",b"OPTIONS ",b"PATCH ",b"DELETE ",b"PRI * HTTP/2.0")
logging.basicConfig(level=getattr(logging,os.environ.get("GATEWAY_LOGLEVEL","INFO").upper(),logging.INFO),format="[gateway] %(levelname)s %(message)s");log=logging.getLogger("gateway")
def runtime_routes():
    try:r=json.loads(RUNTIME.read_text());routes=r["routes"];return r,routes
    except Exception:return {},{}
def http_routes():
    _,r=runtime_routes();out={}
    for name,node in r.items():
        path=node.get("path");port=node.get("port")
        if path and port:out[path]=("127.0.0.1",int(port),name)
    return out
def tls_routes():
    _,r=runtime_routes();out={}
    for name,node in r.items():
        sni=node.get("sni");port=node.get("port")
        if sni and port:out[sni.lower().rstrip(".")]=("127.0.0.1",int(port),name)
    return out
def ready(p):
    try:
        with socket.create_connection(("127.0.0.1",p),timeout=1.5):return True
    except OSError:return False
def readiness():
    rt,r=runtime_routes();n=int(rt.get("nodes",{}).get("count",0));lines=[x for x in SUB.read_text().splitlines() if x.strip()] if SUB.exists() else []
    if n not in (3,4) or not SUB.exists() or not TOKEN.exists() or len(lines)!=n:return False,"state"
    for name,node in r.items():
        p=node.get("port")
        if p and not ready(int(p)):return False,name
    return True,"ready"
def subscription(token):
    if not TOKEN.exists() or token!=TOKEN.read_text().strip():return None,"TOKEN_INVALID"
    if not SUB.exists():return None,"SUB_MISSING"
    lines=[x.strip() for x in SUB.read_text().splitlines() if x.strip()];n=int(runtime_routes()[0].get("nodes",{}).get("count",0))
    return (base64.b64encode("\n".join(lines).encode()),"OK") if len(lines)==n else (None,"SUB_INVALID")
def parse_sni(h):
    try:
        if len(h)<4 or h[0]!=1:return None
        end=4+int.from_bytes(h[1:4],"big")
        if end>len(h):return None
        p=38;p+=1+h[p];cl=struct.unpack("!H",h[p:p+2])[0];p+=2+cl;p+=1+h[p];el=struct.unpack("!H",h[p:p+2])[0];p+=2;stop=p+el
        while p+4<=stop:
            typ,ln=struct.unpack("!HH",h[p:p+4]);p+=4
            if p+ln>stop:return None
            if typ==0 and ln>=5:
                q=p+2;e=p+ln
                while q+3<=e:
                    nt=h[q];nl=struct.unpack("!H",h[q+1:q+3])[0];q+=3
                    if q+nl>e:return None
                    if nt==0:return h[q:q+nl].decode("idna").lower().rstrip(".")
                    q+=nl
            p+=ln
    except Exception:return None
def tls_sni(buf):
    if len(buf)<5 or buf[0]!=22 or buf[1]!=3:return None
    pos=0;hs=bytearray()
    while pos+5<=len(buf):
        typ=buf[pos];ln=struct.unpack("!H",buf[pos+3:pos+5])[0]
        if buf[pos+1]!=3 or buf[pos+2] not in (0,1,2,3,4):return None
        if pos+5+ln>len(buf):break
        if typ==22:
            hs.extend(buf[pos+5:pos+5+ln])
            if len(hs)>=4:
                total=4+int.from_bytes(hs[1:4],"big")
                if len(hs)>=total:
                    s=parse_sni(bytes(hs[:total]));
                    if s:return s
        pos+=5+ln
    low=bytes(buf).lower()
    for s in tls_routes():
        if s.encode() in low:return s
    return None
async def initial(reader):
    b=bytearray();deadline=asyncio.get_running_loop().time()+INITIAL_TIMEOUT
    while len(b)<MAX_INITIAL:
        try:c=await asyncio.wait_for(reader.read(min(8192,MAX_INITIAL-len(b))),max(.1,deadline-asyncio.get_running_loop().time()))
        except asyncio.TimeoutError:break
        if not c:break
        b.extend(c);x=bytes(b)
        if x.startswith(HTTP) and (b"\r\n\r\n" in x or len(x)>=8192):return x
        if x[:2]==b"\x16\x03":
            if tls_sni(x):return x
        elif x[:1]!=b"\x16":return x
    return bytes(b)
async def pipe(r,w,d):
    try:
        while True:
            b=await asyncio.wait_for(r.read(65536),IDLE_TIMEOUT)
            if not b:return
            w.write(b);await w.drain()
    except asyncio.CancelledError:raise
    except Exception as e:log.warning("RELAY_ERROR direction=%s error=%s:%s",d,type(e).__name__,e)
async def relay(reader,writer,data,dest,label):
    up=None;tasks=set()
    try:
        log.info("ROUTE_SELECTED route=%s dest=%s:%s initial=%d",label,dest[0],dest[1],len(data));ur,up=await asyncio.wait_for(asyncio.open_connection(*dest),UPSTREAM_TIMEOUT)
        if data:up.write(data);await up.drain()
        tasks={asyncio.create_task(pipe(reader,up,"client->upstream")),asyncio.create_task(pipe(ur,writer,"upstream->client"))};await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
    except asyncio.TimeoutError:log.warning("UPSTREAM_TIMEOUT route=%s dest=%s:%s",label,dest[0],dest[1])
    except Exception as e:log.warning("RELAY_ERROR route=%s error=%s:%s",label,type(e).__name__,e)
    finally:
        for t in tasks:
            if not t.done():t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        for s in (writer,up):
            if s:
                try:s.close();await s.wait_closed()
                except Exception:pass
async def response(w,status,body=b"",ct=b"text/plain; charset=utf-8"):
    w.write(b"HTTP/1.1 "+status+b"\r\nContent-Type: "+ct+b"\r\nContent-Length: "+str(len(body)).encode()+b"\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"+body);await w.drain()
async def http(reader,writer,data):
    first=data.split(b"\r\n",1)[0].decode("latin1","ignore");parts=first.split(" ",2);method=parts[0] if parts else "";target=parts[1] if len(parts)>1 else "";path=urllib.parse.urlsplit(target).path
    if method in ("GET","HEAD") and path in ("/health","/ready"):
        if path=="/health":body,status=b"healthy\n",b"200 OK"
        else:
            ok,reason=readiness();body,status=(b"ready\n",b"200 OK") if ok else (("not-ready:"+reason+"\n").encode(),b"503 Service Unavailable")
        await response(writer,status,b"" if method=="HEAD" else body);return
    m=re.fullmatch(r"/sub/([A-Za-z0-9_-]{20,128})/?",path)
    if method in ("GET","HEAD") and m:
        payload,status=subscription(urllib.parse.unquote(m.group(1)));await response(writer,b"200 OK" if payload else (b"404 Not Found" if status=="TOKEN_INVALID" else b"500 Internal Server Error"),b"" if method=="HEAD" and payload else (payload or (status+"\n").encode()));return
    if method in ("GET","HEAD") and path in ("/","/index.html"):
        body=SITE.read_bytes();await response(writer,b"200 OK",b"" if method=="HEAD" else body,b"text/html; charset=utf-8");return
    routes=http_routes();route=routes.get(path)
    if not route:
        if not routes:return
        route=next(iter(routes.values()));label="fallback-"+route[2]
    else:label=route[2]
    await relay(reader,writer,data,route[:2],label)
async def handle(reader,writer):
    try:
        async with INIT_SEM:data=await initial(reader)
        if not data:return
        if data.startswith(HTTP):
            async with SEM:await http(reader,writer,data)
        elif data[:2]==b"\x16\x03":
            route=tls_routes().get(tls_sni(data) or "")
            if route:
                async with SEM:await relay(reader,writer,data,route[:2],route[2])
            else:log.warning("ROUTE_REJECT tls_sni=%s",tls_sni(data) or "-")
        else:log.warning("ROUTE_REJECT unknown_protocol=0x%s",data[:1].hex() if data else "-")
    except Exception as e:log.warning("ERROR error=%s:%s",type(e).__name__,e)
    finally:
        try:writer.close();await writer.wait_closed()
        except Exception:pass
async def main():
    s=await asyncio.start_server(handle,"0.0.0.0",PORT,limit=262144);log.warning("GATEWAY_READY=%s",PORT);log.warning("HTTP_ROUTES=%s",http_routes());log.warning("TLS_ROUTES=%s",tls_routes())
    async with s:await s.serve_forever()
if __name__=="__main__":asyncio.run(main())