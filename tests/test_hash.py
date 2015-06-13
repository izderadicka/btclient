'''
Created on Apr 27, 2015

@author: ivan
'''
import unittest
import os
from opensubtitle import OpenSubtitles

fname = os.path.join(os.path.dirname(__file__),'breakdance.avi')

class Test(unittest.TestCase):


    def test_hash(self):
        size = os.stat(fname).st_size
        self.assertEqual(size, 12909756)
        hash=OpenSubtitles.hash_file(open(fname,'rb'), size)
        self.assertEqual(hash, '8e245d9679d31e12')


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.test_hash']
    unittest.main()