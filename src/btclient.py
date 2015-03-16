#!/usr/bin/env python
__version__='0.1.1'

import libtorrent as lt
import time
import sys
import argparse
import os.path
from threading import Thread, Lock, Event
import re
import subprocess
import urlparse
import BaseHTTPServer as htserver
import types
import logging
import logging.handlers
import traceback
from hachoir_metadata import extractMetadata
from hachoir_parser import createParser
import hachoir_core.config as hachoir_config
from reportlab.lib.colors import yellow
import urllib
import SocketServer
hachoir_config.quiet = True


logger=logging.getLogger()

VIDEO_EXTS={'.avi':'video/x-msvideo','.mp4':'video/mp4','.mkv':'video/x-matroska',
            '.m4v':'video/mp4','.mov':'video/quicktime', '.mpg':'video/mpeg','.ogv':'video/ogg', 
            '.ogg':'video/ogg', '.webm':'video/webm'}

RANGE_RE=re.compile(r'bytes=(\d+)-')

def get_duration(fn):
    p=createParser(unicode(fn))
    m=extractMetadata(p)
    if m:
        return m.getItem('duration',0) and m.getItem('duration',0).value


def parse_range(range):  # @ReservedAssignment
    if range:
        m=RANGE_RE.match(range)
        if m:
            try:
                return int(m.group(1))
            except:
                pass
    return 0


class StreamServer(SocketServer.ThreadingMixIn, htserver.HTTPServer):
    daemon_threads = True
    def __init__(self, address, handler_class, tfile=None, allow_range=True):
        htserver.HTTPServer.__init__(self,address,handler_class)
        self.file=tfile
        self._running=True
        self.allow_range=allow_range
        
    def stop(self):
        self._running=False
        
    def set_file(self,f):
        self.file=f
        
    def serve(self, w=0.1):
        while self._running:
            try:
                self.handle_request()
                time.sleep(w)
            except Exception,e:
                print >>sys.stderr, str(e)
            
    def run(self):
        self.timeout=0.1
        t=Thread(target=self.serve, args=[0.1], name='HTTP Server')
        t.daemon=True
        t.start()
        
class BTFileHandler(htserver.BaseHTTPRequestHandler):
    
    def do_GET(self):
        
        if self.do_HEAD(only_header=False):
            self.server.file.seek( self._offset)
            while True:
                buf= self.server.file.read(1024) 
                if buf:
                    if logger.level<= logging.DEBUG:
                        logger.debug('Sending %d bytes', len(buf))
                    self.wfile.write(buf)
                else:
                    if logger.level<= logging.DEBUG:
                        logger.debug('Finished sending data')
                    break
            
    def _file_info(self):
        size=self.server.file.size
        ext=os.path.splitext(self.server.file.path)[1]
        mime=VIDEO_EXTS.get(ext)
        if not mime:
            mime='application/octet-stream'
        return size,mime
            
    def do_HEAD(self, only_header=True):
        parsed_url=urlparse.urlparse(self.path)
        if urllib.unquote_plus(parsed_url.path)=='/'+self.server.file.path:
            self._offset=0
            size,mime = self._file_info()
            range=None  # @ReservedAssignment
            if self.server.allow_range:
                range=parse_range(self.headers.get('Range', None))  # @ReservedAssignment
                if range:
                    size=size-range
                    if size <0:  size=0
                    self._offset=range
                    range=(range,size,size)  # @ReservedAssignment
            self.send_resp_header(mime, size, range, only_header)
            return True
        else:
            logger.error('Requesting wrong path %s, but file is', parsed_url.path, '/'+self.server.file.path)
            self.send_error(404, 'Not Found')
        
    def send_resp_header(self, cont_type, cont_length, range=False, only_header=False):  # @ReservedAssignment
        #logger.debug('range is %s'% str(range))
        self.send_response(200, 'OK')
        self.send_header('Content-Type', cont_type)
        self.send_header('Content-Length', cont_length)
        self.send_header('Connection', 'close')
        self.send_header('transferMode.dlna.org', 'Streaming')
        self.send_header('contentFeatures.dlna.org', 'DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000')
        if self.server.allow_range:
            self.send_header('Accept-Ranges', 'bytes')
        else:
            self.send_header('Accept-Ranges', 'none')
        if self.server.allow_range and range:
            if isinstance(range, (types.TupleType, types.ListType)) and len(range)==3:
                self.send_header('Content-Range', 'bytes %d-%d/%d' % range)    
        if not only_header: self.end_headers()
        
    def log_message(self, format, *args):  # @ReservedAssignment
        logger.debug(format, *args)
        
    
            

