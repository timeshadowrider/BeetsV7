#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

# Stopwords filtered out before matching.
# Keep this list small -- only truly meaningless filler words.
# Short words like "or", "at", "by" can be meaningful in artist/album names.
STOPWORDS = {
    "a", "an", "the", "and", "with", "from", "this", "that",
}

# Pure numeric tokens (track numbers, years used as folder prefixes, etc.)
# should never match against artist/album folder names. A folder called
# "Alabama-40.Hour.Week" contains "40" as a word token; a transfer path
# "04 Don't Look Back in Anger.flac" contains "04". These should NOT match.
# We filter out any token that is purely digits or zero-padded digits.
def _is_numeric(token: str) -> bool:
    return token.isdigit()


def tokenize(text: str):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [
        t for t in text.split()
        if t
        and t not in STOPWORDS
        and not _is_numeric(t)   # FIX: drop pure numeric tokens (track numbers, years)
    ]
    return tokens


def fuzzy_match(path_tokens, folder_tokens):
    """
    Returns True if ANY token from path_tokens appears in folder_tokens.

    FIX: Numeric-only tokens are now stripped in tokenize() so track numbers
    like "03", "04", "10" in SLSKD transfer paths can no longer cause false
    positive matches against inbox folder names that happen to contain the
    same digits (e.g. "Alabama-40.Hour.Week", "10 Great Songs", "04 - Holy...").

    This was causing almost every inbox folder to be incorrectly flagged as
    matching the active Oasis download and skipped by the pipeline.
    """
    if not path_tokens or not folder_tokens:
        return False
    for t in path_tokens:
        if t in folder_tokens:
            return True
    return False