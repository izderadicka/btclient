#!/usr/bin/env python


import unittest
import sys

sys.path.append('../src')

loader=unittest.defaultTestLoader

suite = loader.discover('.')

runner=unittest.TextTestRunner()

runner.run(suite)
