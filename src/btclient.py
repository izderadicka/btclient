#!/usr/bin/env python
from _version import __version__
import libtorrent as lt
import time
import sys
import argparse
import os.path
from threading import Thread, Lock, Event
import re
import urlparse
import BaseHTTPServer as htserver
import types
import logging
import logging.handlers
import traceback
import urllib
import SocketServer
import socket
import pprint
import pickle
from cache import Cache
from player import Player
from common import AbstractFile, Hasher, BaseMonitor, BaseClient, Resolver,\
    TerminalColor
from htclient import HTClient
import plugins  # @UnresolvedImport
import signal
import json
import shutil
import subprocess

logger=logging.getLogger()

INITIAL_TRACKERS=['udp://tracker.openbittorrent.com:80',
                  'udp://tracker.istole.it:80',
                  'udp://open.demonii.com:80',
                  'udp://tracker.coppersurfer.tk:80',
                  'udp://tracker.leechers-paradise.org:6969',
                  'udp://exodus.desync.com:6969',
                  'udp://tracker.publicbt.com:80']

VIDEO_EXTS={'.avi':'video/x-msvideo','.mp4':'video/mp4','.mkv':'video/x-matroska',
            '.m4v':'video/mp4','.mov':'video/quicktime', '.mpg':'video/mpeg','.ogv':'video/ogg', 
            '.ogg':'video/ogg', '.webm':'video/webm', '.ts': 'video/mp2t', '.3gp':'video/3gpp'}

RANGE_RE=re.compile(r'bytes=(\d+)-')

#offset from end to download first
FILE_TAIL=10000

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
    def __init__(self, address, handler_class, tfile=None, allow_range=True, status_fn=None):
        htserver.HTTPServer.__init__(self,address,handler_class)
        self.file=tfile
        self._running=True
        self.allow_range=allow_range
        self.status_fn=status_fn
        
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
            with self.server.file.create_cursor(self._offset) as f: 
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
        mime=(self.server.file.mime if hasattr(self.server.file,'mime')  else None) or VIDEO_EXTS.get(ext)
        if not mime:
            mime='application/octet-stream'
        return size,mime
            
    def do_HEAD(self, only_header=True):
        parsed_url=urlparse.urlparse(self.path)
        if parsed_url.path=="/status" and self.server.status_fn:
            s=self.server.status_fn()
            status=json.dumps(s)
            self.send_response(200, 'OK')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(status))
            self._finish_header(only_header)
            if not only_header:
                self.wfile.write(status)
            return False
            
        elif self.server.file and urllib.unquote(parsed_url.path)=='/'+self.server.file.path:
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
        self._finish_header(only_header)
            
    def _finish_header(self, only_header):
        self.send_header('Connection', 'close')    
        if not only_header: self.end_headers()
        
    def log_message(self, format, *args):  # @ReservedAssignment
        logger.debug(format, *args)
     

