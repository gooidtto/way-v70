#!/usr/bin/env python3
import asyncio,base64,json,logging,os,re,socket,struct,urllib.parse
from pathlib import Path
PORT=int(os.environ.get("GATEWAY_PORT","8080"));D=Path(os.environ.get("DATA_DIR","/data"));SITE=Path("/opt/xray/site/index.html");TOKEN=D/"subscription_token.txt";SUB=D/"subscription.txt";RUNTIME=D/"runtime.json"
MAX_CONNECTIONS=max(16,int(os.environ.get("GATEWAY_MAX_CONNECTIONS","512")));READ_TIMEOUT=max(3.0,float(os.environ.get("GATEWAY_READ_TIMEOUT","20")));UPSTREAM_TIMEOUT=max(3.0,float(os.environ.get("GATEWAY_UPSTREAM_TIMEOUT","15")));IDLE_TIMEOUT=max(30.0,float(os.environ.get("GATEWAY_IDLE_TIMEOUT","900")));MAX_INITIAL=min(262144,max(8192,int(os.environ.get("GATEWAY_MAX_INITIAL","131072"))))
SEM=asyncio.Semaphore(MAX_CONNECTIONS);INIT_SEM=asyncio.Semaphore(max(32,MAX_CONNECTIONS*2));HTTP_METHODS=(b"GET ",b"POST ",b"HEAD ",b"PUT ",b"OPTIONS ",b"PATCH ",b"DELETE ",b"PRI * HTTP/2.0")
logging.basicConfig(level=getattr(logging,os.environ.get("GATEWAY_LOGLEVEL","INFO").upper(),logging.INFO),format="[gateway] %(levelname)s %(message)s");log=logging.getLogger("gateway")

def routes():
    try:
        rt=json.loads(RUNTIME.read_text());return rt,rt.get("routes",{})
    except Exception:return {},{}

def http_routes():
    _,rs=routes();return {v["path"]:("127.0.0.1",int(v["port"]),k) for k,v in rs.items() if v.get("path") and v.get("port")}

def tls_routes():
    _,rs=routes();return {v["sni"].lower().rstrip("."):("127.0.0.1",int(v["port"]),k) for k,v in rs.items() if v.get("sni") and v.get("port")}

def ready(p):
    try:
        with socket.create_connection(("127.0.0.1",p),timeout=1.5):return True
    except OSError:return False

def readiness():
    rt,rs=routes();n=int(rt.get("nodes",{}).get("count",0));sub=[x for x in SUB.read_text().splitlines() if x.strip()] if SUB.exists() else []
    if n not in (3,4) or len(sub)!=n or not TOKEN.exists():return False,"state"
    for name,v in rs.items():
        if v.get("port") and not ready(int(v["port"])):return False,name
    return True,"ready"

def subscription(token):
    if not TOKEN.exists() or token!=TOKEN.read_text().strip():return None,"TOKEN_INVALID"
    if not SUB.exists():return None,"SUB_MISSING"
    lines=[x.strip() for x in SUB.read_text().splitlines() if x.strip()];n=int(routes()[0].get("nodes",{}).get("count",0))
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
            while len(hs)>=4:
                total=4+int.from_bytes(hs[1:4],"big")
                if len(hs)<total:break
                s=parse_sni(bytes(hs[:total]));del hs[:total]
                if s:return s
        pos+=5+ln
    return None

async def initial(reader):
    buf=bytearray();deadline=asyncio.get_running_loop().time()+READ_TIMEOUT
    while len(buf)<MAX_INITIAL:
        try:chunk=await asyncio.wait_for(reader.read(min(8192,MAX_INITIAL-len(buf))),max(.1,deadline-asyncio.get_running_loop().time()))
        except asyncio.TimeoutError:break
        if not chunk:break
        buf.extend(chunk);b=bytes(buf)
        if b.startswith(HTTP_METHODS) and (b"\r\n\r\n" in b or len(b)>=8192):return b
        if len(b)>=5 and b[:2]==b"\x16\x03" and tls_sni(b):return b
        if b[:1]!=b"\x16":return b
    return bytes(buf)

async def pipe(reader,writer,label):
    try:
        while True:
            data=await asyncio.wait_for(reader.read(65536),IDLE_TIMEOUT)
            if not data:return
            writer.write(data);await writer.drain()
    except asyncio.CancelledError:raise
    except Exception as e:log.debug("PIPE_ERROR label=%s error=%s:%s",label,type(e).__name__,e)

async def relay(reader,writer,first,dest,label):
    upstream=None;tasks=set()
    try:
        log.info("ROUTE_SELECTED route=%s dest=%s:%s initial=%d",label,dest[0],dest[1],len(first));ur,upstream=await asyncio.wait_for(asyncio.open_connection(*dest),UPSTREAM_TIMEOUT)
        if first:upstream.write(first);await upstream.drain()
        tasks={asyncio.create_task(pipe(reader,upstream,"c2u")),asyncio.create_task(pipe(ur,writer,"u2c"))};await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
    except asyncio.TimeoutError:log.warning("UPSTREAM_TIMEOUT route=%s dest=%s:%s",label,dest[0],dest[1])
    except Exception as e:log.warning("RELAY_ERROR route=%s error=%s:%s",label,type(e).__name__,e)
    finally:
        for t in tasks:
            if not t.done():t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        for s in (writer,upstream):
            if s:
                try:s.close();await s.wait_closed()
                except Exception:pass

async def response(writer,status,body=b"",ctype=b"text/plain; charset=utf-8"):
    writer.write(b"HTTP/1.1 "+status+b"\r\nContent-Type: "+ctype+b"\r\nContent-Length: "+str(len(body)).encode()+b"\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"+body);await writer.drain()

async def http(reader,writer,data):
    first=data.split(b"\r\n",1)[0].decode("latin1","ignore");parts=first.split(" ",2);method=parts[0] if parts else "";target=parts[1] if len(parts)>1 else "";path=urllib.parse.urlsplit(target).path or "/"
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
    route=http_routes().get(path)
    if not route:
        log.warning("ROUTE_REJECT http_path=%s",path);await response(writer,b"404 Not Found",b"not found\n");return
    await relay(reader,writer,data,route[:2],route[2])

async def handle(reader,writer):
    try:
        async with INIT_SEM:data=await initial(reader)
        if not data:return
        if data.startswith(HTTP_METHODS):
            async with SEM:await http(reader,writer,data);return
        if data[:2]==b"\x16\x03":
            sni=tls_sni(data);route=tls_routes().get(sni or "")
            if route:
                async with SEM:await relay(reader,writer,data,route[:2],route[2])
            else:log.warning("ROUTE_REJECT tls_sni=%s",sni or "-")
            return
        log.warning("ROUTE_REJECT protocol=0x%s",data[:1].hex() if data else "-")
    except Exception as e:log.warning("ERROR error=%s:%s",type(e).__name__,e)
    finally:
        try:writer.close();await writer.wait_closed()
        except Exception:pass

async def main():
    server=await asyncio.start_server(handle,"0.0.0.0",PORT,limit=262144);log.warning("GATEWAY_READY=%s",PORT);log.warning("HTTP_ROUTES=%s",http_routes());log.warning("TLS_ROUTES=%s",tls_routes())
    async with server:await server.serve_forever()

if __name__=="__main__":asyncio.run(main())
