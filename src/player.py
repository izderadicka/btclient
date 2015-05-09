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
    def create(player,on_play_time_change=None):
        executable=find_executable(player)
        if not executable:
                msg= "Cannot find player %s on path"%player
                raise Exception(msg)
        if player=='mplayer':
            return MPlayer(executable,on_play_time_change)
        elif player=='vlc':
            return Vlc(executable,on_play_time_change)
        else:
            raise ValueError('Invalid player name %s'%player)
        
    OPTIONS=[]
                
    def __init__(self,player, on_play_time_change=None):
        self._player=player
        self._proc=None
        self._player_options=copy(self.OPTIONS)
        self._log =None
        self._started=Event()
        self._on_play_time_change=on_play_time_change
    
    
    def modify_env(self):
        env=os.environ.copy()
        #assure not using proxy
        env.pop('http_proxy', '')
        env.pop('HTTP_PROXY', '')
        return env
        
    def start_log(self):
        self._log = Player.Log(self._proc)
            
    def start(self, f, base, stdin, sub_lang=None, start_time=None):
        env=self.modify_env()
        params=[self._player,]
        params.extend(self._player_options)
        if sub_lang:
            try:
                params.extend(self.load_subs(f.full_path, sub_lang, f.size, f.filehash))
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
            params.append(urlparse.urljoin(base, f.path))
            sin=open(os.devnull, 'w')
        self._proc=subprocess.Popen(params, 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    env=env, 
                                    stdin=sin,
                                    close_fds=True)
        self.start_log()
        self._started.set()
    
    def subs_option(self,subs_file):
        raise NotImplementedError()
    
    def start_time_option(self, time):
        raise NotImplementedError()
    
    def load_subs(self, filename, lang, filesize, filehash):
        logger.debug('Downloading %s subs for %s', lang, filename)
        res=  OpenSubtitles.download_if_not_exists(filename,lang, filesize, filehash)
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
    
    def __init__(self, player, on_play_time_change=None):
        Player.__init__(self, player, on_play_time_change)
        if not os.path.exists(self.INPUT_PIPE):
            os.mkfifo(self.INPUT_PIPE)
        
    def start_log(self):
        self._log = MPlayer.Log(self._proc, self._on_play_time_change)
        self._poller=MPlayer.Poller(self.is_playing)
        
    def subs_option(self, subs_file):
        return ['-sub', subs_file]
    
    def start_time_option(self, time):
        return ['-ss', '%0.1f'%time]

class Vlc(Player):
    HTTP_PORT=4448
    OPTIONS=['--no-video-title-show','--extraintf', 'http', '--http-host', '127.0.0.1', '--http-port', '4448']
    def subs_option(self, subs_file):
        return ['--sub-file=%s'%subs_file]
    
    def start_time_option(self, time):
        return ['--start-time', '%0.1f'%time]