import requests
from requests import Session
from requests.packages.urllib3.util import Retry
from requests.adapters import HTTPAdapter
import os.path
import pickle
from common import AbstractFile, BaseClient, Hasher, Resolver, TerminalColor
import logging
from collections import namedtuple
import random
import time
import re
import Queue
import collections
from threading import Lock, Thread
import sys
import threading
from bs4 import BeautifulSoup
from collections import deque

logger=logging.getLogger('htclient')

Piece=namedtuple('Piece', ['piece','data','total_size', 'type'])


class HTTPLoader(object):
    
    UA_STRING=['Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0',
               'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.0 Safari/537.36',
               'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.75.14 (KHTML, like Gecko) Version/7.0.3 Safari/7046A194A']
    
    PARSER='lxml'#'html5lib'#'html.parser'#'lxml'
    RETRIES=5
    class Error(Exception):
        pass
    def __init__(self,url,id, resolver_class=None):
        self.id=id
        resolver_class=resolver_class or Resolver
        self._client=Session()
        self._client.mount('http', HTTPAdapter(max_retries=Retry(total=self.RETRIES, status_forcelist=[500,503])))
        self._client.headers.update({'User-Agent':self._choose_ua()})
        self.url=self.resolve_file_url(resolver_class, url)
        if not self.url:
            raise HTTPLoader.Error('Url was not resolved to file link')
        
    def resolve_file_url(self, resolver_class, url):
        r=resolver_class(self)
        return r.resolve(url)
        
    def _choose_ua(self):
        return HTTPLoader.UA_STRING[random.randint(0,len(HTTPLoader.UA_STRING)-1)]
    
    
    RANGE_RE=re.compile(r'bytes\s+(\d+)-(\d+)/(\d+)')
    def _parse_range(self, r):
        m=HTTPLoader.RANGE_RE.match(r)
        if not m:
            raise HTTPLoader.Error('Invalid range header')
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    
    
    def open(self, url, data=None, headers={}, method='get' , stream=False, redirect=True ):
        try:
            if method=='post':
                res=self._client.post(url, data=data, headers=headers, timeout=30, stream=stream, allow_redirects=redirect)
            else:
                res=self._client.get(url, params=data, headers=headers, timeout=30, stream=stream, allow_redirects=redirect)
        except  requests.exceptions.RequestException , e:
            raise HTTPLoader.Error('Cannot open resource %s due to error %s' % (url,e))
        
        return res
    
    def load_piece(self, piece_no, piece_size):
        start=piece_no*piece_size
        end=start+piece_size-1
        headers={'Range': 'bytes=%d-%d'%(start,end)}
        res=self.open(self.url, headers=headers)
        if res.status_code!=206:
            raise HTTPLoader.Error('Ranges are not supported (status code)')
        
        allow_range_header=res.headers.get('Accept-Ranges')
        if allow_range_header and allow_range_header.lower()=='none':
            raise HTTPLoader.Error('Ranges are not supported (accept-ranges none')
        
        size_header=res.headers.get('Content-Length')
        total_size = int(size_header) if size_header else None
        
        range_header=res.headers.get('Content-Range')
        if not range_header:
                raise HTTPLoader.Error('Ranges are not supported (missing content-range)')
        else:
            from_pos, to_pos, size = self._parse_range(range_header)
        
        type_header=res.headers.get('Content-Type')
        
        if not type_header:
            raise HTTPLoader.Error('Content Type is missing')
        
        data=res.content
        assert len(data)<= piece_size
        return Piece(piece_no,data,size,type_header)
        
    
   
    
    def load_page(self, url, data=None, method='get'):
        res=self.open(url,data,headers={'Accept-Encoding':"gzip, deflate"}, method=method)
        #Content-Type:"text/html; charset=utf-8"
        type_header=res.headers.get('Content-Type')
        if not type_header.startswith('text/html'):
            raise HTTPLoader.Error("%s is not HTML page"%url)
        #Content-Encoding:"gzip"
        pg=BeautifulSoup(res.text, HTTPLoader.PARSER)
        return pg
    
    def load_json(self,url,data,method='get'):
        res=self.open(url,data,headers={'Accept-Encoding':"gzip, deflate", 'X-Requested-With':'XMLHttpRequest'}, method=method)
        type_header=res.headers.get('Content-Type')
        if not type_header.startswith('application/json'):
            raise HTTPLoader.Error("%s is not JSON"%url)
        #Content-Encoding:"gzip"
        return res.json(encoding='utf8')
    
    def close(self):
        self._client.close()
        

