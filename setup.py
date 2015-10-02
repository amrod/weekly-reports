__author__ = 'amrodriguez'
from distutils.core import setup
import py2exe

options = {'py2exe': {'includes': ['redmine.resources'], 'bundle_files': 1, 'compressed': False}}

setup(console=['weekly.py'], options=options, zipfile=None)
