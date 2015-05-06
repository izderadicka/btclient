'''
Created on May 4, 2015

@author: ivan
'''
import unittest
from threading import Thread
import time
from htclient import HTTPLoader,Pool, HTFile
from btclient import StreamServer, BTFileHandler
from _imaging import path
import os
from StringIO import StringIO
import tempfile

PORT = 8000
URL="http://localhost:%d/breakdance.avi" % PORT

class DummyFile(object):
    def __init__(self, path):
        self.path=path
        self.size=os.stat(path).st_size
        
    def create_cursor(self,offset=None):
        f= open(self.path,'rb')
        if offset:
            f.seek(offset)
        return f

class Test(unittest.TestCase):


    def setUp(self):
        f=DummyFile('breakdance.avi')
        self.server=StreamServer(('127.0.0.1',PORT), BTFileHandler, tfile=f,allow_range=True)
        self.server.run()


    def tearDown(self):
        #self.server.shutdown()
        pass
        


    def test(self):
        f=DummyFile('breakdance.avi')
        piece_size=1024
        c=HTTPLoader(URL, 0)
        first=c.load_piece(0, piece_size)
        self.assertEqual(len(first.data), piece_size)
        self.assertEqual(first.piece,0)
        self.assertEqual(first.type,'video/x-msvideo')
        self.assertEqual(first.total_size, f.size)
        
        piece_size=2048*1024/2
        last_piece=f.size // piece_size
        
        tmp_file=tempfile.mktemp()
        base,tmp_file=os.path.split(tmp_file)
        htfile=HTFile(tmp_file, base, f.size, piece_size, lambda a,b: self.fail('Should not need prioritize'))
        pool=Pool(piece_size, [c,HTTPLoader(URL, 1),HTTPLoader(URL, 2)], htfile.update_piece)
        for i in xrange(last_piece+1):
            pool.add_piece(i, 10-i)
        while not htfile.is_complete:
            time.sleep(1)
            print htfile.pieces
        
        with f.create_cursor() as reader:
            ref=reader.read()
        
        buf=StringIO()
        with htfile.create_cursor() as reader:
            while True:
                d=reader.read()
                if not d:
                    break
                buf.write(d)
        data2=buf.getvalue() 
        self.assertEqual(len(data2),len(ref))    
        self.assertEqual(data2, ref, "Different")
            
        




if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
   
    