#!/usr/bin/env python
__version__='0.2.0'

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
from math import floor


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
                if logger.level<= logging.DEBUG:
                        logger.debug('Start sending data')
                while True:
                    buf= f.read(1024) 
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
        #self.send_header('transferMode.dlna.org', 'Streaming')
        #self.send_header('contentFeatures.dlna.org', 'DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000')
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
        
    
            

class BTClient(object):
    def __init__(self, path_to_store, 
                 port_min= 6881, 
                 port_max=6891,
                 start_stream_limit=0.02):
        self._base_path=path_to_store
        self._torrent_params={'save_path':path_to_store,
                              'storage_mode':lt.storage_mode_t.storage_mode_sparse
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
        self._has_tail=False
    
    
    @property
    def file(self):
        return self._file
        
    def on_file_ready(self, action):
        self._on_ready=action
        
    def is_file_ready(self):
        return self._ready 
        
    def _check_ready(self, s, **kwargs):
        if s.state>=3 and  s.state <= 5 and not self._file and s.progress>0:
            self._meta_ready(self._th.get_torrent_info())
            logger.debug('Got torrent metadata and start download')
        elif not self._has_tail and self._file and self._file.can_read(self._file.size-1,1):
            self._has_tail=True
            self.prioritize(0)
            logger.debug('Got file %s tail', self._file.path)
        elif self._has_tail and self._file and not self._ready:
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
        if self._file and s.state>=3:
#             idx=self._file.index
#             prog=self._th.file_progress()[idx]
            self._file.update_pieces(s.pieces)
            
            
    def _choose_file(self, files, search=None):    
        videos=filter(lambda f: VIDEO_EXTS.has_key(os.path.splitext(f.path)[1]), files)
        if search:
            videos=filter(lambda f: re.match(search, f.path), videos)
        f = sorted(videos, key=lambda f:f.size)[-1]
        i = files.index(f)
        f.index=i
        return f
            
    def _meta_ready(self, meta):
        f=self._choose_file(meta.files())
        if os.path.exists(os.path.join(self._base_path, f.path)): #TODO:may now it's not needed that file physically exists
            fmap=meta.map_file(f.index, 0, f.size)
            pieces=self._th.status().pieces
            self._file=BTFile(f.path, self._base_path, f.index,fmap, pieces, meta.piece_length(),
                              self.prioritize)
            self._monitor.add_to_ctx('file', self._file)
            # video player usually checks tail of file - last few ks - so get them first
            self.prioritize(self._file.size - FILE_TAIL)
        logger.debug('File %s pieces (pc=%d, ofs=%d, sz=%d), total_pieces=%d, pc_length=%d', 
                     f.path,fmap.piece, fmap.start, fmap.length, 
                     meta.num_pieces(), meta.piece_length() )
        
    def prioritize(self,offset, size=None):
        first_piece=self._file.piece_no_abs(offset)
        last_piece=None
        if size:
            last_piece=self._file.piece_no_abs(offset+size)
        meta=self._th.get_torrent_info()
        priorities=[0 if i < first_piece or (last_piece is not None and i>last_piece) 
                    else 1 for i in xrange(meta.num_pieces())]
        self._th.prioritize_pieces(priorities)
        
            
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
            self._ctx={}
            
        def add_to_ctx(self,key,val):
            self._ctx[key]=val   
             
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
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    env=env, 
                                    stdin=sin)
        self._log = Player.Log(self._proc)
    
    
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
    
    @property
    def log(self):
        if self._log:
            return self._log.log
        else:
            return ""
        
        