class PriorityQueue(Queue.PriorityQueue):
    NORMAL_PRIORITY=99
    NO_DOWNLOAD=999
    NO_PIECE=-1
    def __init__(self):
        Queue.PriorityQueue.__init__(self, maxsize=0)
        self._wset={}
        self._lock=Lock()
        
    def put_piece(self, piece, priority, remove_previous=False):
        #do not put piece which is already in queue
        with self._lock:
            if piece in self._wset:
                if self._wset[piece][0]==priority:
                    return
                else:
                    self.remove_piece(piece)
            if remove_previous:
                for k in self._wset:
                    if k < piece:
                        self.remove_piece(k)
                        
            entry=[priority,piece]
            self._wset[piece]=entry
            self.put(entry,block=False)
    
    def remove_piece(self,piece):
        entry=self._wset.pop(piece)
        entry[-1]=PriorityQueue.NO_PIECE
        
    def get_piece(self, timeout=None):
        while True:
            _priority, piece= self.get(timeout=timeout)
            with self._lock:
                if piece is not PriorityQueue.NO_PIECE:
                    del self._wset[piece]
                    return piece
        
        
class Pool(object):
    def __init__(self, piece_size,loaders, cb, speed_limit=None):
        self.piece_size=piece_size
        self._cb=cb
        self.speed_limit=speed_limit
        self._queue=PriorityQueue()
        self._running=True
        self._threads=[Thread(name="worker %d"%i, target=self.work, args=[l]) for i,l in enumerate(loaders)]
        for t in self._threads:
            t.daemon=True
            t.start()
        
    def add_worker_async(self, id, gen_fn, args=[], kwargs={}):  
        def resolve():
            l=gen_fn(*args, **kwargs) 
            t=Thread(name="worker %d"%id, target=self.work, args=[l])
            t.daemon=True
            t.start()
            self._threads.append(t)
        adder=Thread(name="Adder", target=resolve)
        adder.daemon=True
        adder.start()
        
    def work(self, loader):
        while self._running:
            pc=self._queue.get_piece()
            if not self._running:
                break
            try:
                start=time.time()
                p=loader.load_piece(pc,self.piece_size)
                self._cb(p.piece,p.data)
                if self.speed_limit:
                    dur=time.time()-start
                    expected=self.piece_size/1024.0/self.speed_limit
                    wait_time=expected-dur
                    if wait_time>0:
                        logger.debug('Waiting %f on %s',wait_time, threading.current_thread().name)
                        time.sleep(wait_time)
            except Exception,e:
                logger.exception('(%s) Error when loading piece %d: %s', threading.current_thread().name,pc,e)
            
    def stop(self):
        self._running=False
        #push some dummy tasks to assure workers ends
        for i in xrange(len(self._threads)):
            self._queue.put_piece(i, PriorityQueue.NO_DOWNLOAD)
            
    def add_piece(self, piece, priority=PriorityQueue.NORMAL_PRIORITY, remove_previous=False):
        self._queue.put_piece(piece, priority, remove_previous)
            
            
