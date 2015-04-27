'''
Created on Apr 2, 2015

@author: ivan
'''
import xmlrpclib
import urllib2
import sys
import os.path
import gzip
from StringIO import StringIO
import logging
from subprocess import Popen
import subprocess
import struct
logger=logging.getLogger('opensubtitles')

class Urllib2Transport(xmlrpclib.Transport):
    def __init__(self, opener=None, https=False, use_datetime=0):
        xmlrpclib.Transport.__init__(self, use_datetime)
        self.opener = opener or urllib2.build_opener()
        self.https = https
    
    def request(self, host, handler, request_body, verbose=0):
        proto = ('http', 'https')[bool(self.https)]
        req = urllib2.Request('%s://%s%s' % (proto, host, handler), request_body)
        req.add_header('User-agent', self.user_agent)
        self.verbose = verbose
        return self.parse_response(self.opener.open(req))



class OpenSubtitles(object):
    USER_AGENT='OSTestUserAgent'
    def __init__(self, lang, user='', pwd=''):
        self._lang=lang
        self._proxy=xmlrpclib.ServerProxy('http://api.opensubtitles.org/xml-rpc',
                                          Urllib2Transport(use_datetime=True),
                                          allow_none=True, use_datetime=True)
        self._token=None
        self._user=user
        self._pwd=pwd
        
        
    def login(self):
        res=self._proxy.LogIn(self._user, self._pwd, 'en', self.USER_AGENT)
        self._parse_status(res)
        token=res.get('token')
        if token:
            self._token=token
        else:
            raise xmlrpclib.Fault('No token!')
        
    def _parse_status(self, res):
        if res.has_key('status'):
            code = res['status'].split()[0]
            if code !='200':
                raise xmlrpclib.Fault('Returned error status: %d (%s)'%(code,res))
            return True
        else:
            raise xmlrpclib.Fault('No status!')
        
    def search(self, filename, filesize=None,  filehash=None, limit=20):
        filename=os.path.split(filename)[1]
        name=os.path.splitext(filename)[0]
        query=[]
        if filehash and filesize:
            query.append({'sublanguageid':self._lang,'moviehash':filehash, 'moviebytesize':str(filesize)})
        query.append({'sublanguageid':self._lang, 'tag':filename })
        query.append({'sublanguageid':self._lang, 'query':name })
        res =self._proxy.SearchSubtitles(self._token,query, {'limit':limit})
        self._parse_status(res)
        data=res.get('data')
        
        return  data if data else []
    
    @staticmethod    
    def _sub_file(filename, ext):
        path, fname=os.path.split(filename)
        fname=os.path.splitext(fname)[0]
        return os.path.join(path, fname+'.'+ext)
    
    @staticmethod    
    def _base_name(filename):
        fname=os.path.split(filename)[1]
        return os.path.splitext(fname)[0]
    
    @staticmethod
    def hash_file(f, filesize): 
                 
        longlongformat = '<q'  # little-endian long long
        bytesize = struct.calcsize(longlongformat) 
            
        hash = filesize  # @ReservedAssignment
        if filesize < 65536 * 2: 
            raise ValueError("SizeError") 
        
        for _x in range(65536/bytesize): 
            buffer = f.read(bytesize)  # @ReservedAssignment
            (l_value,)= struct.unpack(longlongformat, buffer)  
            hash += l_value 
            hash = hash & 0xFFFFFFFFFFFFFFFF #to remain as 64bit number  @ReservedAssignment
                 
        
        f.seek(max(0,filesize-65536)) 
        for _x in range(65536/bytesize): 
            buffer = f.read(bytesize)  # @ReservedAssignment
            (l_value,)= struct.unpack(longlongformat, buffer)  
            hash += l_value 
            hash = hash & 0xFFFFFFFFFFFFFFFF  # @ReservedAssignment         
        returnedhash =  "%016x" % hash 
        return returnedhash 
    
    def choose(self, data):
        null=f = open(os.devnull,"w")
        items=[]
        for l in data:
            items.append(l['SubDownloadLink'])
            items.append(l['SubFileName'])
            items.append(l['SubDownloadsCnt'])
        
        p=subprocess.Popen('zenity --list --title "Select subtitles" --text "Select best matching subtitles" --width 1024 --height 600 --column Link --column Name --column Downloads --hide-column=1', 
                 stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=null, shell=True)  
        res,_=p.communicate(u'\n'.join(items).encode('utf-8'))
        null.close()
        return res if res.startswith('http') else None
    
    def download(self, filename, filesize=None, filehash=None, can_choose=True):
        data=self.search(filename, filesize, filehash)
        if not data:
            return None
        media_file=OpenSubtitles._base_name(filename).lower()
        def same_name(b):
            return media_file==OpenSubtitles._base_name(b['SubFileName']).lower()
        if filehash and filesize:
            match=filter(lambda x: x.get('QueryNumber', 0)==0,data)
            logger.debug('Got results by filehash')
        else:
            match=filter(same_name,data)
        if match:
            sub=match[0]
            link=sub['SubDownloadLink']
            ext=sub['SubFormat']
            logger.debug('Find exact match for media file, subtitle is %s', sub['SubFileName'])
        elif can_choose:
            link=self.choose(data)
            ext='srt'
        else:
            sub=data[0]
            link=sub['SubDownloadLink']
            ext=sub['SubFormat']
        if link:
            return self.download_link(filename, link, ext)
    
    def download_link(self, filename, link, ext):
        out_file=OpenSubtitles._sub_file(filename, ext)
        res=urllib2.urlopen(link, timeout=10)
        data=StringIO(res.read())
        data.seek(0)
        res.close()
        z=gzip.GzipFile( fileobj=data)
        with open(out_file,'wb') as f:
            while True:
                d=z.read(1024)
                if not d:
                    break
                f.write(d)
        z.close()
        return out_file
    
    @staticmethod
    def has_subtitles_downloaded(filename, ext='srt'):
        sfile=OpenSubtitles._sub_file(filename, ext)
        if os.path.exists(sfile) and os.stat(sfile).st_size>0:
                return True
        return False
    
    def logout(self):
        res = self._proxy.LogOut(self._token)
        self._parse_status(res)
    
    def __enter__(self):
        self.login()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logout()
 
