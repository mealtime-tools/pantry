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
from decimal import Decimal

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
    "coles",
    "woolworths",
    # Last on purpose. The crowdsourced rows carry the right barcode but often
    # the wrong food for a plain word: "black beans" found `Sardines in black
    # beans`, "almonds" found `Crunchoco Almond`. A retailer at least sells
    # the thing its name says.
    "openfoodfacts",
)

# What kind of answer a source gives, coarse enough for a caller to branch on
# without hard-coding the six names.
SOURCE_TIERS = {
    "manual": "verified",
    "afcd": "composition",
    "usda": "composition",
    "openfoodfacts": "crowdsourced",
    "coles": "retail",
    "woolworths": "retail",
}


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

# What matching a word is worth beyond the word score itself: naming the food
# the record is, against merely narrowing one down.
_NAMES_FOOD = 50
_QUALIFIES = 20

# A head word the query never mentioned names a different food, so it must
# cost more than naming the food is worth: `Lemon peel` is not lemon.
_HEAD_MISS = 60

# Qualifiers naming a different food rather than a more precise one. Counted
# rather than scored, so a query that asks for one still finds it and a record
# is never sunk for stating a preparation the query simply did not mention.
#
# The last line names a part rather than a preparation: an egg white is its own
# food, and `eggs` must answer with the whole egg at 127 kcal, not the white at
# 47. Without it the two tie on leftover words and the id order decides.
_VARIANTS = frozenset(
    """
    fried baked boiled grilled roasted toasted poached scrambled casseroled
    microwaved steamed canned frozen condensed evaporated dried sundried smoked
    pickled preserved sweetened salted cured
    free reduced low skim lite decaffeinated
    white yolk
    """.split()
)

# Words meaning the figures describe the food after it absorbed water. This is
# not one qualifier among others: rice triples in weight when boiled, so a
# cooked panel read as a dry one understates protein and energy roughly
# threefold, and a recipe built on it is wrong by that much. Dry weight is
# always recoverable arithmetic; cooked weight is not, because the water taken
# up is not stated. So a cooked record never outranks an uncooked one — a
# separate rule from `_VARIANTS`, which only breaks ties.
#
# `dried` is deliberately absent: dried chickpeas are the dry weight wanted.
_COOKED = frozenset(
    """
    cooked boiled steamed microwaved simmered stewed braised poached
    reconstituted prepared rehydrated
    """.split()
)

# How far below its identically-named peers a panel may sit before it is
# treated as describing a different state of the food. Water is the only thing
# that dilutes a panel this much: five records named `Basmati Rice` agree at
# ~360 kcal and one says 107.6, which is boiled rice on a five-kilo bag of dry.
_OUTLIER_RATIO = Decimal("0.5")

# Below this many peers there is no consensus to be an outlier from.
_MIN_PEERS = 3