class HTClient(BaseClient):
    def __init__(self, path_to_store, args=None,piece_size=2*1024*1024,no_threads=2,resolver_class=None):
        BaseClient.__init__(self, path_to_store,args=args)
        self._pool=None
        self.resolver_class=resolver_class
        self._no_threads=self.resolver_class.THREADS if self.resolver_class and hasattr(self.resolver_class,'THREADS') else no_threads
        self.piece_size=piece_size
        self._last_downloaded=deque(maxlen=60)
    
    def update_piece(self,piece, data):
        self._file.update_piece(piece, data)
        if not self._ready and hasattr(self._file,'filehash') and self._file.filehash \
            and all(self._file.pieces[:5]):
            self._set_ready(self._file.is_complete)
        
    def request_piece(self, piece, priority):
        if self._pool:
            self._pool.add_piece(piece,priority)
        else:
            raise Exception('Pool not started')
        
    def _on_file_ready(self, filehash):
        self._file.filehash=filehash
        if self.is_file_complete:
            self._set_ready( True)
                
    def _set_ready(self, complete):
        self._ready=True
        if self._on_ready_action:
            self._on_ready_action(self._file, complete)
        
    def start_url(self, uri):
        self._monitor.start()
        path=self.resolver_class.url_to_file(uri)
        c0=None
        try:
            self._file=HTFile(path, self._base_path, 0, self.piece_size, self.request_piece)
        except HTFile.UnknownSize:
            c0=HTTPLoader(uri, 0, self.resolver_class)
            p=c0.load_piece(0, self.piece_size)
            self._file=HTFile(path, self._base_path, p.total_size, self.piece_size, self.request_piece)
            self.update_piece(0, p.data)
            self._file.mime=p.type
        
                    
        if not self._file.is_complete:
            c0= HTTPLoader(uri, 0, self.resolver_class)
            self._pool=Pool(self.piece_size, [c0],
                         self.update_piece, speed_limit=self.resolver_class.SPEED_LIMIT if hasattr(self.resolver_class,'SPEED_LIMIT') else None)
            def gen_loader(i):
                return HTTPLoader(uri,i,self.resolver_class)
            for i in xrange(1,self._no_threads):
                self._pool.add_worker_async(i, gen_loader, (i,))
            #get remaining pieces with normal priority
            for i in xrange(1, self._file.last_piece+1):
                if not self._file.pieces[i]:
                    self._pool.add_piece(i)
            
        self.hash=Hasher(self._file, self._on_file_ready)
        
            
    @property
    def is_file_complete(self):
        return self.file.is_complete if self.file else False
    
    @property
    def unique_file_id(self):
        return self.file.filehash
    
    Status=collections.namedtuple('Status', ['state','downloaded','download_rate', 'total_size', 'threads','desired_rate'])
    
    @property
    def status(self):
        tick=time.time()
        
        state='starting' if not self.file else 'finished' if self.is_file_complete else 'downloading'
        downloaded=self.file.downloaded if self.file else 0
        if self._last_downloaded:
            prev_time,prev_down = self._last_downloaded[0]
            download_rate= (downloaded - prev_down) / (tick-prev_time) 
        else:
            download_rate=0
        total_size=self.file.size if self.file else 0
        threads=self._no_threads
        desired_rate= self._file.byte_rate if self._file else 0
        
        if self.file:
            self._last_downloaded.append((tick, downloaded))
        return HTClient.Status(state,downloaded, download_rate, total_size,threads,desired_rate)
        
    def get_normalized_status(self):
        s=self.status
        return {'source_type':'http',
            'state':s.state,
            'downloaded':s.downloaded,
            'total_size':s.total_size,
            'download_rate':s.download_rate,
            'desired_rate':s.desired_rate, 
            'piece_size': self._file.piece_size if self._file else 0,
            'progress': s.downloaded / float(s.total_size) if s.total_size else 0,
            # HTTP specific
            'threads': s.threads
            }
    def close(self):
        if self._file:
            self._file.close()
        BaseClient.close(self)
            
    def print_status(self, s, client):
        progress=s.downloaded / float(s.total_size) * 100if s.total_size else 0
        total_size=s.total_size / 1048576.0
        
        color=''
        if progress >=100.0 or not s.desired_rate or s.state in ('finished', 'starting'):
            color=TerminalColor.default
        elif s.desired_rate > s.download_rate:
            color=TerminalColor.red
        elif s.download_rate > s.desired_rate and s.download_rate < s.desired_rate *1.2:
            color=TerminalColor.yellow
        else:
            color=TerminalColor.green
        
        print '\r%.2f%% (of %.1fMB) down: %s%.1f kB/s\033[39m(need %.1f)  %s' % \
            (progress, total_size, 
             color, s.download_rate/1000.0, s.desired_rate/1000.0 if s.desired_rate else 0.0,
            s.state),
        sys.stdout.write("\033[K")
        sys.stdout.flush()
        
                    

