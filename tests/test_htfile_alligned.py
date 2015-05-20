'''
Created on Aug 26, 2014

@author: ivan
'''
import unittest
from htclient import HTFile
import os
from StringIO import StringIO
import tempfile
import time
import random
from time import sleep
test_file='test_file.py'
from threading import Thread
from Queue import Queue

TEST_FILE_SIZE=15*1024

       
class DummyClient(Thread):
    def __init__(self, f,delay=0):
        Thread.__init__(self, name="DummyClient")
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
            print "Sent piece no %d" % pc
                
        

class Test(unittest.TestCase):

    
    def setUp(self):
        f=tempfile.NamedTemporaryFile(delete=False)
        s=os.urandom(TEST_FILE_SIZE)
        f.write(s)
        self.fname= f.name
        f.close()

    def tearDown(self):
        os.remove(self.fname)   
        
        
    
     
        
    def test_read_alligned(self, delay=0.001, piece_size=1024, read_block=2000):
        size=TEST_FILE_SIZE
        client=DummyClient(self.fname, delay)
        bt = HTFile(self.fname, './', size, piece_size, client.request)
        self.assertEqual(bt.last_piece,14)
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
        self.assertTrue(bt.is_complete)
        self.assertEqual(bt.downloaded, size)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        c.close()
        
        
    def test_read_nodelay(self):
        self.test_read_alligned(0) 
        
    
    def test_seek3(self):
        size=TEST_FILE_SIZE
        
        client=DummyClient(self.fname)
        bt = HTFile(self.fname, './', size, 512, client.request)
        self.assertEqual(bt.last_piece, 29)
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
            ref=f.read(size-555)
        self.assertTrue(not bt.is_complete)
        self.assertEqual(bt.downloaded, size-512)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        c.close()
        
    def test_seek_end(self):
        size=TEST_FILE_SIZE
        
        client=DummyClient(self.fname)
        bt = HTFile(self.fname, './', size, 1024, client.request)
        self.assertEqual(bt.last_piece, 14)
        client.serve(bt)
        buf=StringIO()
        c=bt.create_cursor()
        c.seek(size-64)
        while True:
            sz=8
            res=c.read(sz)
            if res:
                buf.write(res)
            else:
                break
        with open(self.fname, 'rb') as f:
            f.seek(size-64)
            ref=f.read(64)
        self.assertTrue(not bt.is_complete)
        self.assertEqual(bt.downloaded, 1024)
        self.assertEqual(len(ref), len(buf.getvalue()))
        self.assertEqual(ref, buf.getvalue())
        c.close()
        
        
    
        

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()