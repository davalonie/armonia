import socket,select,threading,os,sys,ipaddress
SOCK='/work/proxy.sock' if sys.argv[1]=='bridge' else sys.argv[2]
ALLOWED={'dl.google.com','maven.google.com','repo.maven.apache.org','plugins.gradle.org','repo.gradle.org','services.gradle.org','repo1.maven.org','storage.googleapis.com'}
def relay(a,b):
 try:
  while True:
   ready,_,_=select.select([a,b],[],[],60)
   if not ready: break
   for x in ready:
    d=x.recv(65536)
    if not d:return
    (b if x is a else a).sendall(d)
 except Exception as e: print('relay:',type(e).__name__,flush=True)
 finally:a.close();b.close()
def host(c):
 try:
  header=b''
  while b'\r\n\r\n' not in header and len(header)<16384: header+=c.recv(1)
  parts=header.split(b'\r\n',1)[0].decode('ascii').split()
  if len(parts)!=3 or parts[0]!='CONNECT':raise ValueError('CONNECT requerido')
  domain,port=parts[1].rsplit(':',1)
  if domain not in ALLOWED or port!='443':raise ValueError('destino no autorizado: '+domain+':'+port)
  infos=socket.getaddrinfo(domain,443,type=socket.SOCK_STREAM)
  ips=[i for i in infos if ipaddress.ip_address(i[4][0]).is_global]
  if not ips:raise ValueError('sin IP publica')
  remote=socket.socket(ips[0][0],ips[0][1],ips[0][2]);remote.settimeout(20);remote.connect(ips[0][4]);remote.settimeout(None)
  c.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n');print('CONNECT '+domain,flush=True);relay(c,remote)
 except Exception as e:
  print('DENIED '+str(e),flush=True)
  try:c.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
  except OSError:pass
  c.close()
def bridge(c):
 try:
  r=socket.socket(socket.AF_UNIX);r.connect(SOCK);relay(c,r)
 except Exception as e:print('bridge:',str(e),flush=True);c.close()
if sys.argv[1]=='host':
 try:os.unlink(SOCK)
 except FileNotFoundError:pass
 s=socket.socket(socket.AF_UNIX);s.bind(SOCK);os.chmod(SOCK,0o600);fn=host
else:
 s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',18888));fn=bridge
s.listen(50)
while True:
 c,_=s.accept();threading.Thread(target=fn,args=(c,),daemon=True).start()
