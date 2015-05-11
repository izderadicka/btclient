#!/usr/bin/env python

import signal
import sys
import time


def write_to_log(msg):
    with open('sigtest.log','w') as f:
        f.write(msg)
        f.write('\n')
    print >>sys.stderr, msg
        
def on_signal_exit(sig,frame):
    write_to_log('Received signal %d'%sig)
    sys.exit(sig)
    
signal.signal(signal.SIGHUP,on_signal_exit)
signal.signal(signal.SIGTERM,on_signal_exit)
signal.signal(signal.SIGINT,on_signal_exit)

if __name__=='__main__':
    while True:
        time.sleep(1)
