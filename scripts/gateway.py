#!/usr/bin/env python3
import asyncio,base64,json,logging,os,re,socket,struct,urllib.parse
from pathlib import Path

PORT=int(os.environ.get("GATEWAY_PORT","8080"));D=Path(os.environ.get("DATA_DIR","/data"));SITE=Path("/opt/xray/site/index.html");TOKEN=D/"subscription_token.txt";SUB=D/"subscription.txt";RUNTIME=D/"runtime.json"
MAX_CONNECTIONS=max(16,int(os.environ.get("GATEWAY_MAX_CONNECTIONS","512")));READ_TIMEOUT=max(3.0,float(os.environ.get("GATEWAY_READ_TIMEOUT","12")));UPSTREAM_TIMEOUT=max(3.0,float(os.environ.get("GATEWAY_UPSTREAM_TIMEOUT","15")));IDLE_TIMEOUT=max(30.0,float(os.environ.get("GATEWAY_IDLE_TIMEOUT","900")));MAX_INITIAL=min(262144,max(16384,int(os.environ.get("GATEWAY_MAX_INITIAL","196196"))))
SEM=asyncio.Semaphore(MAX_CONNECTIONS);INIT_SEM=asyncio.Semaphore(max(32,MAX_CONNECTIONS*2));HTTP_METHODS=(b"GET ",b"POST ",b"HEAD ",b"PUT ",b"OPTIONS ",b"PATCH ",b"DELETE ",b"PRI * HTTP/2.0")
PROXY_V2_SIG=b"\r\n\r\n\x00\r\nQUIT\n"
logging.basicConfig(level=getattr(logging,os.environ.get("GATEWAY_LOGLEVEL","INFO").upper(),logging.INFO),format="[gateway] %(levelname)s %(message)s");log=logging.getLogger("gateway")

def routes():
    try:
        rt=json.loads(RUNTIME.read_text());return rt,rt.get("routes",{})
    except Exception:return {},{}

def http_routes():
    _,rs=routes();return {v["path"]:("127.0.0.1",int(v["port"]),k) for k,v in rs.items() if v.get("path") and v.get("port")}

def tls_routes():
    _,rs=routes();return {v["sni"].lower().rstrip("."):("127.0.0.1",int(v["port"]),k) for k,v in rs.items() if v.get("sni") and v.get("port")}

def http_route(path):
    rs=http_routes();exact=rs.get(path)
    if exact:return exact
    matches=[(base,route) for base,route in rs.items() if path.startswith(base.rstrip("/")+"/")]
    return max(matches,key=lambda x:len(x[0]))[1] if matches else None

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

def parse_client_hello(body):
    try:
        if len(body)<4 or body[0]!=1:return None,None
        total=4+int.from_bytes(body[1:4],"big")
        if total>len(body):return None,None
        end=total;p=4+2+32
        if p>=end:return None,None
        sid_len=body[p];p+=1+sid_len
        if p+2>end:return None,None
        cipher_len=struct.unpack("!H",body[p:p+2])[0];p+=2+cipher_len
        if p>=end:return None,None
        comp_len=body[p];p+=1+comp_len
        if p+2>end:return None,None
        ext_len=struct.unpack("!H",body[p:p+2])[0];p+=2;stop=min(end,p+ext_len);sni=None;alpn=[]
        while p+4<=stop:
            typ,ln=struct.unpack("!HH",body[p:p+4]);p+=4
            if p+ln>stop:return sni,alpn
            ext=body[p:p+ln]
            if typ==0 and len(ext)>=5:
                q=2;e=len(ext)
                while q+3<=e:
                    nt=ext[q];nl=struct.unpack("!H",ext[q+1:q+3])[0];q+=3
                    if q+nl>e:break
                    if nt==0:
                        sni=ext[q:q+nl].decode("idna").lower().rstrip(".");break
                    q+=nl
            elif typ==16 and len(ext)>=2:
                q=2;e=len(ext)
                while q<e:
                    nl=ext[q];q+=1
                    if q+nl>e:break
                    alpn.append(ext[q:q+nl].decode("ascii","ignore"));q+=nl
            p+=ln
        return sni,alpn
    except Exception:return None,[]

def tls_metadata(buf):
    if len(buf)<5 or buf[0]!=22 or buf[1]!=3:return None,[],False
    pos=0;hs=bytearray();complete=False
    while pos+5<=len(buf):
        typ,major,minor=buf[pos],buf[pos+1],buf[pos+2];ln=struct.unpack("!H",buf[pos+3:pos+5])[0]
        if major!=3 or minor>4:return None,[],False
        if pos+5+ln>len(buf):break
        if typ==22:
            hs.extend(buf[pos+5:pos+5+ln])
            while len(hs)>=4:
                total=4+int.from_bytes(hs[1:4],"big")
                if len(hs)<total:break
                sni,alpn=parse_client_hello(bytes(hs[:total]));del hs[:total];complete=True
                if sni:return sni,alpn,True
        pos+=5+ln
    return None,[],complete

