"""User text -> search terms. Pure, no I/O (PLAN §7.1).

Tokenizing on \\w+ drops every FTS5 operator character (" * : ^ ( ) - +) before anything
reaches MATCH, and it splits text the same way the unicode61 tokenizer splits documents.
"""

import re
import unicodedata

# Hand-picked on purpose. Generic lists (NLTK etc.) drop words like "down", "out", "off", "up",
# which matter a lot in incident text.
STOPWORDS = frozenset(
    """
    a an and any anyone are as at be been before but by can could did do does for from had has have
    hello help hi how i if in into is it its me my of on or our please seen should so some than thanks
    that the their them then there these they this to us was we were what when where which who why
    will with would you your
    """.split()
)
_TOKEN = re.compile(r"\w+")


def extract(text: str, max_terms: int) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    terms: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(normalized):
        if len(token) < 2 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) == max_terms:
            break
    return terms