class BTPieces(object):
    def __init__(self, fmap, pieces, piece_size): 
        self._first_piece=fmap.piece
        self._offset= fmap.start
        self._size=fmap.length
        self._piece_size=piece_size
        self._last_piece=self.piece_no(self._size-1)
        self.update_progress(pieces)
        self._ready=0
    
    @property
    def first_piece_abs(self):
        return self._first_piece
    
    @property
    def last_piece_abs(self):
        return self._first_piece + self._last_piece
        
    def _map_pieces(self, pieces):  
        res= pieces[self._first_piece:self._first_piece+self._last_piece+1]
        if len(res)!= self._last_piece+1:
            raise ValueError("Invalid pieces array - shorter then required")
        return res
    
    def piece_no(self, offset):
        if offset>=self._size:
            raise ValueError('Invalid offset - bigger then file size')
        if offset<0:
            raise ValueError('Invalid offset - negative')
        
        return int((floor(float(self._offset+offset)/ self._piece_size)))
    
    def remains(self, offset):
        return self._piece_size - self._offset+offset % self._piece_size
    
    
    def update_progress(self, pieces):
        self._pieces= self._map_pieces(pieces)
        
    @property    
    def last_piece_size(self):
        return self._offset+self._size % self._piece_size 
    
    def has_offset(self, offset):
        return self._pieces[self.piece_no(offset)]
    
    def can_read(self, offset, size):
        count=0
        if offset>=self._offset+self._size:
            raise ValueError('Invalid offset - bigger then file size')
        elif offset<0:
            raise ValueError('Invalid offset - negative')
        
        
        if size+offset>= self._size:
            size=max(0, self._size - offset)
        
        if size <= 0:
            raise ValueError('Invalid size - zero or negative')
        
        
        
        pc_start=self.piece_no(offset)
        pc_end=self.piece_no(offset+size-1)
        bytes=self.remains(offset)  # @ReservedAssignment
        pc=pc_start
        while pc <= pc_end:
            if not self._pieces[pc]:
                return min(count,size),pc
            count+=bytes
            if count>=size:
                return size,None
            pc+=1
            bytes = self._piece_size if pc<self._last_piece else self.last_piece_size  # @ReservedAssignment
            
        return min(count,size), None
    #Partial container interface 
    def __getitem__(self, i): 
        return self._pieces[i]
    
    def __setitem__(self, i, val):
        self._pieces[i]=val
        
    def __iter__(self):
        return self._pieces.__iter__()
    
    def __len__(self):
        return self._pieces.__len__()
        
class BTCursor(object):  
    def __init__(self, btfile):  
        self._btfile=btfile
        self._wait_event= Event()
        self._file=open(self._btfile.full_path,'rb')
        self._wait_for_piece=None
        
    def close(self):
        self._file and self._file.close()
        self._btfile.remove_cursor(self)
        
    def read(self,n=None):
        
        if n is None:
            n= self._btfile.size-self._file.tell()
        if self._file.tell() >= self._btfile.size:
            return None
        while True:
            to_read,wait_for_piece=self._btfile.can_read(self._file.tell(), n)
            if to_read>0:
                return self._file.read(to_read)
            self._wait_for_piece=wait_for_piece
            self._wait_event.clear()
            self._wait_event.wait()
        to_read=min(self._done - self._file.tell(), n)
        
    def wake(self,test_cb):
        if not self._wait_event.is_set() and (self._wait_for_piece is None or test_cb(self._wait_for_piece)):
            self._wait_event.set()
        
    
    def seek(self,n):
        if n>=self._btfile.size:
            raise ValueError('Seeking beyond file size')
        elif n<0:
            raise ValueError('Seeking negative')
        self._wait_for_piece=None
        self._btfile.prioritize(n)
        while not self._btfile.has_offset(n):
            self._wait_for_piece=self._btfile.piece_no(n)
            self._wait_event.clear()
            self._wait_event.wait()
        self._file.seek(n)
        
    def __enter__(self):
        return self
    
    def __exit__(self,exc_type, exc_val, exc_tb):
        self.close()
    
              
