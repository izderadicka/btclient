'''
Created on Aug 26, 2014

@author: ivan
'''
import unittest
from btclient import BTFile
import os
from StringIO import StringIO
test_file='test_file.py'
from threading import Timer

class Test(unittest.TestCase):

    def test_seek_0(self):
        size=os.stat(test_file).st_size
        ref= open(test_file).read()
        bt = BTFile(test_file, './', size,1)
        bt.seek(0)
        bt.update_done(size)
        for i in range(2): 
            res=bt.read()
            self.assertEqual(ref,res)
            bt.seek(0)
            
        
    def test_read(self):
        size=os.stat(test_file).st_size
        ref= open(test_file).read()
        bt = BTFile(test_file, './', size,1)
        bt.update_done(size)
        buf=StringIO()
        while True:
            res=bt.read(10)
            if res:
                buf.write(res)
            else:
                break
        self.assertEqual(ref, buf.getvalue())
        
        
    def test_read_blocked(self):
        size=os.stat(test_file).st_size
        ref= open(test_file).read()
        bt = BTFile(test_file, './', size,1)
        def update():
            size=min(bt.done+100, bt.size)
            bt.update_done(size)
            if size< bt.size:
                Timer(0.05, update).start()
        
        Timer(0.1, update).start()
        bt.reset()
        buf=StringIO()
        while True:
            res=bt.read(10)
            if res:
                buf.write(res)
            else:
                break
        self.assertEqual(ref, buf.getvalue())
        
    def test_seek(self):
        size=os.stat(test_file).st_size
        f=open(test_file)
        f.seek(200)
        ref= f.read()
        bt = BTFile(test_file, './', size,1)
        def update():
            size=min(bt.done+100, bt.size)
            bt.update_done(size)
            if size< bt.size:
                Timer(0.05, update).start()
        Timer(0.1, update).start()
        bt.seek(200)
        buf=StringIO()
        while True:
            res=bt.read(10)
            if res:
                buf.write(res)
            else:
                break
        self.assertEqual(ref, buf.getvalue())


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()