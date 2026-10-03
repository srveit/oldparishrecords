#!/usr/bin/env python3
"""Backward-compatible entry. Login and dashboard files are one process.

site/dashboard/server.py listens on 127.0.0.1:8080.
"""
import os, runpy, sys
target = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'server.py'))
sys.argv[0] = target
runpy.run_path(target, run_name='__main__')
