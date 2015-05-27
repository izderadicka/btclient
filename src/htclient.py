'''
Created on May 3, 2015

@author: ivan
'''

import urllib2
import os.path
import pickle
from common import AbstractFile, BaseClient, Hasher, Resolver, TerminalColor,\
    PieceCache
import logging
from cookielib import CookieJar
from collections import namedtuple
import random
from httplib import BadStatusLine, IncompleteRead
import socket
import time
import re
import Queue
import collections
from threading import Lock, Thread
import urlparse
import sys
import threading
from urllib import urlencode
from bs4 import BeautifulSoup
import zlib
from io import BytesIO
import gzip
import json
import shutil
from collections import deque


logger=logging.getLogger('htclient')

Piece=namedtuple('Piece', ['piece','data','total_size', 'type'])


class HTTPLoader(object):
    
    UA_STRING=['Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0',
               'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.0 Safari/537.36',
               'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.75.14 (KHTML, like Gecko) Version/7.0.3 Safari/7046A194A']
    
    PARSER='lxml'#'html5lib'#'html.parser'#'lxml'
    class Error(Exception):
        pass
    def __init__(self,url,id, resolver_class=None):
        self.id=id
        self.user_agent=self._choose_ua()
        resolver_class=resolver_class or Resolver
        self._client=urllib2.build_opener(urllib2.HTTPCookieProcessor(CookieJar()))
        self.url=self.resolve_file_url(resolver_class, url)
        if not self.url:
            raise HTTPLoader.Error('Urlwas not resolved to file link')
        self._interrupt=False
    
    
    def interrupt(self):
        self._interrupt=True
        
    class Interrupted(Exception):
        pass    
    
    def _check_interrupt(self):
        if self._interrupt:
            self._interrupt=False
            raise HTTPLoader.Interrupted()  
        
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
    
    def open(self, url, data=None, headers={}, method='get' ):
        hdr={'User-Agent':self.user_agent}
        hdr.update(headers)
        url,post_args=self._encode_data(url, data, method)
        req=urllib2.Request(url,post_args,headers=headers)
        res=None
        retries=5
        while retries:   
            try:
                res=self._client.open(req, timeout=10)
                break
            except (IOError, urllib2.HTTPError, BadStatusLine, IncompleteRead, socket.timeout) as e:
                if isinstance(e, urllib2.HTTPError) and hasattr(e,'code') and str(e.code)=='404':
                    raise HTTPLoader.Error('Url %s not found',url)
        
                logging.warn('Retry on (%s)  due to IO or HTTPError (%s) ', threading.current_thread().name,e)
                retries-=1
                time.sleep(1)
        if not res:
            raise HTTPLoader.Error('Cannot open resource %s' % url)
        return res
    BLOCK_SIZE=16*1024
    def load_piece(self, piece_no, piece_size, speed_limit=None):
        self._interrupt=False
        start=piece_no*piece_size
        headers={'Range': 'bytes=%d-'%start}
        res=self.open(self.url, headers=headers)
        allow_range_header=res.info().getheader('Accept-Ranges')
        if allow_range_header and allow_range_header.lower()=='none':
            raise HTTPLoader.Error('Ranges are not supported')
        
        size_header=res.info().getheader('Content-Length')
        total_size = int(size_header) if size_header else None
        
        range_header=res.info().getheader('Content-Range')
        if not range_header:
            if piece_no and not total_size:
                raise HTTPLoader.Error('Ranges are not supported')
            else:
                from_pos, to_pos, size= 0, total_size-1, total_size
        else:
            from_pos, to_pos, size = self._parse_range(range_header)
        
        type_header=res.info().getheader('Content-Type')
        
        if not type_header:
            raise HTTPLoader.Error('Content Type is missing')
        
        buf=bytearray(piece_size)
        pos=0
        while pos<piece_size:
            start=time.time()
            self._check_interrupt()
            sz=min(HTTPLoader.BLOCK_SIZE, piece_size-pos)
            block=res.read(sz)
            if not block:
                break
            buf[pos:len(block)]=block
            pos+=len(block)
            
            if speed_limit and not self._interrupt:
                dur=time.time()-start
                expected=len(block)/1024.0/speed_limit
                wait_time=expected-dur
                if wait_time>0:
                    if wait_time>1: logger.debug('LONG Waiting %f on %s',wait_time, threading.current_thread().name)
                    time.sleep(wait_time)
        
        res.close()
        return Piece(piece_no,buffer(buf)[0:pos],size,type_header)
    @staticmethod
    def decode_data(res):
        header=res.info()
        data=res.read()
        if header.get('Content-Encoding')=='gzip':
            tmp_stream=gzip.GzipFile(fileobj=BytesIO(data))
            data=tmp_stream.read()
            
        elif header.get('Content-Encoding')=='deflate':
            data = zlib.decompress(data)
        return data
    
    def _encode_data(self,url, data, method='post'):
        if not data:
            return url,None
        if method.lower()== 'post':
            return url, urlencode(data)
        else:
            return url+'?'+urlencode(data), None
        
    def load_page(self, url, data=None, method='get'):
        res=self.open(url,data,headers={'Accept-Encoding':"gzip, deflate"}, method=method)
        #Content-Type:"text/html; charset=utf-8"
        type_header=res.info().getheader('Content-Type')
        if not type_header.startswith('text/html'):
            raise HTTPLoader.Error("%s is not HTML page"%url)
        #Content-Encoding:"gzip"
        data=HTTPLoader.decode_data(res)
        pg=BeautifulSoup(data, HTTPLoader.PARSER)
        return pg
    
    def load_json(self,url,data,method='get'):
        res=self.open(url,data,headers={'Accept-Encoding':"gzip, deflate", 'X-Requested-With':'XMLHttpRequest'}, method=method)
        type_header=res.info().getheader('Content-Type')
        if not type_header.startswith('application/json'):
            raise HTTPLoader.Error("%s is not JSON"%url)
        #Content-Encoding:"gzip"
        data=HTTPLoader.decode_data(res)
        return json.loads(data,encoding='utf8')
    
    def get_redirect(self,url,data,method='get'):
        pass
        
        
        
        
                                          

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
    class Worker(Thread):
        def __init__(self, id, loader, pool):
            Thread.__init__(self,name="worker %d"%id)
            self.daemon=True
            self.id=id
            self._loader=loader
            self._queue=pool._queue
            self.piece_size=pool.piece_size
            self.speed_limit=pool.speed_limit
            self._cb=pool._cb
            self._pool=pool
            self.piece=None
            
            self.start()
        
        def interrupt(self):
            self._loader.interrupt()
            
        def run(self):
            while self._pool._running:
                self.piece=pc=self._queue.get_piece()
                if not self._pool._running:
                    break
                try:
                    p=self._loader.load_piece(self.piece,self.piece_size,self.speed_limit)
                    self.piece=None
                    self._cb(p.piece,p.data)
                except HTTPLoader.Interrupted:
                    logger.debug('Interrupted piece %d by high priority piece',pc)
                    # returning piece to queue
                    self._queue.put_piece(self.piece, PriorityQueue.NORMAL_PRIORITY)
                except Exception,e:
                    logger.exception('(%s) Error when loading piece %d: %s', threading.current_thread().name,pc,e)
                    # returning piece to queue
                    self._queue.put_piece(self.piece, PriorityQueue.NORMAL_PRIORITY)
                self._queue.task_done()
            
            
    def __init__(self, piece_size,loaders, cb, speed_limit=None):
        self.piece_size=piece_size
        self._cb=cb
        self.speed_limit=speed_limit
        self._queue=PriorityQueue()
        self._running=True
        self._threads=[Pool.Worker(i,l,self) for i,l in enumerate(loaders)]
        
        
    def add_worker_async(self, id, gen_fn, args=[], kwargs={}):  
        def resolve():
            l=gen_fn(*args, **kwargs) 
            t=Pool.Worker(id,l,self)
            self._threads.append(t)
        adder=Thread(name="Adder", target=resolve)
        adder.daemon=True
        adder.start()
        
    def stop(self):
        self._running=False
        #push some dummy tasks to assure workers ends
        for i in xrange(len(self._threads)):
            self._queue.put_piece(i, PriorityQueue.NO_DOWNLOAD)
            
    def add_piece(self, piece, priority=PriorityQueue.NORMAL_PRIORITY, urgent=False):
        #TBD: interrupt one worker for priority 0
        if urgent:
            for w in self._threads:
                # This is pretty poor heuritics
                if w.piece and w.piece<piece-PieceCache.size or w.piece>piece+PieceCache.size:
                    logger.debug('Will interrupt piece %d in thread %s', w.piece, threading.current_thread().name)
                    w.interrupt()
        self._queue.put_piece(piece, priority)
            
            
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
        
    def request_piece(self, piece, priority, urgent=False):
        if self._pool:
            self._pool.add_piece(piece,priority, urgent)
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
            c0=c0 or HTTPLoader(uri, 0, self.resolver_class)
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
            self._prioritize_fn(piece,idx, idx==0 and piece < self.last_piece-1) #last 2 pieces are special, we do not want them to interrupt other downloads
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
        
        
            
    
