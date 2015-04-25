'''
Created on Aug 27, 2014

@author: ivan
'''
import unittest
from btclient import BTFile, StreamServer, BTFileHandler
import os
from threading import Timer, Thread
import urllib2
import time
import StringIO
import tempfile

from test_file import Peer_Request
import cProfile
import pstats
from time import sleep
from test_file import DummyClient

TEST_FILE_SIZE= 12111222
piece_size=2048

import logging
logging.basicConfig(level=logging.DEBUG)


class Test(unittest.TestCase):


    def setUp(self):
        
        f=tempfile.NamedTemporaryFile(delete=False)
        s=os.urandom(TEST_FILE_SIZE)
        f.write(s)
        self.fname= f.name
        f.close()
        
        size=os.stat(self.fname).st_size
        fmap=Peer_Request(0, 2000)
        self.tf_size=size
        fname=os.path.split(self.fname)[1]
        self.client=DummyClient(self.fname, 0)
        self.file=BTFile(fname, '/tmp',1,size, fmap, piece_size, self.client.request)
        self.client.serve(self.file)
        self.server= StreamServer(('127.0.0.1', 5001), BTFileHandler, self.file)
        self.t=Thread(target=self.server.handle_request)
        self.t.start()


    def tearDown(self):
        self.server.stop()
        os.remove(self.fname) 
        time.sleep(0.1)
        


    def notest_get_all(self):
        self.update_file()
        
        r=urllib2.urlopen('http://localhost:5001/'+self.file.path)
        res=r.read()
        
        self.assertEqual(len(res),self.tf_size)
        
        
        
    def test_range(self):
        
        req=urllib2.Request('http://localhost:5001/'+self.file.path, 
                            headers={'Range': 'bytes=100000-'})
        res=urllib2.urlopen(req)
        buf=StringIO.StringIO()
        while True:
            pc=res.read(50000)
            if pc:
                buf.write(pc)
            else:
                break
        
        self.assertEqual(buf.tell(),self.tf_size - 100000-2000)
        with open(self.fname, 'rb') as f:
            f.seek(102000)
            ch=f.read()
            self.assertEqual(buf.getvalue(),ch)
        
        
        


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(Test)
    def runtests():
        unittest.TextTestRunner().run(suite)

    s = cProfile.run('runtests()',filename='test_stream.statste')
#     pr = cProfile.Profile()
#     pr.enable()
#     runtests()    
#     pr.disable()
#     s = StringIO.StringIO()
#     sortby = 'cumulative'
#     ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
#     ps.print_stats()
#     print s.getvalue()