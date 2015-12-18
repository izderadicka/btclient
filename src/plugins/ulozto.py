'''
Created on May 6, 2015

@author: ivan
'''

from common import Resolver
from plugins import PluginError
import urlparse
import time
import os.path
import adecaptcha.clslib as clslib
import re
from StringIO import StringIO
urlparse

class UlozTo(Resolver):
    URL_PATTERN=r'http://(?:www\.)?(uloz\.to|ulozto\.(cz|sk|net)|bagruj.cz|zachowajto.pl)/(?:live/)?(?P<id>\w+/[^/?]*)'
    SPEED_LIMIT=300
    THREADS=4
    def resolve(self, url):
        s=urlparse.urlsplit(url)
        base_url=urlparse.urlunsplit((s.scheme,s.netloc,'','',''))
        pg=self.client.load_page(url)
        form=pg.find('form', {'id':'frm-downloadDialog-freeDownloadForm'})
        action=form.attrs.get('action')
        if not action:
            raise PluginError('Form has no action')
        if not form:
            raise PluginError()
        inputs=form.find_all('input')
        data={}
        for input in inputs:
            if input.attrs.has_key('name'):
                data[input['name']]=input['value'].encode('utf8','ignore') if input.attrs.has_key('value') else None
                
        if not all([key in data for key in ('captcha_value', 'timestamp', 'salt', 'hash')]):
            raise PluginError('Required inputs are missing')
        
        xapca = self.client.load_json("http://www.ulozto.net/reloadXapca.php", {"rnd": str(int(time.time()))}, method='get')
        sound_url=xapca.get('sound') 
        if not re.match('^https?:', sound_url):
            sound_url='http:'+sound_url
        sound_ext=os.path.splitext(urlparse.urlsplit(sound_url).path)[1]
        if not sound_url:
            raise PluginError('No sound captcha')
        audio=self.client.open(sound_url, method='get')
        cfg_file=os.path.join(os.path.split(clslib.__file__)[0], 'ulozto.cfg')
        captcha= clslib.classify_audio_file(StringIO(audio.content), cfg_file, ext=sound_ext)
        if not captcha and len(captcha)!=4:
            raise PluginError('Invalid decoded captcha')
        
        data.update({'timestamp': xapca['timestamp'], 'salt': xapca['salt'], 'hash': xapca['hash'], 'captcha_value': captcha})
        
        res=self.client.open(urlparse.urljoin(base_url, action),data, method='post', redirect=False)  
        if not res.status_code == 303:
            raise PluginError('Url nor resolved (no redirect)')
        file_url=res.headers['location']
        res=self.client.open(file_url, method='get', redirect=False, stream=True)  
        res.close()
        if res.status_code>=400:
            raise PluginError('Got HTTP %d error on url %s'% (res.status_code, file_url))
        if res.status_code>=300:
            file_url=res.headers['location']
        return file_url
    
    @staticmethod
    def url_to_file(uri):
        path=urlparse.urlsplit(uri)[2]
        if path.startswith('/'):
            path=path[1:]
        path_parts=path.split(os.sep)
        name_parts=path_parts[-1].split('-')
        dname='-'.join(name_parts[:-1])
        fname=dname+'.'+name_parts[-1]
        if len(path_parts)>1:
            dname+='(%s)'%path_parts[-2]
        return os.path.join(dname, fname)
        