'''
Created on Aug 26, 2014

@author: ivan
'''
import unittest
from btclient import BTFile
import os
from StringIO import StringIO
import tempfile
test_file='test_file.py'
from threading import Timer

TEST_FILE_SIZE=15*1024+300

class Peer_Request(object):
    def __init__(self, piece, start, length):
        self.piece=piece
        self.start=start
        self.length=length

class Test(unittest.TestCase):

    
    def setUp(self):
        f=tempfile.NamedTemporaryFile(delete=False)
        s=os.urandom(TEST_FILE_SIZE)
        f.write(s)
        self.fname= f.name
        f.close()

    def tearDown(self):
        os.remove(self.fname)        
        
    def test_read(self):
        size=os.stat(self.fname).st_size
        ref= open(self.fname).read()
        self.assertEqual(TEST_FILE_SIZE, size)
        fmap=Peer_Request(1, 700, size)
        piece_size=1024
        pieces=[False]+16*[True]
        bt = BTFile(self.fname, './',1,fmap, pieces, piece_size, lambda _: None)
        buf=StringIO()
        c=bt.create_cursor()
        while True:
            res=c.read(10)
            if res:
                buf.write(res)
            else:
                break
        self.assertEqual(ref, buf.getvalue())
        c.close()
        
        
        
    def test_seek_0(self):
        size=os.stat(self.fname).st_size
        ref= open(self.fname).read()
        self.assertEqual(TEST_FILE_SIZE, size)
        fmap=Peer_Request(1, 700, size)
        piece_size=1024
        pieces=[False]+16*[True]
        bt = BTFile(self.fname, './',1,fmap, pieces, piece_size, lambda _: None)
        buf=StringIO()
        c=bt.create_cursor()
        
        c.seek(0)
        for i in range(2): 
            res=c.read()
            self.assertEqual(ref,res)
            c.seek(0)
            
        c.close()
        self.assertEqual(0, len(bt._cursors))
         
         
    def test_read_blocked(self):
        size=os.stat(self.fname).st_size
        ref= open(self.fname).read()
        self.assertEqual(TEST_FILE_SIZE, size)
        fmap=Peer_Request(1, 700, size)
        piece_size=1024
        pieces=[False]+1*[True]+15*[False]
        bt = BTFile(self.fname, './',1,fmap, pieces, piece_size, lambda _: None)
        buf=StringIO()
        c=bt.create_cursor()
        
        
        def update(rd):
            
            bt.update_pieces([False]+ rd*[True]+ (16-rd)*[False])
            if rd<=16:
                Timer(0.05, update, args=(rd+1,)).start()
         
        Timer(0.1, update, args=(2,)).start()
       
        while True:
            res=c.read(100)
            if res:
                buf.write(res)
            else:
                break
        self.assertEqual(ref, buf.getvalue())
        c.close()
         
    def test_seek(self):
        size=os.stat(self.fname).st_size
        f=open(self.fname)
        f.seek(2000)
        ref= f.read()
        f.close()
        self.assertEqual(TEST_FILE_SIZE, size)
        
        fmap=Peer_Request(1, 700, size)
        piece_size=1024
        pieces=[False]+1*[True]+15*[False]
        bt = BTFile(self.fname, './',1,fmap, pieces, piece_size, lambda _: None)
        buf=StringIO()
        c=bt.create_cursor()
        
        def update(rd):
            bt.update_pieces([False]+ rd*[True]+ (16-rd)*[False])
            if rd<=16:
                Timer(0.05, update, args=(rd+1,)).start()
         
        Timer(0.1, update, args=(2,)).start()
        c.seek(2000)
        while True:
            res=c.read(513)
            if res:
                buf.write(res)
            else:
                break
        self.assertEqual(ref, buf.getvalue())
        c.close()


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()