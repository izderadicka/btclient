'''
Created on May 3, 2015

@author: ivan
'''

import urllib2
import os.path
import pickle
from common import AbstractFile, BaseClient, Hasher
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

logger=logging.getLogger('htclient')

Piece=namedtuple('Piece', ['piece','data','total_size', 'type'])

class HTTPLoader(object):
    
    UA_STRING=['Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0',
               'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.0 Safari/537.36',
               'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.75.14 (KHTML, like Gecko) Version/7.0.3 Safari/7046A194A']
    class Error(Exception):
        pass
    def __init__(self,url,id):
        self._client=urllib2.build_opener(urllib2.HTTPCookieProcessor(CookieJar()))
        self.url=self.resolve_file_url(url)
        self.id=id
        self.user_agent=self._choose_ua()
        
        
    def resolve_file_url(self, url):
        return url
        
    def _choose_ua(self):
        return HTTPLoader.UA_STRING[random.randint(0,len(HTTPLoader.UA_STRING)-1)]
    
    
    RANGE_RE=re.compile(r'bytes\s+(\d+)-(\d+)/(\d+)')
    def _parse_range(self, r):
        m=HTTPLoader.RANGE_RE.match(r)
        if not m:
            raise HTTPLoader.Error('Invalid range header')
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    
    def load_piece(self, piece_no, piece_size):
        start=piece_no*piece_size
        headers={'User-Agent':self.user_agent,
                 'Range': 'bytes=%d-'%start}
        req=urllib2.Request(self.url, headers=headers)
        res=None
        retries=2
        while retries:   
            try:
                res=self._client.open(req, timeout=10)
                break
            except (IOError, urllib2.HTTPError, BadStatusLine, IncompleteRead, socket.timeout) as e:
                if isinstance(e, urllib2.HTTPError) and hasattr(e,'code') and str(e.code)=='404':
                    raise HTTPLoader.Error('Url %s not found'%self.url)
        
                logging.warn('IO or HTTPError (%s) while trying to get url %s, will retry ' % (str(e),self.url))
                retries-=1
                time.sleep(1)
        if not res:
            raise HTTPLoader.Error('Cannot load resource %s' % self.url)
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
        
        data=res.read(piece_size)
        
        res.close()
        return Piece(piece_no,data,size,type_header)
                                          

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
    def __init__(self, piece_size,loaders, cb):
        self.piece_size=piece_size
        self._cb=cb
        self._queue=PriorityQueue()
        self._running=True
        self._threads=[Thread(name="worker %d"%i, target=self.work, args=[l]) for i,l in enumerate(loaders)]
        for t in self._threads:
            t.daemon=True
            t.start()
        
            
    def work(self, loader):
        while self._running:
            pc=self._queue.get_piece()
            if not self._running:
                break
            p=loader.load_piece(pc,self.piece_size)
            self._cb(p.piece,p.data)
            
    def stop(self):
        self._running=False
        #push some dummy tasks to assure workers ends
        for i in xrange(len(self._threads)):
            self._queue.put_piece(i, PriorityQueue.NO_DOWNLOAD)
            
    def add_piece(self, piece, priority=PriorityQueue.NORMAL_PRIORITY, remove_previous=False):
        self._queue.put_piece(piece, priority, remove_previous)
            
            
class HTClient(BaseClient):
    def __init__(self, path_to_store, args=None,piece_size=2*1024*1024,no_threads=3):
        BaseClient.__init__(self, path_to_store)
        self._pool=None
        self._no_threads=no_threads
        self.piece_size=piece_size
        self._last_downloaded=None
    
    def update_piece(self,piece, data):
        self._file.update_piece(piece, data)
        
    def start_url(self, uri):
        c0=HTTPLoader(uri, 0)
        p=c0.load_piece(0, self.piece_size)
        path=urlparse.urlsplit(uri)[2]
        if path.startswith('/'):
            path=path[1:]
        self._pool=Pool(self.piece_size, [c0]+[HTTPLoader(uri,i) for i in xrange(1,self._no_threads)],
                         self.update_piece)
        
        self._file=HTFile(path, self._base_path, p.total_size, self.piece_size, self._pool.add_piece)
        self.update_piece(0, p.data)
        for i in xrange(1, self._file.last_piece+1):
            self._pool.add_piece(i)
            
        self.hash=Hasher(self._file, self._on_file_ready)
        self._monitor.start()
            
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
        download_rate= (downloaded - self._last_downloaded[1]) / (tick-self._last_downloaded[0]) if self._last_downloaded else 0
        total_size=self.file.size if self.file else 0
        threads=self._no_threads
        desired_rate= self._file.byte_rate if self._file else 0
        
        self._last_downloaded=(tick, downloaded)
        return HTClient.Status(state,downloaded, download_rate, total_size,threads,desired_rate)
        
    
    def close(self):
        BaseClient.close(self)
        if self._file:
            self._file.close()
            
    def print_status(self, s, client):
        color=''
        progress=s.downloaded / float(s.total_size) * 100if s.total_size else 0
        total_size=s.total_size / 1048576.0
        
        print '\r%.2f%% (of %.1fMB) down: %s%.1f kB/s\033[39m(need %.1f)  %s' % \
            (progress, total_size, 
             color, s.download_rate/1000.0, s.desired_rate/1000.0 if s.desired_rate else 0.0,
            s.state),
        sys.stdout.write("\033[K")
        sys.stdout.flush()
        
                    

class HTFile(AbstractFile):
    def __init__(self, path, base, size, piece_size=2097152, prioritize_fn=None):
        AbstractFile.__init__(self, path, base, size, piece_size)
        self._prioritize_fn=prioritize_fn
        self.pieces=[False for _i in xrange(self.last_piece+1)]
        if not os.path.exists(self.full_path):
            self._allocate_file()
        else:
            sz=os.stat(self.full_path).st_size
            if sz==size:
                #get pieces file
                pcs_file=self.pieces_index_file
                if os.access(pcs_file, os.R_OK):
                    with open(pcs_file,'rb') as f:
                        pcs=pickle.load(f)
                    if isinstance(pcs, list) and len(pcs)==self.last_piece+1:
                        self.pieces=pcs
                    else:
                        logger.warn('Invalid pieces file %s',pcs_file)
            else:
                logger.warn("Invalid file size: %s", self.full_path)
                self.remove()
                self._allocate_file()
                
        self._file=open(self.full_path,'r+b')
    
    @property    
    def pieces_index_file(self):
        return self.full_path+'.pieces'
    
                
    def _allocate_file(self):
        #sparecely allocate file 
        with open(self.full_path,'ab') as f:
            f.truncate(self.size)
            
            
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
    
    def close(self):
        self._file.close()
        with open(self.pieces_index_file, 'wb') as f:
            pickle.dump(self.pieces,f)
            
    
        
    
