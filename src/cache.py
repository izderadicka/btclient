'''
Created on Apr 28, 2015

@author: ivan
'''
import os.path
import shelve
import libtorrent as lt
import re
import logging
logger=logging.getLogger('cache')

class Cache(object):
    def __init__(self, path):
        if not os.path.isdir(path):
            raise ValueError('Invalid base directory')
        self.path=os.path.join(path, '.cache')
        if not os.path.isdir(self.path):
            os.mkdir(self.path)
        self._index_path=os.path.join(self.path, 'index')
        self._index=shelve.open(self._index_path)
        self._last_pos_path=os.path.join(self.path, 'last_position')
        self._last_pos=shelve.open(self._last_pos_path)
        
        
    def save(self, url, info_hash):
        self._index[url]=info_hash
        self._index.sync()
        
    def close(self):
        self._index.close()
        self._last_pos.close()
        
    def _tname(self, info_hash):
        return os.path.join(self.path, info_hash.upper()+'.torrent')
            
        
    def file_complete(self, torrent, url=None):
        info_hash=str(torrent.info_hash())
        nt=lt.create_torrent(torrent)
        tname=self._tname(info_hash)
        with open(tname, 'wb') as f:
            f.write(lt.bencode(nt.generate()))
        if url:
            self.save(url,info_hash)
           
    
    def get_torrent(self, url=None, info_hash=None):
        if url:
            info_hash=self._index.get(url)
        if not info_hash:
            return
        tname=self._tname(info_hash)    
        if os.access(tname,os.R_OK):
            logger.debug('Torrent is cached')
            return tname
     
    magnet_re=re.compile('xt=urn:btih:([0-9A-Fa-f]+)')   
    @staticmethod
    def hash_from_magnet(m):
        res=Cache.magnet_re.search(m)
        if res:
            return res.group(1).upper()
        else:
            raise ValueError('Not BT magnet link')
        
    def play_position(self, info_hash, secs):
        self._last_pos[info_hash]=secs
        
    def get_last_position(self, info_hash):
        return self._last_pos.get(info_hash) or 0
        