class BTClient(object):
    def __init__(self, path_to_store, 
                 port_min= 6881, 
                 port_max=6891,
                 start_stream_limit=0.05):
        self._base_path=path_to_store
        self._torrent_params={'save_path':path_to_store,
                              'storage_mode':lt.storage_mode_t.storage_mode_compact
                              }
        self._start_stream_limit=start_stream_limit
        self._ses=lt.session()
        self._ses.listen_on(port_min, port_max)
        self._start_services()
        self._th=None
        self._monitor= BTClient.Monitor()
        self._monitor.add_listener(self._check_ready)
        self._ready=False
        self._file = None
    
    
    @property
    def file(self):
        return self._file
        
    def on_file_ready(self, action):
        self._on_ready=action
        
    def is_file_ready(self):
        return self._ready 
        
    def _check_ready(self, s):
        if s.state>=3 and  s.state <= 5 and not self._file and s.progress>0.01:
            self._meta_ready(self._th.get_torrent_info())
        elif self._file and not self._ready:
            progress=float(s.total_wanted_done)/s.total_wanted
            if progress >= self._start_stream_limit and self._file.done>= min(10000000,self._file.size):
                done=progress>=1.0
                r=self._file.byte_rate
                if r:
                    self._monitor.set_desired_rate(r)
                if done or not r or r < s.download_rate:
                    self._ready=True
                    if self._on_ready:
                        self._on_ready(self._file, done)
        if self._file and s.state>=3:
            idx=self._file.index
            prog=self._th.file_progress()[idx]
            self._file.update_done(prog)
            
            
    def _choose_file(self, files, search=None):    
        videos=filter(lambda f: VIDEO_EXTS.has_key(os.path.splitext(f.path)[1]), files)
        if search:
            videos=filter(lambda f: re.match(search, f.path), videos)
        f = sorted(videos, key=lambda f:f.size)[-1]
        l= [0 for _i in xrange(len(files))]
        i = files.index(f)
        l[i]=1
        f.index=i
        return f,l
            
    def _meta_ready(self, meta):
        f, priorities=self._choose_file(meta.files())
        if os.path.exists(os.path.join(self._base_path, f.path)):
            self._file=BTFile(f.path, self._base_path, f.size, f.index)
            self._th.prioritize_files(priorities)
            
    def add_listener(self, cb):
        self._monitor.add_listener(cb)
            
    def remove_listener(self,cb):
        self._monitor.remove_listener(cb)
        
    def start_torrent(self, uri):
        if self._th:
            raise Exception('Torrent is already started')
        
        if uri.startswith('http://' or uri.startswith('https://')):
            tp={'url':uri}
        elif uri.startswith('magnet:'):
            tp={'url':uri}
        elif os.path.isfile(uri):
            info = lt.torrent_info(uri)
            tp={'ti':info}
        else:
            raise ValueError("Invalid torrent")
        
        tp.update(self._torrent_params)
        self._th = self._ses.add_torrent(tp)
        self._th.set_sequential_download(True)
