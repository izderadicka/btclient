import os,importlib,re
from inspect import isclass
from common import Resolver
import sys

class PluginError(Exception):
    pass

def load_plugins():
    plugs=[]
    path=os.path.split(__file__)[0]
    for fname in os.listdir(path):
        mod,ext=os.path.splitext(fname)
        fname=os.path.join(path,fname)
        if os.path.isfile(fname) and ext=='.py' and not mod.startswith('_'):
            try:
                m=importlib.import_module('plugins.'+mod)
            except Exception,e:
                print >>sys.stderr, "Cannot load plugin %s, error:%s"%(mod,e)
                continue
            plug=None
            for c in dir(m):
                cls=getattr(m, c);
                if not c.startswith('_') and isclass(cls) and issubclass(cls, Resolver) \
                    and Resolver != cls:
                    plug = cls
            
            if plug:
                plugs.append(plug)
                    
    return plugs 

plugs= load_plugins() 

def find_matching_plugin(url):   
    for p in plugs:
        if re.match(p.URL_PATTERN,url) :
            return p      