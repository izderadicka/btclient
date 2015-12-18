'''
Created on May 4, 2015

@author: ivan
'''
import unittest
from btclient import StreamServer, BTFileHandler
import os
from StringIO import StringIO
import requests

PORT = 8003
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
        with open(fname) as f:
            ref=f.read()
        res=requests.get(URL, stream=True)
        data=res.raw.read()
        res.close()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data,ref)
        
        res=requests.get(URL, stream=False)
        data=res.content
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data,ref)
        
        res=requests.get(URL, headers={'Range': 'bytes=1000-9000'})
        self.assertEqual(res.headers['Content-Range'], 'bytes 1000-9000/12909756')
        with open(fname) as f:
            f.seek(1000)
            ref=f.read(8001)
        self.assertEqual(res.content, ref)
        
            
        




if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
   
    