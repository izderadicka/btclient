#!/bin/bash

#install libtorrent manually - needs libboost development libs 
sudo apt-get install -y autoconf libtool libssl-dev libboost-system-dev libboost-chrono-dev libboost-python-dev libboost-random-dev
# Do not use trunk, but latest 1.0 version, trunk was not working
apt-get install -y subversion
svn export svn://svn.code.sf.net/p/libtorrent/code/branches/RC_1_0 libtorrent-code
cd libtorrent-code
./autotool.sh
./configure --enable-python-binding
make
sudo make install
sudo ldconfig
cd ..
sudo pip install -r requirements.txt