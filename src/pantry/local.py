"""Local fuzzy search over product records. No network, ever.

This is the check that stands between a user and a wasted page load, so it is
deliberately generous about spelling and deliberately strict about relevance:
a query's score is the sum of the best match found for each of its words, so a
product matching every word outranks one matching a single word well. The
reference implementation fuzzy-matched each word against the whole "name brand"
string, which let one strong accidental match beat a complete one.
"""

import re
import unicodedata
from collections import defaultdict

from rapidfuzz import fuzz, process

from pantry.ids import id_sort_key
from pantry.products import PRODUCT_SOURCES, Product

# Below this, a word pair is a coincidence rather than a spelling variant.
# "yogurt" against "yoghurt" scores 92, which is the case that sets the floor.
_WORD_CUTOFF = 80

# What a prefix is worth. Typing "choc" to find "chocolate" is a search
# affordance a symmetric ratio cannot express, but it must not outrank an
# exact word match.
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
    serving = {
        key: product[full]
        for key, full in (("size", "serving_size"), ("unit", "serving_unit"))
        if product.get(full) is not None
    }

    nutrients = {
        key: product.get(key) or 0
        for key in ("kcal", "protein", "fat", "carbs", "fiber", "sugar")
    }

    # Sodium is milligrams, and it is the one nutrient most records predate: a
    # defaulted 0 would read as a sodium-free product rather than an unknown
    # one, so it is carried only when the record holds it.
    if product.get("sodium") is not None:
        nutrients["sodium"] = product["sodium"]

    result = {
        "id": product.get("id"),
        "name": name,
        "title": f"{name} ({brand})" if brand else name,
        "nutrients": nutrients,
        "serving": serving,
    }
    # Beside the nutrients, for the same reason they are stored together: a
    # prepared-basis result that looks identical to an as-sold one is the bug.
    # Empty rather than absent, because a record read off a hand-edited shard
    # may carry a note that says nothing, and this shape is documented as
    # carrying these keys only when the record really does.
    for key in ("basis", "basis_note"):
        if product.get(key):
            result[key] = product[key]

    if product.get("url") is not None:
        result["url"] = product["url"]
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
            # One product may hold several words matching the same query word;
            # only its best counts, so repetition cannot inflate a score.
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

                # A query term matching the head of a product name scores
                # higher than one matching a modifier.
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
