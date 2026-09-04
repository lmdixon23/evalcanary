"""Exact JSON numeric parsing and canonical identity serialization."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from fractions import Fraction
from typing import Any

from ..errors import InputValidationError

_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def parse_decimal_token(token: str) -> Decimal:
    """Parse one bounded JSON number directly from its lexical token."""

    try:
        raw = token.encode("ascii")
    except UnicodeEncodeError as exc:  # pragma: no cover - JSON grammar is ASCII
        raise InputValidationError("Numeric token is not ASCII.") from exc
    if len(raw) > 128 or _JSON_NUMBER.fullmatch(token) is None:
        raise InputValidationError("Numeric token violates the bounded JSON grammar.")
    coefficient_text = token
    exponent_text: str | None = None
    if "e" in coefficient_text.lower():
        coefficient_text, exponent_text = re.split("[eE]", coefficient_text, maxsplit=1)
    coefficient_digits = sum(character.isdigit() for character in coefficient_text)
    if coefficient_digits > 100:
        raise InputValidationError("Numeric coefficient exceeds 100 digits.")
    value = Decimal(token)
    if not value.is_finite():
        raise InputValidationError("Non-finite numeric values are not permitted.")
    if value.is_zero():
        written_exponent = int(exponent_text or "0")
        if abs(written_exponent) > 1000:
            raise InputValidationError("Zero exponent magnitude exceeds 1000.")
    elif not -1000 <= value.adjusted() <= 1000:
        raise InputValidationError(
            "Numeric adjusted exponent is outside [-1000, 1000]."
        )
    return value


def reject_constant(token: str) -> None:
    raise InputValidationError(f"Non-finite JSON constant is not permitted: {token}")


def canonical_decimal(value: Decimal) -> str:
    """Return the context-independent R1A ordinary-decimal representation."""

    if not value.is_finite():
        raise InputValidationError("Non-finite numeric values are not permitted.")
    if value.is_zero():
        return "0"
    sign, digits_tuple, raw_exponent = value.as_tuple()
    exponent = int(raw_exponent)
    digits = list(digits_tuple)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(item) for item in digits)
    point = len(coefficient) + exponent
    if point <= 0:
        body = "0." + ("0" * -point) + coefficient
    elif point >= len(coefficient):
        body = coefficient + ("0" * (point - len(coefficient)))
    else:
        body = coefficient[:point] + "." + coefficient[point:]
    return ("-" if sign else "") + body


def decimal_to_fraction(value: Decimal) -> Fraction:
    return Fraction(value)


def fraction_facts(value: Fraction) -> dict[str, int | str | None]:
    """Represent an exact rational and include a decimal only when terminating."""

    denominator = value.denominator
    reduced = denominator
    for factor in (2, 5):
        while reduced % factor == 0:
            reduced //= factor
    decimal: str | None = None
    if reduced == 1:
        # Decimal division is context-sensitive, so format through integer scaling.
        twos = 0
        fives = 0
        work = denominator
        while work % 2 == 0:
            twos += 1
            work //= 2
        while work % 5 == 0:
            fives += 1
            work //= 5
        digits_after = max(twos, fives)
        multiplier = (2 ** (digits_after - twos)) * (5 ** (digits_after - fives))
        scaled_numerator = value.numerator * multiplier
        sign = "-" if scaled_numerator < 0 else ""
        raw = str(abs(scaled_numerator)).rjust(digits_after + 1, "0")
        if digits_after:
            decimal = sign + raw[:-digits_after] + "." + raw[-digits_after:]
        else:
            decimal = sign + raw
        decimal = canonical_decimal(Decimal(decimal))
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": decimal,
    }


def canonical_json_text(value: Any) -> str:
    """Serialize JSON plus Decimal using the locked canonical form."""

    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise TypeError("Binary float is forbidden in assurance canonical JSON.")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list | tuple):
        return "[" + ",".join(canonical_json_text(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Canonical JSON object keys must be strings.")
        pieces = []
        for key in sorted(value):
            pieces.append(
                canonical_json_text(key) + ":" + canonical_json_text(value[key])
            )
        return "{" + ",".join(pieces) + "}"
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json_text(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
