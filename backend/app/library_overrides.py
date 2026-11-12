"""Allow recipients to replace separately licensed libraries before app imports.

Only an explicit process-owner environment setting is used. Project inputs and
HTTP parameters cannot enable this mechanism or override MINA application code.
"""
from __future__ import annotations
import importlib.abc
import importlib.machinery
import os
import sys
from pathlib import Path

REPLACEABLE={'paramiko','ldap3','psycopg','psycopg_binary','certifi','saxonche'}


def activate():
    configured=os.environ.get('MINA_LIBRARY_PATH','')
    if not configured:return
    roots=[]
    for value in configured.split(os.pathsep):
        path=Path(value)
        if not value or not path.is_absolute() or not path.is_dir():
            raise ValueError('MINA_LIBRARY_PATH entries must be existing absolute directories')
        roots.append(str(path.resolve()))
    class LibraryFinder(importlib.abc.MetaPathFinder):
        _mina_library_override=True
        def find_spec(self,fullname,path=None,target=None):
            if path is not None or fullname not in REPLACEABLE:return None
            return importlib.machinery.PathFinder.find_spec(fullname,roots)
    sys.meta_path[:]=[finder for finder in sys.meta_path if not getattr(finder,'_mina_library_override',False)]
    sys.meta_path.insert(0,LibraryFinder())


def diagnostic():
    import importlib.util,json
    print(json.dumps({name:(spec.origin if (spec:=importlib.util.find_spec(name)) else None)
                      for name in sorted(REPLACEABLE)},indent=2))
