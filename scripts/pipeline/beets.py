#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from .util import run, PRELIB, LIBRARY
from .logging import vlog


def run_fingerprint():
    vlog("[FP] Running fingerprint pass...")
    run(["python3", "/app/scripts/fingerprint_all.py"])


def run_beets_import():
    vlog("[BEETS] Importing pre-library...")
    run(["beet", "import", "-q", str(PRELIB)])


def run_post_import():
    vlog("[BEETS] Post-import update/move...")
    run(["beet", "update", "path:/pre-library"])
    run(["beet", "move", "-d", str(LIBRARY), "path:/pre-library"])
    run(["beet", "update", "path:%s" % LIBRARY])
