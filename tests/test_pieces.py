'''
Created on Mar 23, 2015

@author: ivan
'''
import unittest
import libtorrent as lt
from btclient import BTPieces

class Peer_Request(object):
    def __init__(self, piece, start):
        self.piece=piece
        self.start=start
        
        
class Test(unittest.TestCase):

    def test_create(self):
        size=10*1024
        fmap=Peer_Request(0, 512 )
        
        piece_size=1024
        
        p=BTPieces(fmap, size, [False]*11, piece_size)
        self.assertEqual(11, len(p._pieces))
        self.assertEqual(10, p._last_piece)
        
        self.assertEqual(1, p.piece_no(512))
        self.assertEqual(0, p.piece_no(511))
        self.assertEqual(1, p.piece_no(511+1024))
        self.assertEqual(2, p.piece_no(512+1024))
        self.assertEqual(10, p.piece_no(size-1))
        
        try:
            p.piece_no(size)
            self.fail("Should fail")
        except ValueError:
            pass
        
        self.assertEqual(512, p.remains(0))
        self.assertEqual(512, p.last_piece_size)
        
    def test_ready(self):
        size=10*1024
        fmap=Peer_Request(0, 512 )
        
        piece_size=1024
        
        p=BTPieces(fmap, size, [False]*11, piece_size)
        
        self.assertEqual((0,0), p.can_read(0,1))
        self.assertFalse(p.has_offset(0))
        p.update_progress([True]+ ([False] *10))
        self.assertEqual((1,None), p.can_read(0,1))
        self.assertEqual((512,1), p.can_read(0,1024))
        self.assertTrue(p.has_offset(256))
        self.assertTrue(p.has_offset(0))
        self.assertFalse(p.has_offset(900))
        
        p.update_progress([True]*5+ ([False] *6))
        self.assertEqual((4*1024,None), p.can_read(0, 4*1024))
        self.assertEqual((3*1024+512,5), p.can_read(1024, 4*1024))
        self.assertTrue(p.has_offset(4*1024+511))
        self.assertFalse(p.has_offset(4*1024+512))
        
        p.update_progress([True]*11)
        self.assertEqual((256,None), p.can_read(9*1024+3*256, 256))
        self.assertEqual((256,None), p.can_read(9*1024+3*256, 512))
        self.assertTrue(p.has_offset(10*1024-1))
        try:
            self.assertFalse(p.has_offset(10*1024))
            self.fail('Should fail')
        except ValueError:
            pass
        
        
        

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.test_create']
    unittest.main()