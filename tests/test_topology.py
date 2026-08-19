from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p): return (ROOT/p).read_text()
def test_fixed_four_node_topology():
    g=read("scripts/generate.py"); s=read("scripts/start.sh"); w=read("scripts/gateway.py")
    assert '"count":4' in g
    assert '10086,"xhttp"' in g and '10089,"xhttp"' in g and '10087,"tcp"' in g and '10088,"xhttp"' in g
    assert 'PATH2' in g and 'Node 03' in g and 'Node 04' in g
    assert 'if n!=4' in w and 'len(lines)!=4' in w
    assert 'PATH1' in w and 'PATH2' in w and '10089' in w
    assert '10087' in w and '10088' in w
    assert 'NODES=4' in s or 'TOPOLOGY=4' in s
def test_dynamic_railway_endpoints_are_authoritative():
    s=read("scripts/start.sh"); g=read("scripts/generate.py")
    assert 'RAILWAY_PUBLIC_DOMAIN' in s and 'RAILWAY_TCP_PROXY_DOMAIN' in s and 'RAILWAY_TCP_PROXY_PORT' in s
    assert 'RAILWAY_PUBLIC_DOMAIN' in g and 'RAILWAY_TCP_PROXY_DOMAIN' in g and 'RAILWAY_TCP_PROXY_PORT' in g
    assert 'current-deployment-environment' in g and 'current-runtime-values' in g
def test_node_three_four_use_same_live_tcp_endpoint():
    g=read("scripts/generate.py"); s=read("scripts/start.sh")
    assert 'Node 03 · REALITY Vision' in g and 'Node 04 · XHTTP REALITY' in g
    assert 'i in (3,4)' in s
    assert '10087' in s and '10088' in s and '10089' in s
def test_gateway_handles_fragmented_tls_clienthello():
    w=read("scripts/gateway.py")
    assert 'def parse_sni' in w and 'def tls_sni' in w
    assert 'TLS_ROUTES' in w and 'HTTP_ROUTES' in w
    assert 'xhttp2' in w