#         if tp.has_key('ti'):
#             self._meta_ready(self._th.get_torrent_info())
        
        self._monitor.monitor(self._th)
        
    def stop(self):
        self._monitor.stop()
        self._monitor.join()
        

    def _start_services(self):
        self._ses.start_dht()
        self._ses.start_lsd()
        self._ses.start_upnp()
        self._ses.start_natpmp()
        
        
    def _stop_services(self):
        self._ses.stop_natpmp()
        self._ses.stop_upnp()
        self._ses.stop_lsd()
        self._ses.stop_dht()
    
    
    class Monitor(Thread): 
        def __init__(self):
            Thread.__init__(self,name="Torrent Status Monitor")
            self.daemon=True
            self._th=None
            self._listeners=[]
            self._lock = Lock()
            self._wait_event= Event()
            self._running=True
            self._start=self.start
            self.start=None
            self._rate=None
            
        def set_desired_rate(self, val):
            self._rate=val
            
        def monitor(self, th): 
            self._th = th
            self._start()
            
        def stop(self):
            self._running=False
            self._wait_event.set()
            
            
        def add_listener(self, cb):
            with self._lock:
                if not cb in self._listeners:
                    self._listeners.append(cb)
                
        def remove_listener(self,cb):
            with self._lock:
                try:
                    self._listeners.remove(cb)
                except ValueError:
                    pass
                
        def run(self):
            if not self._th:
                raise Exception('Invalid state, th is not initialized') 
    
            while (self._running):
                s = self._th.status()
                s.desired_rate=self._rate
                    
                with self._lock:
                    for cb in self._listeners:
                        cb(s)
                self._wait_event.wait(1.0)


class Player(object):
    
    def __init__(self,player):
        self._player=player
        self._proc=None
        self._player_options=[]
        player_name=os.path.split(player)[1]
#         if player_name =='mplayer':
#             self._player_options=['--cache=9632', '--cache-min=50']
        
        
    def start(self, f, base, stdin):
        null_dev= open(os.devnull, 'w')
        env=os.environ.copy()
        #assure not using proxy
        env.pop('http_proxy', '')
        env.pop('HTTP_PROXY', '')
        params=[self._player,]
        params.extend(self._player_options)
        if stdin:
            params.append('-')
            sin=subprocess.PIPE
        else:
            if not base.endswith(os.sep):
                base+=os.sep
            params.append(urlparse.urljoin(base, f.path))
            sin=None
        self._proc=subprocess.Popen(params, 
                                    stdout=null_dev, stderr=null_dev, 
                                    env=env, 
                                    stdin=sin)
    
    
    def write(self, data):
        self._proc.stdin.write(data)
        
    def close(self):
        if self._proc.stdin and hasattr(self._proc.stdin, 'close'):
            self._proc.stdin.close()
        
    def is_playing(self):
        if not self._proc:
            return False
        self._proc.poll()
        return self._proc.returncode is None
    
    @property
    def rcode(self):
        return self._proc.returncode if self._proc else None
        
class BTFile(object):     
    def __init__(self, path, base, size, index, on_wait=None, on_resume=None):
        self._base=base
        self.path=path
        self.size=size
        self.index=index
        self._on_wait_cb=on_wait
        self._on_resume_cb=on_resume
        
        self._done=0
        self._required=0
        self._full_path= os.path.join(base,path)
        self._wait_event= Event()
        self._file=open(self._full_path,'rb')
        
    def close(self):
        self._file and self._file.close()
    
    @property    
    def duration(self):
        return get_duration(self._full_path)
    @property    
    def byte_rate(self):
        d=self.duration
        if d:
            return self.size / d.total_seconds()
        
    def reset(self):
        self._file.seek(0)
        
    def read(self,n=None):
        if n is None:
            n= self._done-self._file.tell()
        if self._file.tell() >= self.size:
            return None
        while self._file.tell()==self._done:
            self._wait_event.clear()
            self._required=self._file.tell()+1
            self._on_wait()
            self._wait_event.wait()
        to_read=min(self._done - self._file.tell(), n)
        return self._file.read(to_read)
    
    def update_done(self,done):
        self._done=done
        if self._done>=self._required:
            self._on_resume()
            self._wait_event.set()
            
    @property        
    def done(self):
        return self._done
            
    def seek(self,n):
        if n>=self.size:
            self._file.seek(n)
            return
        while self._done < n:
            self._required = n
            self._wait_event.clear()
            self._on_wait()
            self._wait_event.wait()
        self._file.seek(n)
            
    def _on_wait(self):
        if self._on_wait_cb:
            self._on_wait_cb()    
            
    def _on_resume(self):
        if self._on_resume_cb:
            self._on_resume_cb()   
             
    def remove(self):
        os.unlink(self._full_path)
        
    def tell(self):
        return self._file.tell()
        
          
                
                
