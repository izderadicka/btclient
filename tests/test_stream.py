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
test_file='dejavu/DejaVuSans.ttf'
test_base='/usr/share/fonts/truetype/'



class Test(unittest.TestCase):


    def setUp(self):
        
        size = os.stat(os.path.join(test_base, test_file)).st_size
        self.tf_size=size
        self.file=BTFile(test_file, test_base, size, 1)
        self.server= StreamServer(('127.0.0.1', 5001), BTFileHandler, self.file)
        self.t=Thread(target=self.server.handle_request)
        self.t.start()
        
    def update_file(self,n=16384):
            size=min(self.file.done+n, self.file.size)
            self.file.update_done(size)
            if size< self.file.size:
                t=Timer(0.005, self.update_file, args=[n])
                t.daemon=True
                t.start()
        
        


    def tearDown(self):
        self.server.stop()
        self.file.close()
        time.sleep(0.1)
        


    def notest_get_all(self):
        #self.update_file(16)
        self.file.update_done(self.tf_size)
        r=urllib2.urlopen('http://localhost:5001/'+self.file.path)
        res=r.read()
        
        self.assertEqual(len(res),self.tf_size)
        
        
    def notest_get_gradually(self):
        self.update_file(16384)
        #self.file.update_done(self.tf_size)
        r=urllib2.urlopen('http://localhost:5001/'+self.file.path)
        res=r.read()
        
        self.assertEqual(len(res),self.tf_size)
        
    def test_range(self):
        self.update_file(16384)
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
        
        self.assertEqual(buf.tell(),self.tf_size - 100000)
        
        
        


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()