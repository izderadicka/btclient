'''
Created on May 4, 2015

@author: ivan
'''
import unittest
from threading import Thread
import time
from htclient import HTTPLoader,HTFile
from btclient import StreamServer, BTFileHandler
import os
from StringIO import StringIO
import tempfile

PORT = 8001
URL="http://localhost:%d/breakdance.avi" % PORT
fname = os.path.join(os.path.dirname(__file__),'breakdance.avi')

class DummyFile(object):
    def __init__(self, path):
        self.path=os.path.basename(path)
        self._full_path=path
        self.size=os.stat(path).st_size
        
    def create_cursor(self,offset=None):
        f= open(self._full_path,'rb')
        if offset:
            f.seek(offset)
        return f

class Test(unittest.TestCase):


    def setUp(self):
        f=DummyFile(fname)
        self.server=StreamServer(('127.0.0.1',PORT), BTFileHandler, tfile=f,allow_range=True)
        self.server.run()


    def tearDown(self):
        #self.server.shutdown()
        pass
        


    def test(self):
        f=DummyFile(fname)
        piece_size=1024
        c=HTTPLoader(URL, 0)
        first=c.load_piece(0, piece_size)
        self.assertEqual(len(first.data), piece_size)
        self.assertEqual(first.piece,0)
        self.assertEqual(first.type,'video/x-msvideo')
        self.assertEqual(first.total_size, f.size)
        
        piece_size=2048*1024
        last_piece=f.size // piece_size
        
        buf=StringIO()
        tmp_file=tempfile.mktemp()
        base,tmp_file=os.path.split(tmp_file)
        htfile=HTFile(tmp_file, base, f.size, piece_size, lambda a,b: self.fail('Should not need prioritize'))
        for piece in xrange(last_piece+1):
            print "Piece %d"%piece
            p=c.load_piece(piece, piece_size)
            self.assertTrue(p.data)
            if piece!=last_piece:
                self.assertEqual(len(p.data), piece_size)
            if piece==last_piece:
                self.assertEqual(len(p.data), f.size % piece_size)
                
            buf.write(p.data)
            htfile.update_piece(piece, p.data)
        
        
        data=buf.getvalue()
        with f.create_cursor() as reader:
            ref=reader.read()
            
        self.assertEqual(data, ref, "Diffrent")
        
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
   
    