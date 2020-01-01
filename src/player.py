'''
Created on May 2, 2015

@author: ivan
'''

import collections
from threading import Thread, Event
import os.path
import logging
from opensubtitle import OpenSubtitles
import urlparse
import re
import time
import socket
import sys
import urllib
import json
logger=logging.getLogger('player')
import subprocess
from distutils.spawn import find_executable
from copy import copy


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
        
    @staticmethod
    def create(player,player_path,on_play_time_change=None, zenity=None):
        executable=find_executable(player, player_path)
        if not executable:
                msg= "Cannot find player %s on path %s" % (player, str(player_path))
                raise Exception(msg)
        if player=='mplayer':
            return MPlayer(executable,on_play_time_change, zenity)
        elif player=='vlc' or player=='vlc.exe':
            return Vlc(executable,on_play_time_change, zenity)
        elif player == 'mpv':
            return Mpv(executable, on_play_time_change, zenity)
        else:
            raise ValueError('Invalid player name %s'%player)
        
    OPTIONS=[]
                
    def __init__(self,player, on_play_time_change=None, zenity=None):
        self._player=player
        self._proc=None
        self._player_options=copy(self.OPTIONS)
        self._log =None
        self._started=Event()
        self._on_play_time_change=on_play_time_change
        self._zenity =  zenity
    
    
    def modify_env(self):
        env=os.environ.copy()
        #assure not using proxy
        env.pop('http_proxy', '')
        env.pop('HTTP_PROXY', '')
        return env
        
    def start_log(self):
        self._log = Player.Log(self._proc)
            
    def start(self, f, base, stdin, sub_lang=None, start_time=None, always_choose_subtitles=False):
        env=self.modify_env()
        params=[self._player,]
        params.extend(self._player_options)
        if sub_lang:
            try:
                params.extend(self.load_subs(f.full_path, sub_lang, f.size, f.filehash, always_choose_subtitles))
            except Exception,e:
                logger.exception('Cannot load subtitles, error: %s',e)
        if start_time:
            params.extend(self.start_time_option(start_time))
        if stdin:
            params.append('-')
            sin=subprocess.PIPE
        else:
            if not base.endswith(os.sep):
                base+=os.sep
            p=urllib.quote(f.path) if re.match('^(https?|file)://',base) else f.path
            params.append(urlparse.urljoin(base, p))
            sin=open(os.devnull, 'rb')
        self._proc=subprocess.Popen(params, 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    env=env, 
                                    stdin=sin,
                                    close_fds=sys.platform!='win32')
        self.start_log()
        self._started.set()
    
    def subs_option(self,subs_file):
        raise NotImplementedError()
    
    def start_time_option(self, time):
        raise NotImplementedError()
    
    def load_subs(self, filename, lang, filesize, filehash, always_choose_subtitles=False):
        logger.debug('Downloading %s subs for %s', lang, filename)
        res=  OpenSubtitles.download_if_not_exists(filename,lang, filesize, filehash,
                            can_choose=always_choose_subtitles, zenity=self._zenity)
        if res:
            logger.debug('Loadeded subs')
            return self.subs_option(res)
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
        
    def terminate(self):
        if self._proc:
            try:
                self._proc.terminate()
            except OSError:
                pass
        
        
class MPlayer(Player):
    class Log():
        def __init__(self, p, on_time_changed ):
            self._log = collections.deque(maxlen=80)
            self._p=p
            self._stdin_reader= self._mk_thread(p.stdout, "Player stdout reader", self._read_pipe_match)
            self._stderr_reader= self._mk_thread(p.stderr, "Player stderr reader", self._read_pipe)
            self.position=0
            self._time_change_cb=on_time_changed
            
        def _mk_thread(self, pipe, name, fn):
            t= Thread(target=fn, name=name, args=(pipe,))
            t.setDaemon(True)
            t.start()
            return t
        
        TIME_RE=re.compile('^ANS_TIME_POSITION=([\d\.]+)$')
        def _read_pipe(self, pipe):
            while True:
                l= pipe.readline()
                if not l:
                    break
                self._log.append(l)
                
        def _read_pipe_match(self, pipe):
            while True:
                l= pipe.readline()
                if not l:
                    break
                r=MPlayer.Log.TIME_RE.match(l)
                if  r:
                    self._set_time(float(r.group(1)))
                    #logger.debug('Play time is %f', self.position)
                else:
                    self._log.append(l)
                
        def _set_time(self, time):
            if abs(time-self.position)>=1 and self._time_change_cb:
                self._time_change_cb(time)
            self.position=time
                
                
        @property        
        def log(self):
            return ''.join(self._log)
        
        
    class Poller(Thread):
        def __init__(self, live):
            Thread.__init__(self, name="Position poller")
            self.daemon=True
            self._pipe=open(MPlayer.INPUT_PIPE,'w')
            self._live=live
            self.start()
        
        def run(self):
            while self._live():
                self._pipe.write('get_time_pos\n')
                try:
                    self._pipe.flush()
                except IOError:
                    pass
                time.sleep(1)
            try:
                self._pipe.close()
            except IOError:
                pass
            
    INPUT_PIPE='/tmp/mplayer.pipe'
    OPTIONS=['-quiet', '-slave', '-input', 'file=%s' %INPUT_PIPE]#'--nocache']#'--cache=8192', '--cache-min=50']
    
    def __init__(self, player, on_play_time_change=None, zenity = None):
        Player.__init__(self, player, on_play_time_change, zenity)
        if not os.path.exists(self.INPUT_PIPE):
            os.mkfifo(self.INPUT_PIPE)
        
    def start_log(self):
        self._log = MPlayer.Log(self._proc, self._on_play_time_change)
        self._poller=MPlayer.Poller(self.is_playing)
        
    def subs_option(self, subs_file):
        return ['-sub', subs_file]
    
    def start_time_option(self, time):
        return ['-ss', '%0.1f'%time]
    
