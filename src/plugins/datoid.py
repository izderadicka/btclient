'''
Created on May 6, 2015

@author: ivan
'''

from common import Resolver, rand_multiplier
from plugins import PluginError
import urlparse
import time
import os.path
import re
import logging
from io import BytesIO
from time import sleep

logger = logging.getLogger('datoid-plugin')

ACCOUNTS = []
with open(os.path.join(os.path.dirname(__file__), "datoid.accounts"), "r") as f:
    for line in f:
        u,p = line.strip().split(':')
        ACCOUNTS.append((u,p))

class ResolveSoftError(Exception):
    pass

class Datoid(Resolver):
    URL_PATTERN=r'https://(?:www\.)?(datoid\.(cz|sk|net))(?P<path>/.*)'
    SPEED_LIMIT=300
    THREADS=2
    _INSTANCE_NO = 0

    def __init__(self, loader):
        super(Datoid,self).__init__(loader)
        user,password = ACCOUNTS.pop()
        self.user = user
        self.password = password

    def __del__(self):
        ACCOUNTS.append((self.user, self.password))

    
    def resolve(self, url):
        retries = 5
        while True:
            try:
                return self._resolve(url)
            except ResolveSoftError,e:
                if retries>0:
                    logger.debug('Got error that could be retried: %s', e)
                    sleep(rand_multiplier(2) * (6-retries))
                    retries-=1
                else:
                    raise
        
        
    def _resolve(self, url):
        s=urlparse.urlsplit(url)
        base_url=urlparse.urlunsplit((s.scheme,s.netloc,'','',''))
        html = self._client.load_page(base_url)

        token =  html.find('input', {'name': '_token_'}).get('value')
        if not token:
            raise PluginError("Cannot find token input")
        
        
        
        page = self._client.load_page(base_url,
                        method="post",
                         data={'username': self.user,
                               'password': self.password,
                               "_do": "signInForm-submit", 
                               "_token_": token})

        file_url = base_url+'/f'+s.path+"?request=1&_=%d" % time.time()
        json = self._client.load_json(file_url)                      

        link =  json.get("download_link") or json.get("download_link_cdn")
        if not link:
            raise PluginError("Cannot get file link")
        return link
        
        
    
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


if __name__ == '__main__':
    from plugins import find_matching_plugin
    from htclient import HTTPLoader
    url = "https://datoid.cz/JfTBQm/hej-rup-1934-monty-698-avi"
    file_name = Datoid.url_to_file(url)
    resolver_class = find_matching_plugin(url)
    client = HTTPLoader(url,0,resolver_class)
    client2 = HTTPLoader(url,0,resolver_class)
    assert client.url and client2.url



        