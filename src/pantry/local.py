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

from mealtime_nutrients import CORE_NUTRIENTS
from rapidfuzz import fuzz, process

from pantry.ids import id_sort_key
from pantry.products import (
    BASIS_GRAMS,
    NUTRIENT_KEYS,
    Product,
)

# How much a source's answer is worth, best first. Deliberately not
# `PRODUCT_SOURCES`, which is a storage order: reusing it made every branded
# retail row outrank the composition database on an equal name match.
SOURCE_TRUST = (
    "manual",
    "afcd",
    "usda",
    "openfoodfacts",
    "coles",
    "woolworths",
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

# A head word the query never mentioned names a different food, so it must
# cost more than the +50 naming the food is worth: `Lemon peel` is not lemon.
_HEAD_MISS = 60

# Qualifiers naming a different food rather than a more precise one. A query
# that asks for one lifts its penalty, so `fried rice` and `dried oregano`
# still find what they asked for; a query that does not gets the plain food.
_VARIANTS = frozenset(
    (
        "fried", "baked", "boiled", "grilled", "roasted", "toasted",
        "poached", "scrambled", "casseroled", "microwaved", "steamed",
        "canned", "condensed", "evaporated", "dried", "sundried", "smoked",
        "pickled", "preserved", "sweetened", "salted", "cured",
        "free", "reduced", "low", "skim", "lite", "decaffeinated",
    )
)

# Enough to sink a variant behind its plain sibling without letting a pile of
# them outweigh naming the food itself.
_VARIANT_COST = 30

_SPLIT = re.compile(r"[^0-9a-z]+")


def _fold(text: str) -> str:
    """Lowercase and strip diacritics, so "yoğurt" matches "yogurt"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return [word for word in _SPLIT.split(_fold(text)) if len(word) > 1]


def _matches(words: list[str], token: str) -> bool:
    """Whether any of `words` is the same word as `token`, near enough."""
    return any(fuzz.ratio(word, token) >= _WORD_CUTOFF for word in words)


def split_name(name: str) -> tuple[list[str], list[str]]:
    """A name as the food it is, plus the words narrowing it down.

    Two conventions have to read the same. AFCD writes `Oil, olive`: the food
    comes first and every later comma segment narrows it. Retail writes
    `Olive Oil Rusk`: the food comes last and everything before it narrows it.
    Reading both as "the first word is the most specific" is what made a
    biscuit the best answer for olive oil.
    """
    segments = [w for w in (_words(part) for part in name.split(",")) if w]
    if not segments:
        return [], []
    if len(segments) > 1:
        return segments[0], [word for s in segments[1:] for word in s]
    return segments[0][-1:], segments[0][:-1]


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
        self._split: dict[int, tuple[list[str], list[str]]] = {}

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
        return [as_result(product) for product in self.ranked(query, limit)]

    def ranked(self, query: str, limit: int = 10) -> list[Product]:
        """The matching records themselves, best first, in their own shape.

        Split from `search` so a caller holding rows that are not products —
        a retailer catalogue, which carries prices and no nutrition — gets the
        same matching without a second copy of it. Only `name` and `brand` are
        read here, which both shapes have.
        """
        index = self._build()
        tokens = list(dict.fromkeys(_words(query)))
        if not tokens:
            return []

        totals: dict[int, float] = defaultdict(float)
        matched: dict[int, set[str]] = defaultdict(set)
        for token in tokens:
            # Only a product's best word counts; repetition must not inflate.
            best: dict[int, int] = {}
            best_words: dict[int, str] = {}
            for word, score in self._word_scores(token).items():
                for position in index[word]:
                    # Every close word is accounted for, not just the best:
                    # `Cumin (cummin) seed` spells the same word twice and
                    # neither spelling is an unasked-for one.
                    matched[position].add(word)
                    if score > best.get(position, 0):
                        best[position] = score
                        best_words[position] = word

            for position, score in best.items():
                head, qualifiers = self._parts(position)
                matched_word = best_words[position]

                # Naming the food outscores merely qualifying it. An exact
                # whole-name match is deliberately no better than a tie, so
                # `Chicken Breast` and `Chicken, breast, lean flesh, raw`
                # part on source trust rather than on brevity.
                word_score = score
                if _matches(head, matched_word):
                    word_score += 50
                elif _matches(qualifiers, matched_word):
                    word_score += 20

                totals[position] += word_score

        leftover: dict[int, int] = {}
        for position, seen in matched.items():
            head, qualifiers = self._parts(position)
            spare = [word for word in qualifiers if word not in seen]
            totals[position] -= _HEAD_MISS * sum(w not in seen for w in head)
            totals[position] -= _VARIANT_COST * sum(
                word in _VARIANTS for word in spare
            )
            leftover[position] = len(spare)

        ranked = sorted(
            totals, key=lambda p: self._rank(p, totals[p], leftover[p])
        )
        return [self._products[p] for p in ranked[:limit]]

    def _rank(self, position: int, total: float, leftover: int = 0):
        """Score first, then a stable tie-break so output is reproducible.

        Trust outranks `leftover` deliberately: a bare retail name carries no
        spare words at all, and letting that beat `Chicken, breast, lean
        flesh, raw` is the whole reason this ordering exists.
        """
        product = self._products[position]
        source = product.get("source")
        trust = (
            SOURCE_TRUST.index(source)
            if source in SOURCE_TRUST
            else len(SOURCE_TRUST)
        )
        return (
            -total,
            trust,
            leftover,
            id_sort_key(str(product.get("id"))),
        )

    def _parts(self, position: int) -> tuple[list[str], list[str]]:
        """Cached: a name is split once per query, not once per query word."""
        if position not in self._split:
            name = self._products[position].get("name", "")
            self._split[position] = split_name(name)
        return self._split[position]

    def find(self, source: str, product_id: str) -> Product | None:
        """Exact composite-identity lookup: no fuzz, no network."""
        wanted = (source, product_id)
        for product in self._products:
            if (product.get("source"), product.get("id")) == wanted:
                return product
        return None