class HTFile(AbstractFile):
    def __init__(self, path, base, size, piece_size=2097152, prioritize_fn=None):
        self._full_path= os.path.join(base,path)
        self._prioritize_fn=prioritize_fn
        self.pieces=None
        self.mime=None
        size=self._load_cached(size)
        AbstractFile.__init__(self, path, base, size, piece_size)
        if not self.pieces or len(self.pieces)!=self.last_piece+1:
            self.pieces=[False for _i in xrange(self.last_piece+1)]
        self._file=open(self.full_path,'r+b')
        
        
    class UnknownSize(Exception):
        pass
    
    def _load_cached(self, size):
        if not os.path.exists(self.full_path) and size:
            self._allocate_file(size)
            return size
        elif os.path.exists(self.full_path):
            sz=os.stat(self.full_path).st_size
            if size and size!=sz:
                logger.warn('Invalid cached file')
                self._allocate_file(size)
                return size
            pcs_file=self.pieces_index_file
            if os.access(pcs_file, os.R_OK):
                with open(pcs_file,'rb') as f:
                    pcs=pickle.load(f)
                if isinstance(pcs, tuple): 
                    self.pieces=pcs[1]
                    self.mime=pcs[0]
                else:
                    logger.warn('Invalid pieces file %s',pcs_file)
            return sz
        else:
            raise HTFile.UnknownSize()
            
    @property    
    def pieces_index_file(self):
        return self.full_path+'.pieces'
    
                
    def _allocate_file(self, size):
        path=os.path.split(self.full_path)[0]
        if not os.path.exists(path):
            os.makedirs(path, mode=0755)
        #sparecelly allocate file 
        with open(self.full_path,'ab') as f:
            f.truncate(size)
            
            
    def update_piece(self, n, data):
        assert n!= self.last_piece and len(data)==self.piece_size or \
               n==self.last_piece and len(data)==(self.size % self.piece_size) or self.piece_size, "Invalid size of piece %d - %d"% (n,len(data))   
        assert n>=self.first_piece and  n<=self.last_piece,'Invalid piece no %d'%n
        
        with self._lock:
            if not self.pieces[n]:
                self._file.seek(n*self.piece_size)
                self._file.write(data)
                self._file.flush()
                self.pieces[n]=True
                logger.debug('Received piece %d in thread %s', n, threading.current_thread().name)
        AbstractFile.update_piece(self, n, data)
        
    def prioritize_piece(self, piece, idx):
        assert piece>=self.first_piece and  piece<=self.last_piece,'Invalid piece no %d'%piece
        data=None
        with self._lock:
            if self.pieces[piece]:
                sz = self.piece_size if piece < self.last_piece else self.size % self.piece_size
                self._file.seek(piece*self.piece_size)
                data=self._file.read(sz)
                assert len(data)==sz
        if data:
            AbstractFile.update_piece(self, piece, data)
        elif self._prioritize_fn:
            self._prioritize_fn(piece,idx)
        else:
            assert False, 'Missing prioritize fn'
            
    @property
    def is_complete(self):
        return all(self.pieces)
    
    @property
    def downloaded(self):
        sum=0 
        for i,p in enumerate(self.pieces):
            if p and i==self.last_piece:
                sum+= (self.size % self.piece_size) or self.piece_size 
            elif p:
                sum+= self.piece_size
                
        return sum      
    
    def remove(self):
        AbstractFile.remove(self)
        if os.path.exists(self.pieces_index_file):
            os.unlink(self.pieces_index_file)
    def close(self):
        self._file.close()
        d=os.path.split(self.pieces_index_file)[0]
        if d and os.path.isdir(d):
            with open(self.pieces_index_file, 'wb') as f:
                pickle.dump((self.mime,self.pieces),f)
        
        
            
    
