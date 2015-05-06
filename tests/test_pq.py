'''
Created on May 4, 2015

@author: ivan
'''
import unittest
from htclient import PriorityQueue
import time
from threading import Thread
import Queue

class Test(unittest.TestCase):


    def test(self):
        q=PriorityQueue()
        for i in xrange(10):
            q.put_piece(i, 10)
            
        p=q.get_piece()
        self.assertEqual(p,0)
        
        q.put_piece(9,1)
        
        p=q.get_piece()
        self.assertEqual(p,9)
        
        q.remove_piece(1)
        p=q.get_piece()
        self.assertEqual(p,2)
        
        
        
    def test_conc(self):
        q=PriorityQueue()
        res=[]
        def add():
            for i in xrange(10):
                q.put_piece(i, 10)
                time.sleep(0.01)
        def read():
            while True:
                try:
                    p=q.get_piece(timeout=0.5)
                except Queue.Full:
                    break
                res.append(p)
                time.sleep(0.02)
            
            
        t1=Thread(name="t1",target=add)
        t1.start()
        t2=Thread(name="t2",target=read)
        t2.start()
        
        t1.join()
        t2.join()
        
        self.assertEqual(len(res),10)
            


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()