class BTClient(BaseClient):
    def __init__(self, path_to_store, 
                 args=None,
                 state_file="~/.btclient_state",
                 **kwargs):
        super(BTClient,self).__init__(path_to_store, args=args)
        self._torrent_params={'save_path':path_to_store,
                              'storage_mode':lt.storage_mode_t.storage_mode_sparse
                              }
        self._state_file=os.path.expanduser(state_file)
        self._ses=lt.session()
        if os.path.exists(self._state_file):
            with open(self._state_file) as f:
                state=pickle.load(f)
                self._ses.load_state(state)
        #self._ses.set_alert_mask(lt.alert.category_t.progress_notification)
        self._choose_file_flag = False
        if args:
            s=lt.session_settings()
            s.download_rate_limit=int(round(args.bt_download_limit*1024))
            s.upload_rate_limit=int(round(args.bt_upload_limit*1024))
            self._ses.set_settings(s)
            self._ses.listen_on(args.listen_port_min, args.listen_port_max)
            self._choose_file_flag = args.choose_file 
        else:
            self._ses.listen_on(6881, 6891)
        self._start_services()
        self._th=None
        
        self._monitor.add_listener(self._check_ready)
        self._dispatcher=BTClient.Dispatcher(self)
        self._dispatcher.add_listener(self._update_ready_pieces)
        self._hash = None
        self._url=None
        
        if args and args.debug_log and args.trace:
            self.add_monitor_listener(self.debug_download_queue)
            self.add_dispatcher_listener(self.debug_alerts)
    
    @property    
    def is_file_complete(self):
        pcs=self._th.status().pieces[self._file.first_piece:self._file.last_piece+1]
        return all(pcs)
     
    def _update_ready_pieces(self, alert_type, alert):
        if alert_type == 'read_piece_alert' and self._file:
            self._file.update_piece(alert.piece, alert.buffer)
            
    def _check_ready(self, s, **kwargs):
        if s.state>=3 and  s.state <= 5 and not self._file and s.progress>0:
            self._meta_ready(self._th.get_torrent_info())
            logger.debug('Got torrent metadata and start download')
            self.hash=Hasher(self._file, self._on_file_ready)
            
    def _choose_file(self, files, search=None):   
        #TODO - we want to ge
        videos=filter(lambda f: VIDEO_EXTS.has_key(os.path.splitext(f.path)[1]), files)
        if search:
            videos=filter(lambda f: re.search(search, f.path, re.UNICODE|re.IGNORECASE), videos)
        if not videos:
            raise Exception('No video files in torrent')
        
        if self._choose_file_flag and len(videos)>1:
            #filter small files - these would be samples or ads - filter out all videos that are smaller then 10% of biggest video
            max_size=reduce(lambda prev,f: f.size if f.size>prev else prev, videos, 0)
            videos = filter(lambda f: float(f.size) / max_size > 0.1, videos)
            if len(videos) == 1:
                f=videos[0]
            else:
                idx=self._choose_file_dialog(videos)
                f=videos[idx]
        else:
            f = sorted(videos, key=lambda f:f.size)[-1]
        
        i = files.index(f)
        f.index=i
        return f
    
    def _choose_file_dialog(self, files):
        p=subprocess.Popen('zenity --list --title "Select video file" --text "Select best matching subtitles" --width 1024 --height 600 --column Index --column Name --column Size --hide-column=1', 
                 stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, 
                 close_fds=sys.platform!='win32')  
        choices = map(lambda i,f: '%d\n%s\n%d'%(i, f.path.replace('"',''),f.size), range(len(files)), files)
        res,_=p.communicate(b'\n'.join(choices).decode('ascii', errors='ignore'))
        res=res.split('|')[0]  #this is fix for zenity bug - double click returns column twice separated by |
        return int(res or 0)
            
    def _meta_ready(self, meta):
        fs=meta.files()
        files=fs if isinstance(fs, list) else [fs.at(i) for i in xrange(fs.num_files())]
        f=self._choose_file(files)
        #if os.path.exists(os.path.join(self._base_path, f.path)): #TODO:may now it's not needed that file physically exists
        fmap=meta.map_file(f.index, 0, 1)
        self._file=BTFile(f.path, self._base_path, f.index, f.size, fmap, meta.piece_length(),
                          self.prioritize_piece)
        
        self.prioritize_file()
        logger.debug('File %s pieces (pc=%d, ofs=%d, sz=%d), total_pieces=%d, pc_length=%d', 
                 f.path,fmap.piece, fmap.start, fmap.length, 
                 meta.num_pieces(), meta.piece_length() )
            
        self._cache.file_complete(self._th.torrent_file(), self._url if self._url and self._url.startswith('http') else None )
        
    
    def prioritize_piece(self, pc, idx):
        piece_duration=1000
        min_deadline=2000
        dl=idx*piece_duration+min_deadline
        self._th.set_piece_deadline(pc, dl,lt.deadline_flags.alert_when_available)
        logger.debug("Set deadline %d for piece %d", dl,pc)
        
        if idx==0:  # it enough when first piece if prioritize, no need to repeat it for following pieces
            # we do not need to download pieces that are lower then current index, 
            # but last x pieces are special because players often  look at end of file
            # for mp4 metadata - so in this case,  we do not want to stop download of previous pieces
            tail_pieces=9
            if (self._file.last_piece - pc) > tail_pieces:
                for i in xrange(self._file.first_piece,pc):
                    self._th.piece_priority(i,0)
                    self._th.reset_piece_deadline(i)
                
            # If we are skipping back we'd like to re-enable all pieces after this one
            # e.g. give them at least priority 1
            for i in xrange(pc+1, self._file.last_piece+1):
                self._th.piece_priority(i,1)
           
        
    def prioritize_file(self):
        meta=self._th.get_torrent_info()
        priorities=[1 if i>= self._file.first_piece and i<= self.file.last_piece else 0 \
                    for i in xrange(meta.num_pieces())]       
        self._th.prioritize_pieces(priorities)
    
    @property        
    def unique_file_id(self):
        return str(self._th.torrent_file().info_hash())    
    
    @property
    def pieces(self):
        return self._th.status().pieces
            
    def add_dispatcher_listener(self, cb):
        self._dispatcher.add_listener(cb)
            
    def remove_dispacher_listener(self,cb):
        self._dispatcher.remove_listener(cb)
        
    def remove_all_dispatcher_listeners(self):
        self._dispatcher.remove_all_listeners()
        
    def start_url(self, uri):
        if self._th:
            raise Exception('Torrent is already started')
        
        def info_from_file(uri):
            if os.access(uri,os.R_OK):
                info = lt.torrent_info(uri)
                tp= {'ti':info} 
                resume_data= self._cache.get_resume(info_hash=str(info.info_hash()))
                if resume_data:
                    tp['resume_data']=resume_data
                return tp
            raise ValueError('Invalid torrent path %s' % uri)
        
        if uri.startswith('http://') or uri.startswith('https://'):
            self._url=uri
            stored=self._cache.get_torrent(url=uri)
            if stored:
                tp=info_from_file(stored)
            else:
                tp={'url':uri}
                resume_data=self._cache.get_resume(url=uri)
                if resume_data:
                    tp['resume_data']=resume_data
        elif uri.startswith('magnet:'):
            self._url=uri
            stored=self._cache.get_torrent(info_hash=Cache.hash_from_magnet(uri))
            if stored:
                tp=info_from_file(stored)
            else:
                tp={'url':uri}
                resume_data=self._cache.get_resume(info_hash=Cache.hash_from_magnet(uri))
                if resume_data:
                    tp['resume_data']=resume_data
        elif os.path.isfile(uri):
            tp=info_from_file(uri)
        else:
            raise ValueError("Invalid torrent %s" %uri)
        
        tp.update(self._torrent_params)
        self._th = self._ses.add_torrent(tp)
        for tr in INITIAL_TRACKERS:
            self._th.add_tracker({'url':tr})
        self._th.set_sequential_download(True)
