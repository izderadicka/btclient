'''
Created on May 1, 2015

@author: ivan
'''
import unittest
import tempfile
import os.path
import shutil
from cache import Cache
import libtorrent as lt
import re

TEST_TORRENT=os.path.join(os.path.dirname(__file__), 'test.torrent')

class Test(unittest.TestCase):


    def setUp(self):
        self.dir=tempfile.mkdtemp("TEST")


    def tearDown(self):
        shutil.rmtree(self.dir)


    def test_parse_magnet(self):
        m="magnet:?xt=urn:btih:47DF370B841D1477C160A96E20A887C5C458010C&dn=The+Zero+Theorem+%282013%29+%5B720p%5D&tr=http%3A%2F%2Ftracker.yify-torrents.com%2Fannounce&tr=udp%3A%2F%2Ftracker.openbittorrent.com%3A80&tr=udp%3A%2F%2Ftracker.publicbt.org%3A80&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969&tr=udp%3A%2F%2Ftracker.leechers-paradise.org%3A6969&tr=udp%3A%2F%2Fopen.demonii.com%3A1337&tr=udp%3A%2F%2Fp4p.arenabg.ch%3A1337&tr=udp%3A%2F%2Fp4p.arenabg.com%3A1337"
        ih=Cache.hash_from_magnet(m)
        self.assertEqual(len(ih), 40)
        self.assertEqual(ih, "47DF370B841D1477C160A96E20A887C5C458010C" )
        m="magnet:?xt=urn:btih:440008e244e8398522d2271318afc2f938274d56&dn=Alela+Diane+-++The+Pirate%27s+Gospel&tr=udp%3A%2F%2Fopen.demonii.com%3A1337&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969&tr=udp%3A%2F%2Fexodus.desync.com%3A6969"
        ih=Cache.hash_from_magnet(m)
        self.assertEqual(len(ih), 40)
        self.assertEqual(ih, "440008e244e8398522d2271318afc2f938274d56".upper() )
        m='magnet:?xt=urn:btih:VQV6ME7OQAENNYPFHITASWARN6PXEO6I&dn=Game.of.Thrones.S01E05.720p.HDTV.x264-CTU&tr=udp://tracker.openbittorrent.com:80&tr=udp://open.demonii.com:80&tr=udp://tracker.coppersurfer.tk:80&tr=udp://tracker.leechers-paradise.org:6969&tr=udp://exodus.desync.com:6969'
        ih=Cache.hash_from_magnet(m)
        self.assertEqual(len(ih), 40)
        self.assertTrue(re.match('^[0-9A-F]+$',ih))
        
        
    def test_create(self):
        c=Cache(self.dir)
        c.close()
        
    def test_torrent(self):
        ti=lt.torrent_info(TEST_TORRENT)
        ih=str(ti.info_hash())
        c=Cache(self.dir)
        url='http:/nekde/neco'
        c.file_complete(ti, url)
        tmp_file=os.path.join(self.dir, '.cache' ,ih.upper()+'.torrent')
        self.assertTrue(os.path.exists(tmp_file))
        c.close()
        c=Cache(self.dir)
        res=c.get_torrent(url)
        self.assertEqual(res, tmp_file)
        c.close()
        
        

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()