"""English typing intervals, adapted from human-keyboard and human-typer.

See the README Credits for the upstream projects.
The model only calculates delays; the app owns text output and cancellation.
"""

import random
import re


INTERVAL_DEFAULTS = {
    'min_speed': 50,
    'max_speed': 150,
    'separator_min_delay': 200,
    'separator_max_delay': 500,
}
DEFAULT_INPUT_SPEED = 50


def normalize_input_speed(value):
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_INPUT_SPEED


def speed_profile(value):
    """Map 0–100 to coherent interval ranges; 50 preserves the original defaults."""
    speed = normalize_input_speed(value)
    factor = 3 ** ((50 - speed) / 50)
    return {'input_speed': speed, **{key: round(delay * factor)
            for key, delay in INTERVAL_DEFAULTS.items()}}


MODEL_DEFAULTS = {
    'model_tempo': True,
    'model_bigrams': True,
    'model_key_distance': True,
    'model_shift_digits': True,
    'model_smart_pauses': True,
    'model_english_tokens': True,
}
COMMON_BIGRAMS = frozenset('th he in er an re on at en nd ti es or te of'.split())
KEY_POSITIONS = {
    char: complex(column + offset, row)
    for row, (keys, offset) in enumerate((
        ('`1234567890-=', 0),
        ('qwertyuiop[]\\', 1.5),
        ("asdfghjkl;'", 1.75),
        ('zxcvbnm,./', 2.25),
    ))
    for column, char in enumerate(keys)
}
SHIFT_KEYS = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./"))
CLOSING_MARKS = frozenset('\'"\u2019\u201d)]}')
ABBREVIATION = re.compile(r'\b(?:mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|e\.g|i\.e)\.', re.I)
INITIAL = re.compile(r'\b[A-Z]\.(?=\s+[A-Z][a-z])')
ADDRESS = re.compile(
    r'(?:https?://|www\.)[^\s<>"\u201c\u201d]+'
    r'|[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}', re.I
)


def key_position(char):
    return KEY_POSITIONS.get(SHIFT_KEYS.get(char, char.lower()))


def uses_shift(char):
    return 'A' <= char <= 'Z' or char in SHIFT_KEYS


def _delay_setting(settings, key, default):
    try:
        return max(0, int(settings.get(key, default)))
    except (TypeError, ValueError):
        return default


