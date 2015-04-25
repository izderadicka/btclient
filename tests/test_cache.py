'''
Created on Apr 22, 2015

@author: ivan
'''
import unittest
from btclient import PieceCache
import os
from StringIO import StringIO
from Queue import Queue
from threading import Thread
from time import sleep

TEST_FILE_SIZE=10000

class DummyBTFile(object):
    def __init__(self, piece_size, size=TEST_FILE_SIZE, offset=0, appendix=0):
        self.size=size
        self.piece_size=piece_size
        self.data=os.urandom(size+offset+appendix)
        self.first_piece=0
        self.q= Queue()
        self.t=Thread(target=self.send_pieces)
        self.t.daemon=True
        self.t.start()
        self.last_piece=size/piece_size
        self.offset=offset
        
    def map_piece(self,n):
        return (n+self.offset) // self.piece_size , (n+self.offset) % self.piece_size
    def prioritize_piece(self, n, idx):
        self.q.put((n, self.data[self.piece_size*n: self.piece_size* (n+1)]))
    def send_pieces(self):
        while True:
            pc=self.q.get()   
            self.cache.add_piece(*pc)
            print "Sent piece %d" % pc[0]
    def get_cache(self):
        self.cache=PieceCache(self)
        self.cache._request_piece=self.prioritize_piece
        return self.cache
        

class Test(unittest.TestCase):


    def test_read(self, sleep_time=0.01):
        f=DummyBTFile(10,80)
        c=f.get_cache()
        s=StringIO()
        pos=0
        while True:
            t=c.read(pos,8)
            if not t:
                return
            pos+=len(t)
            s.write(t)
            if sleep_time:
                sleep(sleep_time)
        res= s.getvalue()
        self.assertEqual(len(f.data), len(res))    
        self.assertEqual(f.data, res)
        
    def test_read_immediate(self):     
        self.test_read(None)   
        
        
    def test_read_larger(self):
        f=DummyBTFile(1024, 1024*56, offset=734, appendix=283)
        c=f.get_cache()
        s=StringIO()
        pos=0
        while True:
            t=c.read(pos,512)
            if not t:
                return
            pos+=len(t)
            s.write(t)
           
        res= s.getvalue()
        self.assertEqual(1024*56, len(res))    
        self.assertEqual(f.data[734:734+1024*56], res)
        
    def test_read_larger2(self):
        f=DummyBTFile(1024, 1024*56, offset=734, appendix=283)
        c=f.get_cache()
        s=StringIO()
        pos=0
        while True:
            t=c.read(pos,2000)
            if not t:
                return
            pos+=len(t)
            s.write(t)
           
        res= s.getvalue()
        self.assertEqual(1024*56, len(res))    
        self.assertEqual(f.data[734:734+1024*56], res)
        
    def test_read_larger2(self):
        f=DummyBTFile(1024, 1024*56, offset=734, appendix=283)
        c=f.get_cache()
        s=StringIO()
        pos=0
        while True:
            t=c.read(pos,2048)
            if not t:
                return
            pos+=len(t)
            s.write(t)
           
        res= s.getvalue()
        self.assertEqual(1024*56, len(res))    
        self.assertEqual(f.data[734:734+1024*56], res)


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()