def dilute_outliers(
    candidates: list[tuple[int, str, Decimal | None]],
) -> set[int]:
    """Positions whose energy sits far below their identically-named peers.

    A retailer sometimes prints the cooked panel on a dry product, and the
    name gives no sign of it. What does give a sign is the other products
    called the same thing: they agree, and the mislabelled one does not.
    """
    groups: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
    for position, name, kcal in candidates:
        if kcal is not None:
            groups[name].append((position, Decimal(kcal)))

    outliers: set[int] = set()
    for members in groups.values():
        if len(members) < _MIN_PEERS:
            continue
        energies = sorted(k for _, k in members)
        median = energies[len(energies) // 2]
        if median <= 0:
            continue
        for position, kcal in members:
            if kcal < median * _OUTLIER_RATIO:
                outliers.add(position)

    return outliers


# What a record named exactly for the query scores: one word naming the food
# and the rest qualifying it. The denominator that turns a score into a
# confidence, so a caller can tell "the right record" from "the least wrong".
_PERFECT_HEAD = 100 + _NAMES_FOOD
_PERFECT_QUALIFIER = 100 + _QUALIFIES

# Below this the store answered with something, but not with what was asked
# for: a query word went unanswered, or the record names a food of its own.
WEAK_MATCH = Decimal("0.7")

_SPLIT = re.compile(r"[^0-9a-z]+")
_PARENTHETICAL = re.compile(r"\([^)]*\)")

# AFCD sometimes puts a broad taxonomy before the food itself.
_TAXONOMY_HEADS = frozenset({"melon", "nut"})


def _fold(text: str) -> str:
    """Lowercase and strip diacritics, so "yoğurt" matches "yogurt"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return [word for word in _SPLIT.split(_fold(text)) if len(word) > 1]


# Two names for one food, folded onto one spelling before matching so either
# finds either row. Almost all of it is where the user lives: a recipe written
# elsewhere asks for cilantro, arugula and bell pepper, and the shards call
# them coriander, rocket and capsicum.
#
# This is a closed set, not the beginning of a synonym project. Open-ended
# vocabulary is a shop's job and the shops already do it — Woolworths answers
# "shredded" with "grated" unaided — so nothing here tries to compete with
# that. It exists because the store has no relevance engine of its own.
#
# `pepper` is the risk in it: `red pepper` means capsicum, and black pepper is
# a different thing entirely, which the rest of the query is left to settle.
_SYNONYMS = {
    "shredded": "grated",
    "shred": "grated",
    "minced": "ground",
    "mince": "ground",
    "prawn": "shrimp",
    "capsicum": "pepper",
    "eggplant": "aubergine",
    "zucchini": "courgette",
    "coriander": "cilantro",
    "rocket": "arugula",
    "chickpea": "garbanzo",
}


def _stem(word: str) -> str:
    """A crude singular, then the one spelling a pair is matched under."""
    return _SYNONYMS.get(_singular(word), _singular(word))


def _singular(word: str) -> str:
    """A crude singular: enough to tell "eggs" and "egg" apart from nothing."""
    if word.endswith("ies") and len(word) > 3:
        return f"{word[:-3]}y"
    if word.endswith("oes") and len(word) > 3:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


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
    plain = _PARENTHETICAL.sub("", name)
    segments = [w for w in (_words(part) for part in plain.split(",")) if w]
    if not segments:
        return [], []
    if (
        len(segments) > 1
        and len(segments[0]) == 1
        and segments[0][0] in _TAXONOMY_HEADS
    ):
        return segments[1], [
            *segments[0],
            *[w for s in segments[2:] for w in s],
        ]
    if len(segments) > 1:
        return segments[0], [word for s in segments[1:] for word in s]
    return segments[0][-1:], segments[0][:-1]


def confidence(total: float, tokens: int) -> Decimal:
    """A score as a fraction of a perfect answer to every query word.

    Clamped: the penalties can take a score below zero, and "worse than
    nothing" is not a thing a caller can act on.
    """
    perfect = _PERFECT_HEAD + _PERFECT_QUALIFIER * max(tokens - 1, 0)
    bounded = max(0.0, min(1.0, total / perfect))
    return Decimal(bounded).quantize(Decimal("0.01"))


def as_result(product: Product, match: dict | None = None) -> dict:
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

    # The one field two sources can agree on. Carried so a consumer can join
    # a retailer's row to another database's panel without re-reading a page.
    if product.get("barcode"):
        result["barcode"] = product["barcode"]

    # Never absent, so a consumer never has to infer the basis.
    result["grams"] = product.get("grams") or BASIS_GRAMS
    result["source"] = product.get("source")

    # Not a stored field: how well this answered *this* query, which the
    # record itself cannot know. Same standing as `title` and `price`.
    if match is not None:
        result["match"] = match

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

        stem = _stem(token)
        for word in self._vocabulary:
            # A plural is the same word, not a near miss: on `fuzz.ratio`
            # alone "eggs" scored "egg" at 86 and lost to an Easter egg.
            if _stem(word) == stem:
                scores[word] = 100
            elif len(token) >= _MIN_PREFIX and word.startswith(token):
                scores[word] = max(scores.get(word, 0), _PREFIX_SCORE)

        return scores

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Rank products by summed per-word match, best first."""
        return [
            as_result(product, match)
            for product, match in self.scored(query, limit)
        ]

    def ranked(self, query: str, limit: int = 10) -> list[Product]:
        """The matching records themselves, best first, in their own shape.

        Split from `search` so a caller holding rows that are not products —
        a retailer catalogue, which carries prices and no nutrition — gets the
        same matching without a second copy of it. Only `name` and `brand` are
        read here, which both shapes have.
        """
        return [product for product, _ in self.scored(query, limit)]

    def scored(
        self, query: str, limit: int = 10
    ) -> list[tuple[Product, dict]]:
        """The matching records, each with how well it answered the query."""
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
                    word_score += _NAMES_FOOD
                elif _matches(qualifiers, matched_word):
                    word_score += _QUALIFIES

                totals[position] += word_score

        leftover: dict[int, int] = {}
        variants: dict[int, int] = {}
        cooked: dict[int, bool] = {}
        for position, seen in matched.items():
            head, qualifiers = self._parts(position)
            spare = [word for word in qualifiers if word not in seen]
            totals[position] -= _HEAD_MISS * sum(w not in seen for w in head)
            leftover[position] = len(spare)
            variants[position] = sum(word in _VARIANTS for word in spare)
            # Only when the query did not ask: "boiled egg" still finds one.
            cooked[position] = any(word in _COOKED for word in spare)

        # A panel far below its identically-named peers is the same harm as a
        # cooked one, arrived at without the name ever saying so.
        diluted = dilute_outliers(
            [
                (
                    position,
                    _fold(self._products[position].get("name", "")),
                    self._products[position].get("kcal"),
                )
                for position in totals
            ]
        )
        for position in diluted:
            cooked[position] = True

        ranked = sorted(
            totals,
            key=lambda p: self._rank(
                p, totals[p], cooked[p], variants[p], leftover[p]
            ),
        )
        return [
            (
                self._products[p],
                {
                    "score": confidence(totals[p], len(tokens)),
                    "tier": SOURCE_TIERS.get(
                        self._products[p].get("source"), "unknown"
                    ),
                },
            )
            for p in ranked[:limit]
        ]

    def _rank(
        self,
        position: int,
        total: float,
        cooked: bool = False,
        variants: int = 0,
        leftover: int = 0,
    ):
        """Cooked last, then score, then a stable tie-break.

        `cooked` outranks the score itself, which nothing else here does. A
        cooked panel silently read as a dry one is off by however much water
        the food took up — threefold for rice — and that has spoiled real
        recipes. A worse-matching dry record is still the better answer.

        Trust then outranks both counts deliberately. A bare retail name
        carries no spare words at all, and letting that beat `Chicken, breast,
        lean flesh, raw` is the whole reason this ordering exists; and ground
        cinnamon is inherently dried, so saying so must not lose it a donut.
        """
        product = self._products[position]
        source = product.get("source")
        trust = (
            SOURCE_TRUST.index(source)
            if source in SOURCE_TRUST
            else len(SOURCE_TRUST)
        )
        return (
            cooked,
            -total,
            trust,
            variants,
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
