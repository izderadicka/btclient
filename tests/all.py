#!/usr/bin/env python


import unittest
import sys
import os.path

sys.path.append(os.path.join(os.path.dirname(__file__),'../src'))

loader=unittest.defaultTestLoader

suite = loader.discover('.')

runner=unittest.TextTestRunner()

res=runner.run(suite)
if res.errors or res.failures:
    print >>sys.stderr, 'SOME TESTS FAILED!'
    sys.exit(1)
