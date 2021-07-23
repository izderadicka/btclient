#!/bin/bash

#install libtorrent manually - needs libboost development libs 
sudo apt-get update
sudo apt-get install -y autoconf libtool libssl-dev  curl git python2-dev zenity
# need older version of libboost
sudo apt-get install -y libboost-system1.67-dev libboost-python1.67-dev libboost-chrono1.67-dev  libboost-random1.67-dev
# Do not use master, but latest 1.1.x version in RC_1_1 branch
git clone -b RC_1_1 --depth 1 https://github.com/arvidn/libtorrent.git libtorrent-code
cd libtorrent-code
./autotool.sh
./configure --enable-python-binding
make
sudo make install
sudo ldconfig

# sudo apt-get install -y python-hachoir-core python-hachoir-parser python-hachoir-metadata
# untar legacy versions of hachoir
cd ../src
tar xzvf ../hachoir/hachoir-core_1.3.3.orig.tar.gz --strip-components=1 hachoir-core-1.3.3/hachoir_core
tar xzvf ../hachoir/hachoir-metadata_1.3.3.orig.tar.gz --strip-components=1  hachoir-metadata-1.3.3/hachoir_metadata
tar xzvf ../hachoir/hachoir-parser_1.3.4.orig.tar.gz --strip-components=1  hachoir-parser-1.3.4/hachoir_parser
cd ..
#install pip2
curl https://bootstrap.pypa.io/pip/2.7/get-pip.py --output get-pip.py
sudo python2 get-pip.py
sudo rm /usr/local/bin/pip # we want pip command to default to pip3
pip2 install -r requirements.txt