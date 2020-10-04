BTClient
--------
[![Build Status](https://travis-ci.org/izderadicka/btclient.svg?branch=master)](https://travis-ci.org/izderadicka/btclient)

Simple Bit Torrent client (command line),  that enables sequential download and then streams video to 
video player (via http or stdin, but stdin is not seekable), when got enough of the file content is available
to start playback. Also supports HTTP sources, when it can download video from several connections 
concurrently and then stream it to the player. Can work with file sharing services, if plugin is provided 
to resolve file link. 

```
usage: btclient.py [-h] [-d DIRECTORY] [-p {mplayer,vlc}]
                   [--player-path PLAYER_PATH] [--port PORT]
                   [--debug-log DEBUG_LOG] [--stdin] [--print-pieces]
                   [-s SUBTITLES] [--stream] [--no-resume] [-q]
                   [--delete-on-finish] [--clear-older CLEAR_OLDER]
                   [--bt-download-limit BT_DOWNLOAD_LIMIT]
                   [--bt-upload-limit BT_UPLOAD_LIMIT]
                   [--listen-port-min LISTEN_PORT_MIN]
                   [--listen-port-max LISTEN_PORT_MAX] [--choose-subtitles]
                   [--trace]
                   url


```

Accepts either torrent file path or magnet link or http(s) link to torrent file or http link to file.

From torrent file chooses the biggest video file, starts to download it  and sends it to video player 
(works with mplayer or vlc).

Can also download subtitles for current video file (option -s - uses opensubtitles.org API).

Requires libtorrent (1.0.x) and its python bindings,  requests,  hachoir-metadata, hachoir-parser and hachoir-core 
python libraries. 
Optionally  beautifulsoup4 and adecaptcha for plugins.


Install
-------

BTClient is still python2 - so it might require some manual actions during install ( assure you have python 2.7, also hachoir is not on pip anymore - so install from debian packages or manualy for hachoir directory)

Now manual (Ubuntu 14.04):
```
git clone --depth 1 https://github.com/izderadicka/btclient.git
cd btclient/
./install.sh
#optionally you can run tests
#python tests/all.py
cp -r src  somewhere
#can modify btclient script to your preferences
sudo ln -s /somewhere/btclient /usr/local/bin
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