def raw_configured_sni(buf):
    _,rs=routes();lower=buf.lower();candidates=[]
    for name,v in rs.items():
        sni=(v.get("sni") or "").strip().lower().rstrip(".");port=v.get("port")
        if not sni or not port:continue
        try:needle=sni.encode("idna")
        except UnicodeError:continue
        if needle in lower:candidates.append((len(needle),sni,("127.0.0.1",int(port),name)))
    if not candidates:return None,None
    _,sni,route=max(candidates,key=lambda x:x[0]);return route,sni

def tls_route(buf):
    rs=tls_routes();sni,alpn,complete=tls_metadata(buf)
    if sni and sni in rs:return rs[sni],sni,"parser",alpn,complete
    route,sni2=raw_configured_sni(buf)
    if route:return route,sni2,"raw-sni",alpn,complete
    return None,sni or sni2,"none",alpn,complete

def strip_proxy_header(buf):
    """Strip PROXY protocol v1 or v2, preserving the original application bytes.
    Returns (payload, stripped, incomplete). The incomplete result is important:
    a v2 signature may arrive before the complete 16-byte header and must not be
    mistaken for a REALITY/TLS protocol byte.
    """
    if buf.startswith(b"PROXY "):
        end=buf.find(b"\r\n")
        if end<0:
            return buf,False,len(buf)<108
        if end>108:return buf,False,False
        return buf[end+2:],True,False
    if buf.startswith(PROXY_V2_SIG):
        if len(buf)<16:return buf,False,True
        ver_cmd=buf[12];fam_proto=buf[13];length=struct.unpack("!H",buf[14:16])[0]
        if (ver_cmd & 0xF0)!=0x20 or fam_proto not in (0x00,0x11,0x12,0x21,0x22,0x31,0x32):
            return buf,False,False
        total=16+length
        if total>MAX_INITIAL:return buf,False,False
        if len(buf)<total:return buf,False,True
        log.info("PROXY_V2_HEADER_STRIPPED bytes=%d family_proto=0x%02x",total,fam_proto)
        return buf[total:],True,False
    return buf,False,False

async def initial(reader):
    buf=bytearray();deadline=asyncio.get_running_loop().time()+READ_TIMEOUT
    while len(buf)<MAX_INITIAL:
        remaining=deadline-asyncio.get_running_loop().time()
        if remaining<=0:break
        try:chunk=await asyncio.wait_for(reader.read(min(16384,MAX_INITIAL-len(buf))),max(.1,remaining))
        except asyncio.TimeoutError:break
        if not chunk:break
        buf.extend(chunk);payload,proxied,incomplete=strip_proxy_header(bytes(buf))
        if incomplete:continue
        if proxied:
            log.info("PROXY_HEADER_STRIPPED bytes=%d",len(buf)-len(payload));buf=bytearray(payload)
        b=bytes(buf)
        if not b:continue
        if b.startswith(HTTP_METHODS) and (b"\r\n\r\n" in b or len(b)>=8192):return b
        if b[:1]==b"\x16" and len(b)>=5 and b[1]==3 and b[2]<=4:
            route,sni,method,alpn,complete=tls_route(b)
            if route and (complete or sni):return b
            continue
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
        log.info("UPSTREAM_CONNECT route=%s dest=%s:%s",label,dest[0],dest[1]);ur,upstream=await asyncio.wait_for(asyncio.open_connection(*dest),UPSTREAM_TIMEOUT)
        log.info("UPSTREAM_CONNECTED route=%s dest=%s:%s",label,dest[0],dest[1])
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
    mroute=http_route(path)
    if not mroute:
        log.warning("ROUTE_REJECT http_path=%s",path);await response(writer,b"404 Not Found",b"not found\n");return
    await relay(reader,writer,data,mroute[:2],mroute[2])

async def handle(reader,writer):
    peer=writer.get_extra_info("peername")
    try:
        async with INIT_SEM:data=await initial(reader)
        if not data:return
        log.info("INCOMING peer=%s first=0x%s bytes=%d head=%s",peer,data[:1].hex(),len(data),data[:32].hex())
        if data.startswith(HTTP_METHODS):
            async with SEM:await http(reader,writer,data);return
        if data[:1]==b"\x16" and len(data)>=3 and data[1]==3 and data[2]<=4:
            route,sni,method,alpn,complete=tls_route(data)
            log.info("TLS_ROUTE_DETECT peer=%s sni=%s alpn=%s method=%s complete=%s",peer,sni or "-",','.join(alpn) or '-',method,complete)
            if route:
                async with SEM:await relay(reader,writer,data,route[:2],route[2])
            else:log.warning("ROUTE_REJECT tls_sni=%s alpn=%s peer=%s",sni or "-",','.join(alpn) or '-',peer)
            return
        log.warning("ROUTE_REJECT protocol=0x%s peer=%s",data[:1].hex(),peer)
    except Exception as e:log.warning("ERROR peer=%s error=%s:%s",peer,type(e).__name__,e)
    finally:
        try:writer.close();await writer.wait_closed()
        except Exception:pass

async def main():
    server=await asyncio.start_server(handle,"0.0.0.0",PORT,limit=262144)
    log.warning("GATEWAY_READY=%s",PORT);log.warning("HTTP_ROUTES=%s",http_routes());log.warning("TLS_ROUTES=%s",tls_routes())
    async with server:await server.serve_forever()

if __name__=="__main__":asyncio.run(main())