class BTFile(object):     
    def __init__(self, path, base, index, fmap, pieces, piece_size, prioritize_fn):
        self._base=base
        self.path=path
        self.size=fmap.length
        self.index=index
        self._pieces=BTPieces(fmap, pieces, piece_size)
        self._full_path= os.path.join(base,path)
        self._cursors=[]
        self._prioritize_fn=prioritize_fn
        
        self._lock=Lock()
    
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
     
    def has_offset(self, n):
        return self._pieces.has_offset(n)  
        
    def can_read(self, offset, size):
        return self._pieces.can_read(offset, size)
    
    def piece_no(self, n):
        return self._pieces.piece_no(n)
    
    def piece_no_abs(self, n):
        return self._pieces.piece_no(n) + self._pieces.first_piece_abs
    
    @property
    def first_piece(self):
        return self._pieces.first_piece_abs
    
    @property
    def last_piece(self):
        return self._pieces.last_piece_abs
        
    @property
    def full_path(self):
        return self._full_path    
        
    @property    
    def duration(self):
        return get_duration(self._full_path)
    
    @property    
    def byte_rate(self):
        d=self.duration
        if d:
            return self.size / d.total_seconds()
    
    def update_pieces(self,pieces):
        self._pieces.update_progress(pieces)
        def test_cb(i):
            return self._pieces[i]
        with self._lock:
            for c in self._cursors:
                c.wake(test_cb)
                 
    def prioritize(self, offset): 
        logger.debug("Prioritizing offset %d - ",offset)      
        self._prioritize_fn(offset)
        
    def remove(self):
        os.unlink(self._full_path)
        
    
    def __str__(self):
        return self._full_path
        
          
                
                
state_str = ['queued', 'checking', 'downloading metadata', \
                    'downloading', 'finished', 'seeding', 'allocating', 'checking fastresume']    
def print_status(s,**kwargs):
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

def debug_download_queue(s,download_queue,ctx):
    if ctx.has_key('file'):
        first=ctx['file'].first_piece
    else:
        first=0
    q=filter(lambda x: x.piece_index+first,download_queue)
    logger.debug('Download queue: %s', q)
    
def print_file(f):
    print '\nFile %s (%.1fkB) is ready' %(f.path, f.size/1000.0)
    
def main(args=None):
    p=argparse.ArgumentParser()
    p.add_argument("torrent", help="Torrent file, link to file or magnet link")
    p.add_argument("-d", "--directory", default="./", help="directory to save download files")
    p.add_argument("-p", "--player", default="mplayer", choices=["mplayer","vlc"], help="Video player")
    p.add_argument("-m", "--minimum", default=2.0, type=float, help="Minimum %% of file to be downloaded to start player")
    p.add_argument("--port", type=int, default=5001,help="Port for http server")
    p.add_argument("--debug-log", default='',help="File for debug logging")
    p.add_argument("--stdin", action='store_true', help='sends video to player via stdin (no seek then)')
    args=p.parse_args(args)
    if args.debug_log:
        logger.setLevel(logging.DEBUG)
        h=logging.handlers.RotatingFileHandler(args.debug_log)
        logger.addHandler(h)
    c= BTClient(args.directory, start_stream_limit=args.minimum/ 100.0)
    c.add_listener(print_status)
    if args.debug_log:
        c.add_listener(debug_download_queue)
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
        player.start(f,base, stdin=sin)
        logger.debug('Started media player for %s', f)
        
    c.on_file_ready(start_play)
    logger.debug('Starting torrent client')
    c.start_torrent(args.torrent)
    while not c.is_file_ready():
        time.sleep(1)
    
    time.sleep(0.5) # give time for player to start
    with c.file.create_cursor() as f:
        while True:
            if not player.is_playing():
                break
            if not args.stdin or hasattr(args, 'play_file') and args.play_file:
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
    logger.debug('Play ended')       
    if server:
        server.stop()    
    if player.rcode != 0:
        msg='Player ended with error %d\n' % (player.rcode or 0)
        sys.stderr.write(msg)
        logger.error(msg)
    logger.debug("Player output:\n %s", player.log)
    
if __name__=='__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        logger.exception('General error')