def down(f, lang, overwrite=False):
    if OpenSubtitles.has_subtitles_downloaded(f) and not overwrite:
        print 'subs are already there'
    else:
        with OpenSubtitles(lang) as opensub:
            filesize,filehash=calc_hash(f)
            res=  opensub.download(f,filesize,filehash)
            if res:
                print 'subtitles %s downloaded' % res
            else:
                print 'no subs found'
def calc_hash(f):  
    if not os.access(f, os.R_OK):
        raise ValueError('Cannot read from file %s' % f)
    filesize=os.stat(f).st_size
    with open(f,'rb') as fs:
        filehash=OpenSubtitles.hash_file(fs, filesize)
    return filesize,filehash  
         
def list_subs(f, lang):  
    import pprint
    filesize,filehash=calc_hash(f)
    with OpenSubtitles(lang) as opensub:
        res=opensub.search(f, filesize, filehash)
        res=map(lambda x: {'SubFileName':x['SubFileName'], 
                           'SubDownloadsCnt':x['SubDownloadsCnt'],
                           'QueryNumber':x.get('QueryNumber', 0),
                           },
                res)
        pprint.pprint(res)
         
if __name__=='__main__':
    
    from argparse import ArgumentParser
    p=ArgumentParser()
    p.add_argument("video_file", help="video file")
    p.add_argument("-d", "--download", action="store_true", help="Download subtitles for video files")
    p.add_argument("-l", "--list", action="store_true", help="List available subtitles")
    p.add_argument("--lang", default='eng', help="Language")
    p.add_argument("--debug", action="store_true", help="Print debug messages")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing subtitles ")
    args=p.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    if args.download:
        down(args.video_file, args.lang, args.overwrite)
    else:
        list_subs(args.video_file, args.lang)
    
