#!/bin/bash

#install libtorrent manually - needs libboost development libs 
sudo apt-get install -y autoconf libtool libssl-dev libboost-system-dev libboost-python-dev #libboost-chrono-dev  libboost-random-dev
# Do not use master, but latest 1.0.x version in RC_1_0 branch
sudo apt-get install -y git
git clone -b RC_1_0 --depth 1 https://github.com/arvidn/libtorrent.git libtorrent-code
cd libtorrent-code
./autotool.sh
./configure --enable-python-binding
make
sudo make install
sudo ldconfig
cd ..
sudo pip install -r requirements.txt