state_str = ['queued', 'checking', 'downloading metadata', \
                    'downloading', 'finished', 'seeding', 'allocating', 'checking fastresume']    
def print_status(s):
    color=''
    default='\033[39m'
    green='\033[32m'
    red='\033[31m'
    yellow='\033[33m'
    if s.progress >=1.0 or not s.desired_rate or s.state > 3:
        color=default
    elif s.desired_rate > s.download_rate:
        color=red
    elif s.download_rate > s.desired_rate and s.download_rate < s.desired_rate *1.2:
        color=yellow
    else:
        color=green
        
    
    print '\r%.2f%% (of %.1fMB) (down: %s%.1f kB/s\033[39m(need %.1f) up: %.1f kB/s s/p: %d(%d)/%d(%d)) %s' % \
        (s.progress * 100, s.total_wanted/1048576.0, 
         color, s.download_rate / 1000, s.desired_rate/1000.0 if s.desired_rate else 0.0,
         s.upload_rate / 1000, \
        s.num_seeds, s.num_complete, s.num_peers, s.num_incomplete, state_str[s.state]),
    sys.stdout.write("\033[K")
    sys.stdout.flush()
    
def print_file(f):
    print '\nFile %s (%.1fkB) is ready' %(f.path, f.size/1000.0)
    
def main(args=None):
    p=argparse.ArgumentParser()
    p.add_argument("torrent", help="Torrent file, link to file or magnet link")
    p.add_argument("-d", "--directory", default="./", help="directory to save download files")
    p.add_argument("-p", "--player", default="/usr/bin/mplayer", help="Video player executable")
    p.add_argument("-m", "--minimum", default=5.0, type=float, help="Minimum %% of file to be downloaded to start player")
    p.add_argument("--port", type=int, default=5001,help="Port for http server")
    p.add_argument("--debug-log", default='',help="File for debug logging")
    p.add_argument("--http", action='store_true', help='starts HTTP server to stream file (works with vlc, but not mplayer, which works with via stdin)')
    args=p.parse_args(args)
    if args.debug_log:
        logger.setLevel(logging.DEBUG)
        h=logging.handlers.RotatingFileHandler(args.debug_log)
        logger.addHandler(h)
    c= BTClient(args.directory, start_stream_limit=args.minimum/ 100.0)
    c.add_listener(print_status)
    player=Player(args.player)
    server=None
    if args.http:
        server=StreamServer(('127.0.0.1',args.port), BTFileHandler, allow_range=True)
    def start_play(f, finished):
        base=None
        if args.http:
            server.set_file(f)
            server.run()
            base='http://127.0.0.1:'+ str(args.port)+'/'
        sin=not args.http
        if finished:
            base=args.directory
            sin=False
            #print "\nGot all file - %s %s" % (base, f.path)
            args.play_file=True
        player.start(f,base, stdin=sin)
        
    c.on_file_ready(start_play)
    c.start_torrent(args.torrent)
    while not c.is_file_ready():
        time.sleep(1)
    f=c.file
    time.sleep(0.5) # give time for player to start
    while True:
        if not player.is_playing():
            break
        if args.http or hasattr(args, 'play_file') and args.play_file:
            time.sleep(1)
        else:
            buf=f.read(65536)
            if buf:
                try:
                    player.write(buf)
                except IOError:
                    pass
            else:
                player.close()
           
    if server:
        server.stop()    
    if player.rcode != 0:
        sys.stderr.write('Player ended with error %d\n' % player.rcode or 0)
    
if __name__=='__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