class Mpv(Player):        
    class Poller(Thread):
        def __init__(self, cb, live):
            Thread.__init__(self,name='Position poller')
            self.daemon=True
            self._cb=cb
            self._live=live
            start=time.time()
            
            # wait for mpv to listen on json ipc socket
            while True:
                try:
                    time.sleep(1)
                    self._socket =  socket.socket(socket.AF_UNIX)
                    self._socket.connect(Mpv.INPUT_SOCKET)
                    break
                except socket.error,e:
                    if time.time()-start>10:
                        raise e
                    
            self._reader=self._socket.makefile('rb')
            self.position=0
            self.start()
        
        def run(self):
            while self._live():
                try:
                    #logger.debug('poller-sending time request')
                    cmd = '{ "command": ["get_property", "playback-time"] }\n'
                    self._socket.send(cmd)
                    ans=self._reader.readline()
                except socket.error,e:
                    logger.warn('Socket error in mpv poller - %s',e)
                #logger.debug('ANS %s', ans)
                try:
                    ans=json.loads(ans)
                except ValueError as e:
                    logger.warn('Reply error %s', e)
                else:
                    #logger.debug('poller - response %s', ans)
                    if ans.get('error') == 'success' and ans.get('data'):
                        pos = float(ans['data'])
                        if abs(self.position - pos)>=1 and self._cb:
                            self._cb(pos)
                        self.position = pos
                           
                time.sleep(1)
                
        def close(self):
            try:
                self._reader.close()
                self._socket.close()
            except:
                logger.warn('Error closing VLC poller')
            
    INPUT_SOCKET='/tmp/mpv.socket'
    OPTIONS=['--quiet', '--input-ipc-server=%s'%INPUT_SOCKET]
    
    def __init__(self, player, on_play_time_change=None, zenity=None):
        Player.__init__(self, player, on_play_time_change=on_play_time_change, zenity=zenity)
        self._poller=None
    
    def start(self, f, base, stdin, sub_lang=None, start_time=None, always_choose_subtitles=False):
        Player.start(self, f, base, stdin, sub_lang=sub_lang, start_time=start_time, always_choose_subtitles=always_choose_subtitles)
        self._poller=Mpv.Poller(self._on_play_time_change, self.is_playing)
    
    def close(self):
        Player.close(self)
        if self._poller:
            self._poller.close()    
    
        
    def subs_option(self, subs_file):
        return ['--sub-file=%s'% subs_file]
    
    def start_time_option(self, time):
        return ['--start=%0.1f'%time]

class Vlc(Player):
    RC_PORT=4212
    OPTIONS=['--no-video-title-show','--extraintf', 'rc', '--rc-host', 'localhost:%d'%RC_PORT]
    class Poller(Thread):
        def __init__(self, cb, live):
            Thread.__init__(self,name='Position poller')
            self.daemon=True
            self._cb=cb
            self._live=live
            start=time.time()
            
            # wait for vlc to listen on cli socket
            while True:
                try:
                    time.sleep(1)
                    self._socket=socket.create_connection(('localhost', Vlc.RC_PORT))
                    break
                except socket.error,e:
                    if time.time()-start>10:
                        raise e
                    
            self._reader=self._socket.makefile('rb')
            for i in xrange(2):
                l=self._reader.readline()
                logger.debug('VLC CLI - %s',l)
            self.position=0
            self.start()
        
        digits=re.compile(r'\d+')    
        def run(self):
            while self._live():
                try:
                    self._socket.send('get_time\n')
                    ans=self._reader.readline()
                except socket.error,e:
                    logger.warn('Socket error in VLC poller - %s',e)
                else:
                    #logger.debug('ANS %s', ans)
                    pos=self.digits.search(ans)
                    if pos:
                        pos=int(pos.group(0))
                        if abs(self.position - pos)>=1 and self._cb:
                            self._cb(pos)
                        self.position = pos
                time.sleep(1)
                
        def close(self):
            try:
                self._reader.close()
                self._socket.close()
            except:
                logger.warn('Error closing VLC poller')
                
    def __init__(self, player, on_play_time_change=None, zenity=None):
        Player.__init__(self, player, on_play_time_change=on_play_time_change, zenity=zenity)
        self._poller=None
    
    def start(self, f, base, stdin, sub_lang=None, start_time=None, always_choose_subtitles=False):
        if self._player.endswith(".exe") and not base.startswith('http'):
            idx = base.find("/mnt/c/")
            base = "file:///c:"+base[idx+6:]
        Player.start(self, f, base, stdin, sub_lang=sub_lang, start_time=start_time, always_choose_subtitles=always_choose_subtitles)
        self._poller=Vlc.Poller(self._on_play_time_change, self.is_playing)
    
    def close(self):
        Player.close(self)
        if self._poller:
            self._poller.close()

    def subs_option(self, subs_file):
        if self._player.endswith('.exe'):
            #remap sub file to windows path
            subs_file=subs_file.replace("/mnt/c", "c:").replace("/", "\\")
            pass
        return ['--sub-file=%s'%subs_file]
    
    def start_time_option(self, time):
        return ['--start-time', '%0.1f'%time]