#         if tp.has_key('ti'):
#             self._meta_ready(self._th.get_torrent_info())
        
        self._monitor.start()
        self._dispatcher.do_start(self._th, self._ses)
        
    def stop(self):
        BaseClient.stop(self)(self)
        self._dispatcher.stop()
        self._dispatcher.join()
        

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
            
    def save_resume(self):
        if self._th.need_save_resume_data() and self._th.is_valid() and self._th.has_metadata():
            r=BTClient.ResumeData(self)
            start=time.time()
            while (time.time() - start) <= 5 :
                if r.data or r.failed:
                    break
                time.sleep(0.1)
            if r.data:
                logger.debug('Savig fast resume data')
                self._cache.save_resume(self.unique_file_id,lt.bencode(r.data))
            else:
                logger.warn('Fast resume data not available')    
        
    def close(self):
        self.remove_all_dispatcher_listeners()
        if self._ses:
            self._ses.pause()
            if self._th:
                self.save_resume()
            self.save_state()
        self._stop_services()
        BaseClient.close(self)
        
    @property
    def status(self):
        if self._th:
            s = self._th.status()
            if self._file:
                pieces=s.pieces[self._file.first_piece:self._file.last_piece]
                progress= float(sum(pieces))/len(pieces)
            else:
                progress=0
            size=self._file.size if self._file else 0
            s.desired_rate=self._file.byte_rate if self._file and progress>0.003 else 0
            s.progress_file=progress
            s.file_size=size
            return s
    
    class ResumeData(object):  
        def __init__(self, client):   
            self.data=None
            self.failed=False
            client.add_dispatcher_listener(self._process_alert)
            client._th.save_resume_data()
            
        def _process_alert(self, t, alert):
            if t=='save_resume_data_failed_alert':
                logger.debug('Fast resume data generation failed')
                self.failed=True
            elif t=='save_resume_data_alert':
                self.data=alert.resume_data
    
    class Dispatcher(BaseMonitor):
        def __init__(self, client):
            super(BTClient.Dispatcher,self).__init__(client, name='Torrent Events Dispatcher')
            
        def do_start(self, th, ses): 
            self._th = th
            self._ses=ses
            self.start()
            
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
                                
    STATE_STR = ['queued', 'checking', 'downloading metadata', \
                    'downloading', 'finished', 'seeding', 'allocating', 'checking fastresume']    
    
    def print_status(self,s,client):
        color=''
        
        if s.progress >=1.0 or not s.desired_rate or s.state > 3:
            color=TerminalColor.default
        elif s.desired_rate > s.download_rate:
            color=TerminalColor.red
        elif s.download_rate > s.desired_rate and s.download_rate < s.desired_rate *1.2:
            color=TerminalColor.yellow
        else:
            color=TerminalColor.green
            
        status = BTClient.STATE_STR[s.state]
        print '\r%.2f%% (of %.1fMB) (down: %s%.1f kB/s\033[39m(need %.1f) up: %.1f kB/s s/p: %d(%d)/%d(%d)) %s' % \
            (s.progress_file * 100, s.file_size/1048576.0, 
             color, s.download_rate / 1000, s.desired_rate/1000.0 if s.desired_rate else 0.0,
             s.upload_rate / 1000, \
            s.num_seeds, s.num_complete, s.num_peers, s.num_incomplete, status),
        sys.stdout.write("\033[K")
        sys.stdout.flush()
        
    def get_normalized_status(self):
        s=self.status
        if self._file:
            pieces = s.pieces[self._file.first_piece: self._file.last_piece+1]
            downloaded = reduce(lambda s,x:s+(x and 1 or 0)*self._file.piece_size, pieces[:-1], 0)
            if pieces[-1]:
                rem=self._file.size % self._file.piece_size
                downloaded+=rem if rem else self._file.piece_size
        else:
            downloaded=0
        return {'source_type':'bittorrent',
            'state':BTClient.STATE_STR[s.state],
            'downloaded':downloaded,
            'total_size':s.file_size,
            'download_rate':s.download_rate,
            'desired_rate':s.desired_rate, 
            'piece_size': self._file.piece_size if self._file else 0,
            'progress': s.progress_file,
            #BT specific
            'seeds_connected': s.num_seeds,
            'seeds_total': s.num_complete,
            'peers_connected': s.num_peers,
            'peers_total': s.num_incomplete,
            
            }
        
    def debug_download_queue(self,s,client):
        if s.state!= 3:
            return
        download_queue=self._th.get_download_queue()
        if self.file:
            first=self.file.first_piece
        else:
            first=0
        q=map(lambda x: x['piece_index']+first,download_queue)
        logger.debug('Download queue: %s', q)
    
    def debug_alerts(self,type, alert):
        logger.debug("Alert %s - %s", type, alert)
                   
                
            

              
