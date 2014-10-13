BTClient
--------

Simple Bit Torrent client (command line),  that enables sequential download and then streams video to 
video player (via stdin or http) when got enough of the file content to start(deafult is 2%).

Usage: btclient torrent_file_or_url

Accepts either torrent file path or magnet link or http(s) link to torrent file.

From torrent file chooses biggest video file, starts to download and sends it to video player (works with mplayer or vlc)

Requires libtorrent and its python bindings and gnome-terminal.


Install
-------

Now manual:
```
sudo apt-get install python-libtorrent 
sudo pip install hachoir-metadata hachoir-core hachoir-parser
cp btclient.py btclient somewhere
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


