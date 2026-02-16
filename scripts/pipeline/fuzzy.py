#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "to", "for", "and", "or",
    "at", "by", "with", "from", "as", "is", "it", "this", "that"
}


def tokenize(text: str):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t and t not in STOPWORDS]
    return tokens


def fuzzy_match(path_tokens, folder_tokens):
    for t in path_tokens:
        if t in folder_tokens:
            return True
    return False