class BTFile(AbstractFile):     
    def __init__(self, path, base, index, size, fmap, piece_size, prioritize_fn):
        AbstractFile.__init__(self, path, base, size, piece_size)
        self.index=index
        self.first_piece=fmap.piece
        self.last_piece=self.first_piece + max((size-1+fmap.start),0) // piece_size
        self.offset=fmap.start
        self._prioritize_fn=prioritize_fn
       
                
    def prioritize_piece(self, n, idx):  
        self._prioritize_fn(n,idx)       

    
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
    p.add_argument("url", help="Torrent file, link to file or magnet link")
    p.add_argument("-d", "--directory", default="./", help="directory to save download files")
    p.add_argument("-p", "--player", default="mplayer", choices=["mplayer","vlc"], help="Video player")
    p.add_argument("--player-path", default=None, help="Video player path")
    p.add_argument("--port", type=int, default=5001, help="Port for http server")
    p.add_argument("--debug-log", default='',help="File for debug logging")
    p.add_argument("--stdin", action='store_true', help='sends video to player via stdin (no seek then)')
    p.add_argument("--print-pieces", action="store_true", help="Prints map of downloaded pieces and ends (X is downloaded piece, O is not downloaded)")
    p.add_argument("-s", "--subtitles", action=LangAction, help="language for subtitle 3 letter code eng,cze ... (will try to get subtitles from opensubtitles.org)")
    p.add_argument("--stream", action="store_true", help="just file streaming, but will not start player")
    p.add_argument("--no-resume", action="store_true",help="Do not resume from last known position")
    p.add_argument("-q", "--quiet", action="store_true", help="Quiet - did not print progress to stdout")
    p.add_argument('--delete-on-finish', action="store_true", help="Delete downloaded file when program finishes")
    p.add_argument('--clear-older', type=int, default=0, help="Deletes files older then x days from download directory, if set will slowdown start of client")
    p.add_argument('--bt-download-limit', type=int, default=0, help='Download limit for torrents kB/s')
    p.add_argument('--bt-upload-limit', type=int, default=0, help='Upload limit for torrents kB/s')
    p.add_argument('--listen-port-min', type=int, default=6881, help='Bitorrent input port range - minimum port')
    p.add_argument('--listen-port-max', type=int, default=6891, help='Bitorrent input port range - maximum port')
    p.add_argument('--choose-subtitles',  action="store_true", help="Always manually choose subtitles (otherwise will try to use best match in many cases)" )
    p.add_argument('--trace', action='store_true', help='More detailed debug logging')
    p.add_argument('--choose-file', action='store_true', help='Manually choose if there are more video files in torrent (otherwise chooses biggest automatically)')
    args=p.parse_args(args)
    if args.debug_log:
        logger.setLevel(logging.DEBUG)
        h=logging.handlers.RotatingFileHandler(args.debug_log)
        logger.addHandler(h)
    else:
        logger.setLevel(logging.CRITICAL)
        logger.addHandler(logging.StreamHandler())
        
    if args.clear_older:
        days=args.clear_older
        items=os.listdir(args.directory)
        now=time.time()
        for item in items:
            if item!=Cache.CACHE_DIR:
                full_path=os.path.join(args.directory,item)
                if now-os.path.getctime(full_path)>days*24*3600:
                    logger.debug('Deleting path %s',full_path)
                    if os.path.isdir(full_path):
                        shutil.rmtree(full_path,ignore_errors=True)
                    else:
                        os.unlink(full_path)
    
    if args.print_pieces:
        print_pieces(args) 
    elif re.match('https?://localhost', args.url):  
        class TestResolver(Resolver):
            SPEED_LIMIT=300
            THREADS=2
        stream(args, HTClient,TestResolver)
    else: 
        rclass=plugins.find_matching_plugin(args.url)
        if rclass:
            stream(args,HTClient, rclass)
        else:
            stream(args, BTClient)

        
