'''
Created on Apr 2, 2015

@author: ivan
'''
import xmlrpclib
import urllib2
import sys
import os.path
import gzip
import StringIO
import logging

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
        
    def search(self, filename, filesize=None, limit=20):
        filename=os.path.split(filename)[1]
        name=os.path.splitext(filename)[0]
        s={'sublanguageid':self._lang, 'tag':filename }
        s2={'sublanguageid':self._lang, 'query':name }
        res =self._proxy.SearchSubtitles(self._token,[s,s2], {'limit':limit})
        self._parse_status(res)
        data=res.get('data')
        
        return  data if data else []
    
    @staticmethod    
    def _sub_file(filename, ext):
        path, fname=os.path.split(filename)
        fname=os.path.splitext(fname)[0]
        return os.path.join(path, fname+'.'+ext)
        
        
    def download(self, filename, filesize=None):
        data=self.search(filename, filesize)
        if not data:
            return None
        sub=data[0]
        link=sub['SubDownloadLink']
        ext=sub['SubFormat']
        out_file=OpenSubtitles._sub_file(filename, ext)
        res=urllib2.urlopen(link, timeout=10)
        data=StringIO.StringIO(res.read())
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
 
def down(query, lang):
    if OpenSubtitles.has_subtitles_downloaded(query):
        print 'subs are already there'
    else:
        with OpenSubtitles(lang) as opensub:
            res=  opensub.download(query)
            if res:
                print 'subtitles downloaded'
            else:
                print 'no subs found'
         
def list_subs(f, lang):  
    import pprint
    with OpenSubtitles(lang) as opensub:
        res=opensub.search(f)
        res=map(lambda x: {'SubFileName':x['SubFileName'], 
                           'SubDownloadsCnt':x['SubDownloadsCnt'],
                           'QueryNumber':x['QueryNumber']},
                res)
        pprint.pprint(res)
         
if __name__=='__main__':
    
    from argparse import ArgumentParser
    p=ArgumentParser()
    p.add_argument("video_file", help="video file")
    p.add_argument("-d", "--download", action="store_true", help="Download subtitles for video files")
    p.add_argument("-l", "--list", action="store_true", help="List available subtitles")
    p.add_argument("--lang", default='eng', help="Language")
    args=p.parse_args()
    if args.download:
        down(args.video_file, args.lang)
    else:
        list_subs(args.video_file, args.lang)
    
