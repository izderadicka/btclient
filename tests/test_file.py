'''
Created on Aug 26, 2014

@author: ivan
'''
import unittest
from btclient import BTFile
import os
from StringIO import StringIO
import tempfile
import time
import random
from time import sleep
test_file='test_file.py'
from threading import Thread
from Queue import Queue

TEST_FILE_SIZE=15*1024+300

class Peer_Request(object):
    def __init__(self, piece, start):
        self.piece=piece
        self.start=start
        
class DummyClient(Thread):
    def __init__(self, f,delay=0):
        Thread.__init__(self)
        self.daemon=True
        if hasattr(f, 'read'):
            self.f=f
        else:
            self.f=open(f,'rb')
        self.q=Queue()
        self.delay=delay
        self.piece_cache={}
        
    def serve(self, btfile):  
        self.btfile=btfile  
        self.start()
        
    def request(self,n,idx):
        self.q.put((n,idx))
        
    def run(self):
        while True:
            pc,idx=self.q.get()
            if self.piece_cache.has_key(pc):
                data=self.piece_cache[pc]
            else:
                time.sleep(idx*self.delay)
                self.f.seek(self.btfile.piece_size *pc)
                data=self.f.read(self.btfile.piece_size)
                self.piece_cache[pc]=data
            self.btfile.update_piece(pc,data)
            print "Send piece no %d" % pc
            
            
        
    
        

class Test(unittest.TestCase):

    
    def setUp(self):
        f=tempfile.NamedTemporaryFile(delete=False)
        s=os.urandom(TEST_FILE_SIZE)
        f.write(s)
        self.fname= f.name
        f.close()

    def tearDown(self):
        os.remove(self.fname)   
        
        
    def test_read_ofs(self, delay=0.001, piece_size=1024, read_block=2000):
        ofs_start=1 * piece_size + 700
        size=TEST_FILE_SIZE - ofs_start
        fmap=Peer_Request(1, 700)
        
        client=DummyClient(self.fname, delay)
        bt = BTFile(self.fname, './',1, size, fmap, piece_size, client.request)
        client.serve(bt)
        buf=StringIO()
        c=bt.create_cursor()
        with open(self.fname, 'rb') as inf:
            ofs=ofs_start
            while True:
                sz=read_block
                res=c.read(sz)
                inf.seek(ofs)
                
                if res:
                    ch=inf.read(len(res))
                    
                    self.assertEqual(len(res), len(ch))
                    self.assertEqual(res,ch, msg="Unequal ot ofs %d"%ofs)
                    ofs+=len(ch)
                    
                    buf.write(res)
                else:
                    break
        with open(self.fname, 'rb') as f:
            f.seek(ofs_start)
            ref=f.read(size)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        c.close()     
        
    def test_read(self, delay=0.001, piece_size=1024, read_block=2000):
        size=TEST_FILE_SIZE 
        fmap=Peer_Request(0, 0)
        
        client=DummyClient(self.fname, delay)
        bt = BTFile(self.fname, './',1, size, fmap, piece_size, client.request)
        client.serve(bt)
        buf=StringIO()
        c=bt.create_cursor()
        with open(self.fname, 'rb') as inf:
            ofs=0
            while True:
                sz=read_block
                res=c.read(sz)
                inf.seek(ofs)
                
                if res:
                    ch=inf.read(len(res))
                    
                    self.assertEqual(len(res), len(ch))
                    self.assertEqual(res,ch, msg="Unequal ot ofs %d"%ofs)
                    ofs+=len(ch)
                    
                    buf.write(res)
                else:
                    break
        with open(self.fname, 'rb') as f:
            #f.seek(1 * piece_size + 700)
            ref=f.read(size)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        c.close()
        
        
    def test_read_nodelay(self):
        self.test_read(0) 
        
    def test_sizes(self):
        self.test_read(delay=0, piece_size=1024, read_block=11)
        self.test_read(delay=0, piece_size=233, read_block=3333)
         
    def test_seek(self):
        size=TEST_FILE_SIZE 
        fmap=Peer_Request(0, 0)
        
        client=DummyClient(self.fname)
        bt = BTFile(self.fname, './',1, size, fmap, 512, client.request)
        client.serve(bt)
        buf=StringIO()
        c=bt.create_cursor()
        c.seek(555)
        while True:
            sz=1024
            res=c.read(sz)
            if res:
                buf.write(res)
            else:
                break
        with open(self.fname, 'rb') as f:
            f.seek(555)
            ref=f.read(size)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        c.close()
        
    def test_starts_later(self):
        size=TEST_FILE_SIZE 
        fmap=Peer_Request(3, 15)
        client=DummyClient(self.fname)
        bt = BTFile(self.fname, './',1, size, fmap, 512, client.request)
        client.serve(bt)
        buf=StringIO()
        c=bt.create_cursor()
        while True:
            sz=1024
            res=c.read(sz)
            if res:
                buf.write(res)
            else:
                break
        ofs=3*512+15
        with open(self.fname, 'rb') as f:
            f.seek(ofs)
            ref=f.read(size)
        self.assertEqual(len(buf.getvalue()), TEST_FILE_SIZE-ofs)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        c.close()
        
        
        
    def test_seek2(self):
        size=TEST_FILE_SIZE 
        fmap=Peer_Request(0, 0)
        client=DummyClient(self.fname)
        bt = BTFile(self.fname, './',1, size, fmap, 768, client.request)
        client.serve(bt)
        c=bt.create_cursor()
        c.seek(555)
        buf=StringIO()
        while True:
            sz=1024
            res=c.read(sz)
            if res:
                buf.write(res)
            else:
                break
        with open(self.fname, 'rb') as f:
            f.seek(555)
            ref=f.read(size)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        
        buf=StringIO()
        c.seek(10000)
        while True:
            sz=512
            res=c.read(sz)
            if res:
                buf.write(res)
            else:
                break
        with open(self.fname, 'rb') as f:
            f.seek(10000)
            ref=f.read(size)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        
        with open(self.fname, 'rb') as f:
            for _i in xrange(10):
                seek=random.randint(0,size)
                c.seek(seek)
                res=c.read(100)
                f.seek(seek)
                ref=f.read(len(res))
                self.assertTrue(res,ref)
        
        c.close()
        
    def test_clone(self, close_first=False):
        size=TEST_FILE_SIZE 
        fmap=Peer_Request(0, 0)
        
        client=DummyClient(self.fname)
        bt = BTFile(self.fname, './',1, size, fmap, 512, client.request)
        client.serve(bt)
        c=bt.create_cursor()
        c.seek(5000)
        c.read(100)
        sleep(0.1)
        self.assertTrue(all(c._cache._cache))
        if close_first:
            c.close()
        c2=bt.create_cursor(offset=5000)
        self.assertTrue(all(c2._cache._cache))
        def no(*args):
            raise Exception('Should not be called')
        client.request=no
        c2.seek(5000)
        c2.read(100)
        
    def test_clone2(self):
        self.test_clone(True)
      
        
        

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()