def stream(args, client_class, resolver_class=None):
    c= client_class(args.directory, args=args, resolver_class=resolver_class)
    player=None
    def on_exit(sig=None,frame=None):
        c.close()
        if player:
            player.terminate()
        if sig:    
            logger.info('Exiting by signal %d', sig)
            sys.exit(0)
    if sys.platform!='win32':
        signal.signal(signal.SIGHUP, on_exit)
        signal.signal(signal.SIGTERM, on_exit)
    try:
            
        
        if  not args.stream:
            player=Player.create(args.player,args.player_path,c.update_play_time)
        
        server=None
        #test if port if free, otherwise find free
        free_port=args.port
        while True:
            
                try:
                    s=socket.socket()
                    res=s.connect_ex(('127.0.0.1', free_port))
                    if res:
                        break
                finally:
                    s.close()
                free_port+=1
        if not args.stdin:
            server=StreamServer(('127.0.0.1',free_port), BTFileHandler, allow_range=True, status_fn=c.get_normalized_status)
            logger.debug('Started http server on port %d', free_port)
            server.run()
        if player:
            def start_play(f, finished):
                base=None
                if not args.stdin:
                    server.set_file(f)
                    base='http://127.0.0.1:'+ str(free_port)+'/'
                sin=args.stdin
                if finished:
                    base=args.directory
                    sin=False
                    logger.debug('File is already downloaded, will play it directly')
                    args.play_file=True
               
                if args.no_resume:
                    start_time=0
                else:
                    start_time=c.last_play_time or 0    
                player.start(f,base, stdin=sin,sub_lang=args.subtitles,start_time=start_time,
                             always_choose_subtitles=args.choose_subtitles)
                logger.debug('Started media player for %s', f)
            def start_play_async(f,finished):
                t=Thread(name='Start player', target=start_play, args=(f,finished))
                t.daemon=True
                t.start()
            c.set_on_file_ready(start_play_async)
        else:
            def print_url(f,done):
                server.set_file(f)
                base='http://127.0.0.1:'+ str(free_port)+'/'
                url=urlparse.urljoin(base, urllib.quote(f.path))
                print "\nServing file on %s" % url
                sys.stdout.flush()

            c.set_on_file_ready(print_url)
            
        logger.debug('Starting btclient - libtorrent version %s', lt.version)
        c.start_url(args.url)
        while not c.is_file_ready:
            time.sleep(1)
        if not args.stdin or hasattr(args, 'play_file') and args.play_file:
            f=None
        else:
            f=c.file.create_cursor()
            
        while True:
            if player and not player.is_playing():
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
        if player: 
            if player.rcode != 0:
                msg='Player ended with error %d\n' % (player.rcode or 0)
                sys.stderr.write(msg)
                logger.error(msg)
        
            logger.debug("Player output:\n %s", player.log)
    finally:
        on_exit()
        #logger.debug("Remaining threads %s", list(threading.enumerate()))
    

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
    c= BTClient(args.directory)
    c.start_url(args.url)
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
    except KeyboardInterrupt:
        print >>sys.stderr, '\nProgram interrupted, exiting'
        logger.info('Exiting by SIGINT')
    except Exception:
        traceback.print_exc()
        logger.exception('General error')
