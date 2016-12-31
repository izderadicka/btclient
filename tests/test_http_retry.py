'''
Created on Dec 31, 2016

@author: ivan
'''
import unittest
from htclient import HTTPLoader
import time


class Test(unittest.TestCase):


    def test500(self):
        loader = HTTPLoader('http://nothing', 0)
        res = loader.open('http://httpbin.org/status/200')
        start = time.time()
        try:
           
            res = loader.open('http://httpbin.org/status/503')
            self.fail('should rise error')
        except loader.Error,e:
            print e
            
        
        dur = time.time() - start
        print dur
        self.assertTrue(dur > 3)


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()