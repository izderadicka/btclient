'''
Created on May 6, 2015

@author: ivan
'''
import unittest
from plugins import load_plugins,find_matching_plugin
from htclient import HTTPLoader
import sys

class Test(unittest.TestCase):


    def test_load(self):
        plugs=load_plugins()
        
    def test_ulozto(self):
        url='http://www.ulozto.cz/xEtqWa87/jachyme-hod-ho-do-stroje-1974-mp4'
        cls=find_matching_plugin(url)
        try:
            import adecaptcha
            self.assertTrue(cls)
            loader=HTTPLoader(url, 0, cls)
        except ImportError:
            print >>sys.stderr, 'WARNIG - adecaptcha not install ulozto plugin will not be available'
        
        

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.test_load']
    unittest.main()