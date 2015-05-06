BTClient
--------

Simple Bit Torrent client (command line),  that enables sequential download and then streams video to 
video player (via http or stdin, but stdin is not seekable) when got enough of the file content to start 
playback

```
usage: btclient.py [-h] [-d DIRECTORY] [-p {mplayer,vlc}] [--port PORT]
                   [--debug-log DEBUG_LOG] [--stdin] [--print-pieces]
                   [-s SUBTITLES] [--stream] [--no-resume]
                   torrent
```

Accepts either torrent file path or magnet link or http(s) link to torrent file.

From torrent file chooses biggest video file, starts to download and sends it to video player (works with mplayer or vlc)

Requires libtorrent (1.0.4) and its python bindings,  gnome-terminal and hachoir python libraries.


Install
-------

Now manual:
```
#install libtorrent manually - latest 1.0.4 from 
sudo apt-get install libboost-system-dev libboost-chrono-dev libboost-python-dev libboost-random-dev
svn checkout svn://svn.code.sf.net/p/libtorrent/code/trunk libtorrent-code
./autotool.sh
./configure --enable-python-binding
make
sudo make install


sudo pip install hachoir-metadata hachoir-core hachoir-parser
cp -r src  somewhere
#can modify btclient script to your preferences
ln -s /somewhere/btclient /usr/local/bin
```

For desktop integration can copy desktop/btclient.desktop to ~/.local/share/applications.

In browser assure that browser asks for protocol handler

Check in your browser profile directory file mimeTypes.rdf and check this:
```
<RDF:Description RDF:about="urn:scheme:handler:magnet"
   NC:alwaysAsk="true">
```


License
-------

GPL v3


