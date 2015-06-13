#!/usr/bin/env python


import unittest
import sys
import os.path

sys.path.append(os.path.join(os.path.dirname(__file__),'../src'))

loader=unittest.defaultTestLoader

suite = loader.discover('.')

runner=unittest.TextTestRunner()

runner.run(suite)
