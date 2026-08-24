"""Local fuzzy search over product records. No network, ever.

This stands between a user and a wasted page load, so it is generous about
spelling and strict about relevance: a query scores the sum of the best match
for each word, so a product matching every word outranks one matching a single
word well. Matching against the whole "name brand" string, as the reference
implementation did, let one accident beat a complete match.
"""

import re
import unicodedata
from collections import defaultdict

from rapidfuzz import fuzz, process

from mealtime_nutrients import CORE_NUTRIENTS

from pantry.ids import id_sort_key
from pantry.products import (
    BASIS_GRAMS,
    NUTRIENT_KEYS,
    PRODUCT_SOURCES,
    Product,
)


def result_with_nulls(result: dict) -> dict:
    """Complete a provider search result without inventing measurements.

    Only the four that are always present: an absent nutrient and a null one
    say the same thing, so spelling out the rest of the vocabulary would be
    tens of keys per row carrying no answer.
    """
    shown = dict(result)
    for key in CORE_NUTRIENTS:
        shown[key] = shown.get(key)
    return shown


# Below this a word pair is coincidence; "yoghurt" scores 92 on "yogurt".
_WORD_CUTOFF = 80

# What a prefix is worth: "choc" finds "chocolate", never beating an exact.
_PREFIX_SCORE = 90
_MIN_PREFIX = 3

_SPLIT = re.compile(r"[^0-9a-z]+")


def _fold(text: str) -> str:
    """Lowercase and strip diacritics, so "yoğurt" matches "yogurt"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return [word for word in _SPLIT.split(_fold(text)) if len(word) > 1]


def as_result(product: Product) -> dict:
    """The search-result shape agents consume. Absent fields stay absent."""
    name = product.get("name", "")
    brand = product.get("brand", "")
    # Missing stays missing; only an explicit source value may become zero.
    result = {
        "id": product.get("id"),
        "name": name,
        "title": f"{name} ({brand})" if brand else name,
        **{
            key: product.get(key)
            for key in NUTRIENT_KEYS
            if key in CORE_NUTRIENTS or product.get(key) is not None
        },
    }
    # Carried when stated: a prepared result reading as as-sold is the bug.
    for key in ("basis", "basis_note"):
        if product.get(key):
            result[key] = product[key]

    if product.get("url") is not None:
        result["url"] = product["url"]

    # Never absent, so a consumer never has to infer the basis.
    result["grams"] = product.get("grams") or BASIS_GRAMS
    result["source"] = product.get("source")

    return result


class Local:
    """A searchable view over a list of products, indexed once on demand."""

    def __init__(self, products: list[Product]) -> None:
        self._products = products
        self._index: dict[str, list[int]] | None = None
        self._vocabulary: list[str] = []

    def _build(self) -> dict[str, list[int]]:
        """Map each distinct word to the products carrying it.

        Built here because this is the common ingress for the frozen shards, a
        file on disk and a user's localstore alike.
        """
        if self._index is not None:
            return self._index

        index: dict[str, list[int]] = defaultdict(list)
        for position, product in enumerate(self._products):
            text = f"{product.get('name', '')} {product.get('brand', '')}"
            for word in set(_words(text)):
                index[word].append(position)

        self._index = index
        self._vocabulary = list(index)
        return index

    def _word_scores(self, token: str) -> dict[str, int]:
        """Every vocabulary word close enough to one query word."""
        matches = process.extract(
            token,
            self._vocabulary,
            scorer=fuzz.ratio,
            score_cutoff=_WORD_CUTOFF,
            limit=None,
        )
        scores = {word: int(score) for word, score, _ in matches}

        if len(token) >= _MIN_PREFIX:
            for word in self._vocabulary:
                if word.startswith(token):
                    scores[word] = max(scores.get(word, 0), _PREFIX_SCORE)

        return scores

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Rank products by summed per-word match, best first."""
        index = self._build()
        tokens = list(dict.fromkeys(_words(query)))
        if not tokens:
            return []

        totals: dict[int, float] = defaultdict(float)
        for token in tokens:
            # Only a product's best word counts; repetition must not inflate.
            best: dict[int, int] = {}
            best_words: dict[int, str] = {}
            for word, score in self._word_scores(token).items():
                for position in index[word]:
                    if score > best.get(position, 0):
                        best[position] = score
                        best_words[position] = word

            for position, score in best.items():
                product = self._products[position]
                name = product.get("name", "")
                head_segment = name.split(",")[0]
                head_words = _words(head_segment)
                matched_word = best_words[position]

                # A head-of-name match outscores one against a modifier.
                word_score = score
                if head_words:
                    if fuzz.ratio(head_words[0], matched_word) >= _WORD_CUTOFF:
                        word_score += 50
                        if (
                            len(head_words) == 1
                            and len(tokens) == 1
                            and score >= 100
                        ):
                            word_score += 25
                        elif len(head_words) == len(tokens) and score >= 100:
                            word_score += 20
                    elif any(
                        fuzz.ratio(hw, matched_word) >= _WORD_CUTOFF
                        for hw in head_words[: len(tokens)]
                    ):
                        word_score += 20

                totals[position] += word_score

        ranked = sorted(totals, key=lambda p: self._rank(p, totals[p]))
        return [as_result(self._products[p]) for p in ranked[:limit]]

    def _rank(self, position: int, total: float):
        """Score first, then a stable tie-break so output is reproducible."""
        product = self._products[position]
        source = product.get("source")
        order = (
            PRODUCT_SOURCES.index(source)
            if source in PRODUCT_SOURCES
            else len(PRODUCT_SOURCES)
        )
        return (-total, order, id_sort_key(str(product.get("id"))))

    def find(self, source: str, product_id: str) -> Product | None:
        """Exact composite-identity lookup: no fuzz, no network."""
        wanted = (source, product_id)
        for product in self._products:
            if (product.get("source"), product.get("id")) == wanted:
                return product
        return None
