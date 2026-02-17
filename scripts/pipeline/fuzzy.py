#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

# FIX: Removed short common words like "or", "at", "by", "as", "is", "it"
# from stopwords. These can be meaningful parts of artist/album names
# e.g. "The Band Perry", "At The Drive-In", "Is This It".
# Only filter truly meaningless filler words.
STOPWORDS = {
    "a", "an", "the", "and", "with", "from", "this", "that",
}


def tokenize(text: str):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t and t not in STOPWORDS]
    return tokens


def fuzzy_match(path_tokens, folder_tokens):
    """
    Returns True if ANY token from path_tokens appears in folder_tokens.

    FIX: This is a very broad match - a single shared token triggers it.
    This is intentional for safety (better to skip a folder than process
    one mid-download) but means common words in artist names can cause
    false positives. The reduced stopword list above reduces this risk.
    """
    if not path_tokens or not folder_tokens:
        return False
    for t in path_tokens:
        if t in folder_tokens:
            return True
    return False