class TypingRhythm:
    """Return the delay in seconds between text[index] and text[index + 1]."""

    def __init__(self, text, settings, rng=None):
        self.text = text
        self.rng = rng if rng is not None else random.Random()
        # Higher speeds model greater fluency as well as shorter intervals.
        self.fluency = (normalize_input_speed(settings.get('input_speed', DEFAULT_INPUT_SPEED)) - 50) / 50
        self.context_cost = 1 - 0.25 * self.fluency
        self.minimum, self.maximum = sorted((
            _delay_setting(settings, 'min_speed', 50),
            _delay_setting(settings, 'max_speed', 150),
        ))
        self.separator_minimum, self.separator_maximum = sorted((
            _delay_setting(settings, 'separator_min_delay', 200),
            _delay_setting(settings, 'separator_max_delay', 500),
        ))
        self.features = {key: bool(settings.get(key, default)) for key, default in MODEL_DEFAULTS.items()}
        self.separators = set(settings.get('separators', ' ,._，。;；:：!?！？、'))
        self.tempo = 1.0
        self.target_tempo = 1.0
        self.burst_left = 0
        self.effort = 0.0
        self.protected = (self._protected_positions()
                          if self.features['model_english_tokens'] else set())
        self.boundaries = (self._find_boundaries()
                           if self.features['model_smart_pauses'] else {})

    def _protected_positions(self):
        """Punctuation inside addresses, numbers, identifiers and abbreviations."""
        text = self.text
        protected = set()
        for pattern in (ADDRESS, ABBREVIATION, INITIAL):
            for match in pattern.finditer(text):
                end = match.end()
                if pattern is ADDRESS:
                    end = match.start() + len(match.group().rstrip('.,;:!?)]}'))
                protected.update(range(match.start(), end))
        for index in range(1, len(text) - 1):
            char, previous, following = text[index], text[index - 1], text[index + 1]
            if (char in '._' and previous.isalnum() and following.isalnum()
                    or char == ',' and previous.isdigit() and following.isdigit()):
                protected.add(index)
        return protected

    def _find_boundaries(self):
        """Attach one pause to the end of a separator/quote/whitespace run."""
        if not self.separators:
            return {}
        text = self.text
        protected = self.protected
        boundaries = {}
        index = 0
        while index < len(text):
            char = text[index]
            if index in protected or (char not in self.separators and char not in '\r\n'):
                index += 1
                continue
            end = index + 1
            while end < len(text) and end not in protected and (
                text[end] in self.separators or text[end].isspace() or text[end] in CLOSING_MARKS
            ):
                end += 1
            chunk = text[index:end]
            line_breaks = chunk.count('\n') + chunk.count('\r') - chunk.count('\r\n')
            if line_breaks > 1:
                kind = 'paragraph'
            elif line_breaks:
                kind = 'line'
            elif any(mark in chunk for mark in '.!?。！？'):
                kind = 'sentence'
            elif any(mark in chunk for mark in ',;:，；：、'):
                kind = 'clause'
            else:
                kind = 'word'
            if end < len(text):
                boundaries[end - 1] = kind
            index = end
        return boundaries

    def _character_delay(self, index):
        if self.minimum == self.maximum:
            return self.minimum
        char, following = self.text[index:index + 2]
        factor = 1.0
        if self.features['model_tempo']:
            if self.burst_left <= 0:
                span = 0.18 - 0.04 * self.fluency
                self.target_tempo = self.rng.uniform(1 - span, 1 + span)
                self.burst_left = self.rng.randint(12, 32)
            self.burst_left -= 1
            self.tempo += (self.target_tempo - self.tempo) * 0.15
            # Character counts model active effort, so a user pause cannot add fatigue.
            self.effort = min(1.0, self.effort + 0.0008)
            factor *= self.tempo * (1 + self.effort * 0.1)
        if self.features['model_bigrams'] and char.lower() + following.lower() in COMMON_BIGRAMS:
            factor *= 0.82 - 0.04 * self.fluency
        if self.features['model_key_distance']:
            start, end = key_position(char), key_position(following)
            if start is not None and end is not None:
                factor *= 1 + min(abs(end - start), 8) * 0.025 * self.context_cost
            if char == following:
                factor *= 1 + 0.1 * self.context_cost
        if self.features['model_shift_digits']:
            if following.isascii() and following.isdigit():
                factor *= 1 + 0.08 * self.context_cost
            if uses_shift(char) != uses_shift(following):
                factor *= 1 + 0.18 * self.context_cost
        if char.isspace() or following.isspace():
            factor *= 0.9
        midpoint = (self.minimum + self.maximum) / 2
        spread = (self.maximum - self.minimum) / (self.maximum + self.minimum)
        sigma = (0.35 - 0.08 * self.fluency) * spread
        delay = midpoint * factor * self.rng.lognormvariate(-sigma * sigma / 2, sigma)
        return max(self.minimum, min(self.maximum, delay))

    def delay_after(self, index):
        if index >= len(self.text) - 1:
            return 0.0
        char = self.text[index]
        if not self.features['model_smart_pauses'] and char in self.separators and index not in self.protected:
            delay = self.rng.uniform(self.separator_minimum, self.separator_maximum)
        elif index in self.boundaries:
            kind = self.boundaries[index]
            # Separator settings remain hard bounds for every boundary class.
            center = {'word': 0.22, 'clause': 0.5, 'sentence': 0.75,
                      'line': 0.85, 'paragraph': 0.95}[kind]
            center -= 0.05 * self.fluency
            fraction = max(0, min(1, self.rng.gauss(center, 0.1)))
            delay = self.separator_minimum + (self.separator_maximum - self.separator_minimum) * fraction
            if kind != 'word':
                self.effort *= 0.7
                self.target_tempo = 1.0
        else:
            delay = self._character_delay(index)
        return delay / 1000
