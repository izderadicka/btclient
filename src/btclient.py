#!/usr/bin/env python
__version__='0.3.0'

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
import urllib
import SocketServer
from distutils.spawn import find_executable
import socket
import pprint
import collections
from opensubtitle import OpenSubtitles
import pickle


hachoir_config.quiet = True
logger=logging.getLogger()

VIDEO_EXTS={'.avi':'video/x-msvideo','.mp4':'video/mp4','.mkv':'video/x-matroska',
            '.m4v':'video/mp4','.mov':'video/quicktime', '.mpg':'video/mpeg','.ogv':'video/ogg', 
            '.ogg':'video/ogg', '.webm':'video/webm'}

RANGE_RE=re.compile(r'bytes=(\d+)-')

#offset from end to download first
FILE_TAIL=10000

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
        
    def handle_error(self, request, client_address):
        """Handle an error gracefully.  May be overridden.

        The default is to print a traceback and continue.

        """
        _, e, _ = sys.exc_info()
        if isinstance(e, socket.error) and e.errno==32:
            logger.debug("Socket disconnect for client %s", client_address)
            #pprint.pprint(e)
        else:
            logger.exception("HTTP Server Error")
            #TODO: remove print 
            traceback.print_exc()
            
        
class BTFileHandler(htserver.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def do_GET(self):
        
        if self.do_HEAD(only_header=False):
            with self.server.file.create_cursor() as f: 
                f.seek( self._offset)
                send_something=False
                while True:
                    buf= f.read(1024) 
                    if not send_something and logger.level<= logging.DEBUG:
                        logger.debug('Start sending data')
                        send_something=True
                    if buf:
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
                    self._offset=range
                    range=(range,size-1,size)  # @ReservedAssignment
                    logger.debug('Request range %s - (header is %s', range,self.headers.get('Range', None) )
            self.send_resp_header(mime, size, range, only_header)
            return True
        else:
            logger.error('Requesting wrong path %s, but file is %s', parsed_url.path, '/'+self.server.file.path)
            self.send_error(404, 'Not Found')
        
    def send_resp_header(self, cont_type, cont_length, range=False, only_header=False):  # @ReservedAssignment
        #logger.debug('range is %s'% str(range))
        if self.server.allow_range and range:
            self.send_response(206, 'Partial Content')
        else:
            self.send_response(200, 'OK')
        self.send_header('Content-Type', cont_type)
        self.send_header('transferMode.dlna.org', 'Streaming')
        self.send_header('contentFeatures.dlna.org', 'DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000')
        if self.server.allow_range:
            self.send_header('Accept-Ranges', 'bytes')
        else:
            self.send_header('Accept-Ranges', 'none')
        if self.server.allow_range and range:
            if isinstance(range, (types.TupleType, types.ListType)) and len(range)==3:
                self.send_header('Content-Range', 'bytes %d-%d/%d' % range)    
                self.send_header('Content-Length', range[1]-range[0]+1)
            else:
                raise ValueError('Invalid range value')
        else:
            self.send_header('Content-Length', cont_length)
        self.send_header('Connection', 'close')    
        if not only_header: self.end_headers()
        
    def log_message(self, format, *args):  # @ReservedAssignment
        logger.debug(format, *args)
     
class BaseMonitor(Thread): 
    def __init__(self, client, name):
        Thread.__init__(self,name=name)
        self.daemon=True
        self._th=None
        self._listeners=[]
        self._lock = Lock()
        self._wait_event= Event()
        self._running=True
        self._start=self.start
        self.start=None
        self._ctx={'client':client}
        self._ses=None
       
    def add_to_ctx(self,key,val):
        self._ctx[key]=val   
         
    def do_start(self, th, ses): 
        self._th = th
        self._ses=ses
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
            

class BTClient(object):
    def __init__(self, path_to_store, 
                 port_min= 6881, 
                 port_max=6891,
                 start_stream_limit=0.02,
                 state_file="~/.btclient_state"):
        self._base_path=path_to_store
        self._torrent_params={'save_path':path_to_store,
                              'storage_mode':lt.storage_mode_t.storage_mode_sparse
                              }
        self._start_stream_limit=start_stream_limit
        self._state_file=os.path.expanduser(state_file)
        self._ses=lt.session()
        if os.path.exists(self._state_file):
            with open(self._state_file) as f:
                state=pickle.load(f)
                self._ses.load_state(state)
        #self._ses.set_alert_mask(lt.alert.category_t.progress_notification|lt.alert.category_t.status_notification)
        self._ses.listen_on(port_min, port_max)
        self._start_services()
        self._th=None
        self._monitor= BTClient.Monitor(self)
        self._monitor.add_listener(self._check_ready)
        self._dispatcher=BTClient.Dispatcher(self)
        self._dispatcher.add_listener(self._update_ready_pieces)
        self._ready=False
        self._file = None
        
    
    
    @property
    def file(self):
        return self._file
        
    def on_file_ready(self, action):
        self._on_ready=action
        
    @property    
    def is_file_ready(self):
        return self._ready 
    
    def _update_ready_pieces(self, alert_type, alert):
        if alert_type == 'read_piece_alert' and self._file:
            self._file.update_piece(alert.piece, alert.buffer)
    
    def _check_ready(self, s, **kwargs):
        if s.state>=3 and  s.state <= 5 and not self._file and s.progress>0:
            self._meta_ready(self._th.get_torrent_info())
            logger.debug('Got torrent metadata and start download')
        elif self._file and not self._ready:
            progress=float(s.total_wanted_done)/s.total_wanted
            if progress >= self._start_stream_limit: #and self._file.done>= min(10000000,self._file.size):
                done=progress>=1.0
                r=self._file.byte_rate
                if r:
                    self._monitor.set_desired_rate(r)
                #if done or not r or r < s.download_rate :# if want to wait until reasonable download rate is reached
                self._ready=True
                if self._on_ready:
                    self._on_ready(self._file, done)
                    
    
            
    def _choose_file(self, files, search=None):    
        videos=filter(lambda f: VIDEO_EXTS.has_key(os.path.splitext(f.path)[1]), files)
        if search:
            videos=filter(lambda f: re.match(search, f.path), videos)
        f = sorted(videos, key=lambda f:f.size)[-1]
        i = files.index(f)
        f.index=i
        return f
            
    def _meta_ready(self, meta):
        fs=meta.files()
        files=fs if isinstance(fs, list) else [fs.at(i) for i in xrange(fs.num_files())]
        f=self._choose_file(files)
        if os.path.exists(os.path.join(self._base_path, f.path)): #TODO:may now it's not needed that file physically exists
            fmap=meta.map_file(f.index, 0, 1)
            self._file=BTFile(f.path, self._base_path, f.index, f.size, fmap, meta.piece_length(),
                              self.prioritize_piece)
            self._monitor.add_to_ctx('file', self._file)
            self.prioritize_file()
            logger.debug('File %s pieces (pc=%d, ofs=%d, sz=%d), total_pieces=%d, pc_length=%d', 
                     f.path,fmap.piece, fmap.start, fmap.length, 
                     meta.num_pieces(), meta.piece_length() )
        
    
    def prioritize_piece(self, pc, idx):
        piece_duration=1000
        min_deadline=2000
        dl=idx*piece_duration+min_deadline
        self._th.set_piece_deadline(pc, dl,lt.deadline_flags.alert_when_available)
        logger.debug("Set deadline %d for piece %d", dl,pc)
        
        # we do not need to download pieces that are lower then current index, but last two pieces are special because players sometime look at end of file
        if idx==0 and (self._file.last_piece - pc) > 2:
            for i in xrange(pc-1):
                self._th.piece_priority(i,0)
                self._th.reset_piece_deadline(i)
                
        
    def prioritize_file(self):
        meta=self._th.get_torrent_info()
        priorities=[1 if i>= self._file.first_piece and i<= self.file.last_piece else 0 \
                    for i in xrange(meta.num_pieces())]       
        self._th.prioritize_pieces(priorities)
        
    
    @property
    def pieces(self):
        return self._th.status().pieces
            
    def add_monitor_listener(self, cb):
        self._monitor.add_listener(cb)
            
    def remove_monitor_listener(self,cb):
        self._monitor.remove_listener(cb)
        
    def add_dispatcher_listener(self, cb):
        self._dispatcher.add_listener(cb)
            
    def remove_dispacher_listener(self,cb):
        self._dispatcher.remove_listener(cb)
        
    def start_torrent(self, uri):
        if self._th:
            raise Exception('Torrent is already started')
        
        if uri.startswith('http://') or uri.startswith('https://'):
            tp={'url':uri}
        elif uri.startswith('magnet:'):
            tp={'url':uri}
        elif os.path.isfile(uri):
            info = lt.torrent_info(uri)
            tp={'ti':info}
        else:
            raise ValueError("Invalid torrent %s" %uri)
        
        tp.update(self._torrent_params)
        self._th = self._ses.add_torrent(tp)
        self._th.set_sequential_download(True)
#         if tp.has_key('ti'):
#             self._meta_ready(self._th.get_torrent_info())
        
        self._monitor.do_start(self._th, self._ses)
        self._dispatcher.do_start(self._th, self._ses)
        
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
        
    def save_state(self):
        state=self._ses.save_state()
        with open(self._state_file, 'wb') as f:
            pickle.dump(state,f)
        #pprint.pprint(state)
    
    class Dispatcher(BaseMonitor):
        def __init__(self, client):
            super(BTClient.Dispatcher,self).__init__(client, name='Torrent Events Dispatcher')
            
        def run(self):
            if not self._ses:
                raise Exception('Invalid state, session is not initialized') 
    
            while (self._running):
                a=self._ses.wait_for_alert(1000)
                if a:
                    alerts= self._ses.pop_alerts()
                    for alert in alerts:
                        with self._lock:
                            for cb in self._listeners:
                                cb(lt.alert.what(alert), alert)
                   
                
            
    class Monitor(BaseMonitor): 
        def __init__(self, client):
            super(BTClient.Monitor,self).__init__(client, name="Torrent Status Monitor" )
            self._rate=None
             
        def set_desired_rate(self, val):
            self._rate=val
                
        def run(self):
            if not self._th:
                raise Exception('Invalid state, th is not initialized') 
    
            while (self._running):
                s = self._th.status()
                s.desired_rate=self._rate
                    
                with self._lock:
                    for cb in self._listeners:
                        cb(s, download_queue=self._th.get_download_queue(), ctx=self._ctx)
                self._wait_event.wait(1.0)


class Player(object):
    class Log():
        def __init__(self, p):
            self._log = collections.deque(maxlen=80)
            self._p=p
            self._stdin_reader= self._mk_thread(p.stdout, "Player stdout reader")
            self._stderr_reader= self._mk_thread(p.stderr, "Player stderr reader")
            
        def _mk_thread(self, pipe, name):
            t= Thread(target=self._read_pipe, name=name, args=(pipe,))
            t.setDaemon(True)
            t.start()
            return t
        
        def _read_pipe(self, pipe):
            while True:
                l= pipe.readline()
                if not l:
                    break
                self._log.append(l)
                
        @property        
        def log(self):
            return ''.join(self._log)
        
            
    def __init__(self,player):
        self._player=player
        self._proc=None
        self._player_options=[]
        self._log =None
        player_name=os.path.split(player)[1]
        if player_name =='mplayer':
            self._player_options=[]#'--nocache']#'--cache=8192', '--cache-min=50']
        self._player_name=player_name
        self._started=Event()
        
        
    def start(self, f, base, stdin, sub_lang=None):
        null_dev= open(os.devnull, 'w')
        env=os.environ.copy()
        #assure not using proxy
        env.pop('http_proxy', '')
        env.pop('HTTP_PROXY', '')
        params=[self._player,]
        params.extend(self._player_options)
        if sub_lang:
            try:
                params.extend(self.load_subs(f.full_path, sub_lang))
            except Exception,e:
                logger.exception('Cannot load subtitles, error: %s',e)
        if stdin:
            params.append('-')
            sin=subprocess.PIPE
        else:
            if not base.endswith(os.sep):
                base+=os.sep
            params.append(urlparse.urljoin(base, f.path))
            sin=None
        self._proc=subprocess.Popen(params, 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    env=env, 
                                    stdin=sin)
        self._log = Player.Log(self._proc)
        self._started.set()
    
    def load_subs(self, filename, lang):
        logger.debug('Downloading %s subs for %s', lang, filename)
        with OpenSubtitles(lang) as opensub:
            res=  opensub.download(filename)
            if res:
                logger.debug('Loadeded subs')
                if self._player_name=='mplayer':
                    return ['-sub', res]
                elif self._player_name=='vlc':
                    return ['--sub-file=%s'%res]
                else:
                    logger.error('Unknown player %s, cannot add subs', self._player_name)
            else:
                logger.debug('No subs found')
                return []
        
    def write(self, data):
        self._proc.stdin.write(data)
        
    def close(self):
        if self._proc.stdin and hasattr(self._proc.stdin, 'close'):
            self._proc.stdin.close()
        
    def is_playing(self):
        self._started.wait()
        self._proc.poll()
        return self._proc.returncode is None
    
    @property
    def rcode(self):
        return self._proc.returncode if self._proc else None
    
    @property
    def log(self):
        if self._log:
            return self._log.log
        else:
            return ""
        
        

    
class PieceCache(object):
    TIMEOUT=30
    size=5
    def __init__(self, btfile):   
        #self._btfile=btfile
        self._cache=[None] * self.size
        self._lock=Lock()
        self._event=Event()
        self._cache_first=btfile.first_piece
        self._piece_size= btfile.piece_size
        self._map_offset = btfile.map_piece
        self._file_size = btfile.size
        self._last_piece = btfile.last_piece
        self._request_piece=btfile.prioritize_piece
    
    def fill_cache(self, first):
        with self._lock:
            diff=first-self._cache_first
            if diff>0:
                for i in xrange(self.size):
                    if i+diff < self.size:
                        self._cache[i]=self._cache[i+diff]
                    else:
                        self._cache[i]=None
                        
            elif diff<0:
                for i in xrange(self.size-1, -1,-1):
                    if i+diff>=0:
                        self._cache[i]=self._cache[i+diff]
                    else:
                        self._cache[i]=None
                        
            self._cache_first=first
            self._event.clear()
            for i in xrange(self.size):
                if self._cache[i] is None and (self._cache_first+i) <= self._last_piece:
                    self._request_piece(self._cache_first+i, i)
                    
                    
    def add_piece(self, n, data):
        with self._lock:
            i=n-self._cache_first
            if i>=0 and i<self.size:
                self._cache[i]=data
                if i==0:
                    self._event.set()
            
        
    def has_piece(self,n):  
        with self._lock:
            i=n-self._cache_first
            if i>=0 and i<self.size:
                return not (self._cache[i] is None)
    
    def _wait_piece(self,pc_no):
        while not self.has_piece(pc_no):
            self.fill_cache(pc_no)
            #self._event.clear()
            logger.debug('Waiting for piece %d'%pc_no)
            self._event.wait(self.TIMEOUT)
            
    def _get_piece(self,n):
        with self._lock:
            i = n-self._cache_first
            if i < 0 or i >self.size:
                raise ValueError('index of of scope of current cache')
            return self._cache[i]
              
    def get_piece(self,n):
        self._wait_piece(n)
        return self._get_piece(n)
            
        
    def read(self, offset, size):
        size = min(size, self._file_size - offset)
        if not size:
            return
        
        pc_no,ofs=self._map_offset(offset)    
        data=self.get_piece(pc_no)
        pc_size=self._piece_size-ofs
        if pc_size>size:
            return data[ofs: ofs+size]
        else:
            pieces=[data[ofs:self._piece_size]]
            remains=size-pc_size
            new_head=pc_no+1
            while remains and self.has_piece(new_head):
                sz=min(remains, self._piece_size)
                data=self.get_piece(new_head)
                pieces.append(data[:sz])
                remains-=sz
                if remains:
                    new_head+=1
            self.fill_cache(new_head)
            return ''.join(pieces)
    
             
class BTCursor(object):  
    def __init__(self, btfile):  
        self._btfile=btfile
        self._pos=0
        self._cache=PieceCache(btfile)
        
    def close(self):
        self._btfile.remove_cursor(self)
        
    def read(self,n=None):
        sz=self._btfile.size - self._pos
        if not n:
            n=sz
        else:
            n=min(n,sz)
        res=self._cache.read(self._pos,n)
        if res:
            self._pos+=len(res)
        return res
        
    
    def seek(self,n):
        if n>=self._btfile.size:
            raise ValueError('Seeking beyond file size')
        elif n<0:
            raise ValueError('Seeking negative')
        self._pos=n
        
    def update_piece(self,n,data):
        self._cache.add_piece(n,data)
        
    def __enter__(self):
        return self
    
    def __exit__(self,exc_type, exc_val, exc_tb):
        self.close()
    
              
class BTFile(object):     
    def __init__(self, path, base, index, size, fmap, piece_size, prioritize_fn):
        self._base=base
        self.path=path
        self.size=size
        self.piece_size=piece_size
        self.index=index
        self.first_piece=fmap.piece
        self.last_piece=self.first_piece + (size+fmap.start) // piece_size
        self.offset=fmap.start
        self._full_path= os.path.join(base,path)
        self._cursors=[]
        self._prioritize_fn=prioritize_fn
        self._lock=Lock()
        self._duration=None
        self._rate=None
        self._piece_duration=None
        
    
    def add_cursor(self,c):
        with self._lock:
            self._cursors.append(c)
        
    def remove_cursor(self, c):
        with self._lock:
            self._cursors.remove(c)
        
    def create_cursor(self):
        c = BTCursor(self)  
        self.add_cursor(c)
        return c
    
    def map_piece(self, ofs):
        return  self.first_piece+ (ofs+self.offset) // self.piece_size , \
                self.first_piece+ (ofs+self.offset) % self.piece_size
                
    def prioritize_piece(self, n, idx):  
        self._prioritize_fn(n,idx)       
        
    @property
    def full_path(self):
        return self._full_path    
        
    @property    
    def duration(self):
        if not self._duration:
            self._duration= get_duration(self._full_path)
        return self._duration
    
    @property
    def piece_duration_ms(self):
        if not self._piece_duration:
            if self.byte_rate:
                self._piece_duration=self.piece_size/ self.byte_rate / 1000
                
        return self._piece_duration
    
    @property    
    def byte_rate(self):
        if not self._rate:
            d=self.duration
            if d:
                self._rate= self.size / d.total_seconds()
        return self._rate
            
    def remove(self):
        os.unlink(self._full_path)
        
    def update_piece(self, n, data):
        for c in self._cursors:
            c.update_piece(n,data)
        
    
    def __str__(self):
        return self._full_path
        
          
                
                
state_str = ['queued', 'checking', 'downloading metadata', \
                    'downloading', 'finished', 'seeding', 'allocating', 'checking fastresume']    
def print_status(s,download_queue, ctx):
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
        
    status = state_str[s.state]
    print '\r%.2f%% (of %.1fMB) (down: %s%.1f kB/s\033[39m(need %.1f) up: %.1f kB/s s/p: %d(%d)/%d(%d)) %s' % \
        (s.progress * 100, s.total_wanted/1048576.0, 
         color, s.download_rate / 1000, s.desired_rate/1000.0 if s.desired_rate else 0.0,
         s.upload_rate / 1000, \
        s.num_seeds, s.num_complete, s.num_peers, s.num_incomplete, status),
    sys.stdout.write("\033[K")
    sys.stdout.flush()

def debug_download_queue(s,download_queue,ctx):
    if s.state!= 3:
        return
    if ctx.has_key('file'):
        first=ctx['file'].first_piece
    else:
        first=0
    q=map(lambda x: x['piece_index']+first,download_queue)
    logger.debug('Download queue: %s', q)
    
def debug_alerts(type, alert):
    logger.debug("Alert %s - %s", type, alert)
    
def print_file(f):
    print '\nFile %s (%.1fkB) is ready' %(f.path, f.size/1000.0)
    
class LangAction(argparse.Action):
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")
        super(LangAction, self).__init__(option_strings, dest, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        if len(values)!=3:
            raise ValueError('subtitles language should be 3 letters code')
        setattr(namespace, self.dest, values)
    
def main(args=None):
    p=argparse.ArgumentParser()
    p.add_argument("torrent", help="Torrent file, link to file or magnet link")
    p.add_argument("-d", "--directory", default="./", help="directory to save download files")
    p.add_argument("-p", "--player", default="mplayer", choices=["mplayer","vlc"], help="Video player")
    p.add_argument("-m", "--minimum", default=1.0, type=float, help="Minimum %% of file to be downloaded to start player")
    p.add_argument("--port", type=int, default=5001,help="Port for http server")
    p.add_argument("--debug-log", default='',help="File for debug logging")
    p.add_argument("--stdin", action='store_true', help='sends video to player via stdin (no seek then)')
    p.add_argument("--print-pieces", action="store_true", help="Prints map of downloaded pieces and ends (X is downloaded piece, O is not downloaded)")
    p.add_argument("-s", "--subtitles", action=LangAction, help="language for subtitle 3 letter code eng,cze ... (will try to get subtitles from opensubtitles.org)")
    args=p.parse_args(args)
    if args.debug_log:
        logger.setLevel(logging.DEBUG)
        h=logging.handlers.RotatingFileHandler(args.debug_log)
        logger.addHandler(h)
    if args.print_pieces:
        print_pieces(args) 
    else:   
        stream(args)



        
def stream(args):
    c= BTClient(args.directory, start_stream_limit=args.minimum/ 100.0)
    try:
        c.add_monitor_listener(print_status)
        if args.debug_log:
            c.add_monitor_listener(debug_download_queue)
            c.add_dispatcher_listener(debug_alerts)
        player=find_executable(args.player)
        if not player:
            print >>sys.stderr, "Cannot find player %s on path"%args.player
        player=Player(player)
        
        server=None
        if not args.stdin:
            server=StreamServer(('127.0.0.1',args.port), BTFileHandler, allow_range=True)
            logger.debug('Started http server on port %d', args.port)
        def start_play(f, finished):
            base=None
            if not args.stdin:
                server.set_file(f)
                server.run()
                base='http://127.0.0.1:'+ str(args.port)+'/'
            sin=args.stdin
            if finished:
                base=args.directory
                sin=False
                logger.debug('File is already downloaded, will play it directly')
                args.play_file=True
            player.start(f,base, stdin=sin,sub_lang=args.subtitles)
            logger.debug('Started media player for %s', f)
            
        c.on_file_ready(start_play)
        logger.debug('Starting torrent client - libtorrent version %s', lt.version)
        c.start_torrent(args.torrent)
        while not c.is_file_ready:
            time.sleep(1)
        if not args.stdin or hasattr(args, 'play_file') and args.play_file:
            f=None
        else:
            f=c.file.create_cursor()
            
        while True:
            if not player.is_playing():
                break
            if not f:
                time.sleep(1)
            else:
                    buf=f.read(1024)
                    if buf:
                        try:
                            player.write(buf)
                            logger.debug("written to stdin")
                        except IOError:
                            pass
                    else:
                        player.close()
        if f:
            f.close()
        logger.debug('Play ended')       
        if server:
            server.stop()    
        if player.rcode != 0:
            msg='Player ended with error %d\n' % (player.rcode or 0)
            sys.stderr.write(msg)
            logger.error(msg)
        logger.debug("Player output:\n %s", player.log)
    finally:
        c.save_state()
    

def pieces_map(pieces, w):
    idx=0
    sz= len(pieces)
    w(" "*4)
    for i in xrange(10): 
        w("%d "%i)
    w('\n')
    while idx < sz:
        w("%3d "%(idx/10))
        for _c in xrange(min(10, sz-idx)):
            if pieces[idx]:
                w('X ')
            else:
                w('O ')
            idx+=1
        w('\n')

def print_pieces(args):
    def w(x):
        sys.stdout.write(x)
    c= BTClient(args.directory, start_stream_limit=args.minimum/ 100.0)
    c.start_torrent(args.torrent)
    #c.add_listener(print_status)
    start = time.time()
    while time.time()-start<60:
        if c.file:
            print "Pieces (each %.0f k) for file: %s" % (c.file.piece_size / 1024.0, c.file.path)
            pieces=c.pieces
            pieces_map(pieces,w)
            return
        time.sleep(1)
    print >>sys.stderr, "Cannot get metadata"
        
    
    
    
if __name__=='__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        logger.exception('General error')
