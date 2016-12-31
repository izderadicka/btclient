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
import logging

logger = logging.getLogger('ulozto-plugin')

class ResolveSoftError(Exception):
    pass

class UlozTo(Resolver):
    URL_PATTERN=r'https://(?:www\.)?(uloz\.to|ulozto\.(cz|sk|net)|bagruj.cz|zachowajto.pl)/(?:live/)?(?P<id>[!\w]+/[^/?]*)'
    SPEED_LIMIT=300
    THREADS=4
    
    def resolve(self, url):
        retries = 3
        while True:
            try:
                return self._resolve(url)
            except ResolveSoftError,e:
                if retries>0:
                    logger.debug('Got error that could be retried: %s', e)
                    retries-=1
                else:
                    raise
        
        
    def _resolve(self, url):
        s=urlparse.urlsplit(url)
        base_url=urlparse.urlunsplit((s.scheme,s.netloc,'','',''))
        pg=self._client.load_page(url)
        form=pg.find('form', {'id':'frm-download-freeDownloadTab-freeDownloadForm'})
        if not form:
            recaptcha = pg.find('form', {'id':'frm-captchaComponent-accessForm'})
            if recaptcha:
                raise PluginError('Need recaptcha - cannot resolve it now')
            else:
                raise PluginError('Cannot find download form - page changed?')
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
        
        xapca = self._client.load_json("https://www.ulozto.net/reloadXapca.php", {"rnd": str(int(time.time()))}, method='get')
        sound_url=xapca.get('sound') 
        if not sound_url:
            raise PluginError('No sound captcha')
        if not re.match('^https?:', sound_url):
            sound_url='https:'+sound_url
        sound_ext=os.path.splitext(urlparse.urlsplit(sound_url).path)[1]
        try:
            audio=self._client.open(sound_url, method='get')
        except self._client.Error,e:
            logger.exception('Cannot get audio captcha')
            raise ResolveSoftError('Cannot load audio captcha')
        cfg_file=os.path.join(os.path.split(clslib.__file__)[0], 'ulozto.cfg')
        captcha= clslib.classify_audio_file(audio, cfg_file, ext=sound_ext)
        if not captcha and len(captcha)!=4:
            raise PluginError('Invalid decoded captcha')
        
        data.update({'timestamp': xapca['timestamp'], 'salt': xapca['salt'], 'hash': xapca['hash'], 'captcha_value': captcha})
        
        res=self._client.open(urlparse.urljoin(base_url, action),data, method='post')  
        type_header=res.info().getheader('Content-Type')
        
        if not type_header.startswith('video') and not type_header.startswith('application/octet-stream'):
            raise ResolveSoftError('Not resolved to a video link - mime %s' % type_header)
        file_url=res.geturl()
        res.close()
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
        