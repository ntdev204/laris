"""Number theory on integers: gcd, lcm, factorisation, primality, modular arithmetic, CRT,
totient, divisors, binomial, factorial and base conversion.

The primary result comes from SymPy (or Python); each check is computed another way in plain
Python: Euclid's algorithm, a deterministic Miller-Rabin test (exact below 3.3e24; above that a
factor's primality is not checked and the answer stays a proposal), square-and-multiply, the
congruences themselves, multiplicative formulas from a checked factorisation, `math.comb`,
`math.factorial` and Horner's rule.
"""

from __future__ import annotations

import math
from functools import reduce
from typing import Dict, List

from laris.model.solver.context import Context
from laris.model.solver.errors import SolverError
from laris.model.solver.numeric import Check
from laris.model.solver.result import Outcome

MILLER_RABIN_BOUND = 3_317_044_064_679_887_385_961_981  # first 13 primes as bases are exact below
_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41)
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def miller_rabin(n: int) -> bool:
    """Deterministic primality for n < MILLER_RABIN_BOUND."""
    if n < 2:
        return False
    for p in _BASES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in _BASES:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def euclid(a: int, b: int) -> int:
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def _integers(ctx: Context, key: str = "integers") -> List[int]:
    return [ctx.parser.integer(v, key) for v in ctx.items(key)]


def _one(ctx: Context, key: str) -> int:
    return ctx.parser.integer(ctx.require(key), key)


def _positive(n: int, key: str) -> None:
    if n < 1:
        raise SolverError("invalid_arguments", f"{key} must be a positive integer")


def _plain(answer, checks, notes=None) -> Outcome:
    out = Outcome(answer, str(answer), checks)
    out.notes.extend(notes or [])
    return out


def gcd(ctx: Context) -> Outcome:
    import sympy

    values = _integers(ctx)
    found = int(reduce(sympy.igcd, values))
    return _plain(found, [Check("Euclid's algorithm", found == reduce(euclid, values))])


def lcm(ctx: Context) -> Outcome:
    import sympy

    values = _integers(ctx)
    if 0 in values:
        raise SolverError("invalid_arguments", "lcm needs non-zero integers")
    found = int(reduce(sympy.ilcm, values))
    direct = reduce(lambda a, b: abs(a * b) // euclid(a, b), values)
    divides = all(found % v == 0 for v in values)
    return _plain(
        found, [Check("product over gcd (Euclid) and divisibility", found == direct and divides)]
    )


def _checked_factorisation(n: int):
    """`(factors, checks)` of |n| with the product and primality checked independently."""
    import sympy

    factors: Dict[int, int] = {int(p): int(e) for p, e in sympy.factorint(abs(n)).items()}
    product = 1
    for p, e in factors.items():
        product *= p**e
    checks = [Check("product of the factors", product == abs(n))]
    large = [p for p in factors if p >= MILLER_RABIN_BOUND]
    checks.append(
        Check(
            "deterministic Miller-Rabin on every factor",
            not large and all(miller_rabin(p) for p in factors),
            "a factor is beyond the deterministic bound" if large else "",
        )
    )
    return factors, checks


def factor_integer(ctx: Context) -> Outcome:
    n = _one(ctx, "integer")
    if n == 0:
        raise SolverError("invalid_arguments", "0 has no prime factorisation")
    factors, checks = _checked_factorisation(n)
    answer = [{"prime": p, "exponent": e} for p, e in sorted(factors.items())]
    text = " * ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(factors.items())) or "1"
    return Outcome(answer, ("-" if n < 0 else "") + text, checks)


def is_prime(ctx: Context) -> Outcome:
    import sympy

    n = _one(ctx, "integer")
    found = bool(sympy.isprime(n))
    if n >= MILLER_RABIN_BOUND:
        return _plain(
            found, [Check("deterministic Miller-Rabin", False, "beyond the deterministic bound")]
        )
    return _plain(found, [Check("deterministic Miller-Rabin", found == miller_rabin(n))])


def mod_pow(ctx: Context) -> Outcome:
    base, exponent, modulus = _one(ctx, "base"), _one(ctx, "exponent"), _one(ctx, "modulus")
    _positive(modulus, "modulus")
    if exponent < 0:
        raise SolverError("invalid_arguments", "exponent must not be negative; use mod_inverse")
    found = pow(base, exponent, modulus)
    result, b, e = 1 % modulus, base % modulus, exponent
    while e:
        if e & 1:
            result = result * b % modulus
        b = b * b % modulus
        e >>= 1
    return _plain(found, [Check("square-and-multiply", found == result)])


def mod_inverse(ctx: Context) -> Outcome:
    import sympy

    a, modulus = _one(ctx, "integer"), _one(ctx, "modulus")
    _positive(modulus, "modulus")
    if euclid(a, modulus) != 1:
        raise SolverError("rejected", "the integer and the modulus are not coprime")
    found = int(sympy.mod_inverse(a, modulus))
    return _plain(
        found, [Check("a times the inverse is 1 modulo m", (a * found) % modulus == 1 % modulus)]
    )


def crt(ctx: Context) -> Outcome:
    from sympy.ntheory.modular import crt as sympy_crt

    residues, moduli = _integers(ctx, "integers"), _integers(ctx, "moduli")
    if len(residues) != len(moduli):
        raise SolverError(
            "invalid_arguments", "integers (residues) and moduli must have the same length"
        )
    for m in moduli:
        _positive(m, "moduli")
    found = sympy_crt(moduli, residues, check=True)
    if found is None:
        raise SolverError("rejected", "the congruences have no common solution")
    x, modulus = int(found[0]), int(found[1])
    lcm_all = reduce(lambda a, b: a * b // euclid(a, b), moduli)
    ok = modulus == lcm_all and all((x - r) % m == 0 for r, m in zip(residues, moduli))
    answer = {"residue": x, "modulus": modulus}
    return Outcome(
        answer,
        f"x = {x} (mod {modulus})",
        [Check("every congruence holds; modulus is the lcm", ok)],
    )


def totient(ctx: Context) -> Outcome:
    import sympy

    n = _one(ctx, "integer")
    _positive(n, "integer")
    found = int(sympy.totient(n))
    factors, checks = _checked_factorisation(n)
    formula = n
    for p in factors:
        formula = formula // p * (p - 1)
    checks.append(Check("product formula over the checked factors", formula == found))
    return _plain(found, checks)


def divisors(ctx: Context) -> Outcome:
    import sympy

    n = _one(ctx, "integer")
    _positive(n, "integer")
    factors, checks = _checked_factorisation(n)
    count = math.prod(e + 1 for e in factors.values())
    if count > ctx.settings.max_items * 64:
        raise SolverError("input_too_large", "the integer has too many divisors to list")
    found = [int(d) for d in sympy.divisors(n)]
    total = math.prod((p ** (e + 1) - 1) // (p - 1) for p, e in factors.items())
    ok = len(found) == count and all(n % d == 0 for d in found) and sum(found) == total
    checks.append(Check("every divisor divides; count and sum by the divisor formulas", ok))
    answer = {"divisors": found, "count": len(found), "sum": sum(found)}
    return Outcome(answer, f"{len(found)} divisors: " + ", ".join(map(str, found)), checks)


def binomial(ctx: Context) -> Outcome:
    import sympy

    n, k = _one(ctx, "n"), _one(ctx, "k")
    if n < 0 or k < 0 or n > ctx.settings.max_exponent:
        raise SolverError(
            "invalid_arguments", f"binomial needs 0 <= k and 0 <= n <= {ctx.settings.max_exponent}"
        )
    found = int(sympy.binomial(n, k))
    return _plain(found, [Check("math.comb", found == math.comb(n, k))])


def factorial(ctx: Context) -> Outcome:
    import sympy

    n = _one(ctx, "integer")
    if not 0 <= n <= min(ctx.settings.max_exponent, 3000):
        raise SolverError("invalid_arguments", "factorial needs a small non-negative integer")
    found = int(sympy.factorial(n))
    if len(str(found)) > ctx.settings.max_result_chars:
        raise SolverError("input_too_large", "the factorial is too long to report")
    return _plain(found, [Check("math.factorial", found == math.factorial(n))])


def _base(ctx: Context) -> int:
    base = _one(ctx, "base")
    if not 2 <= base <= 36:
        raise SolverError("invalid_arguments", "base must be from 2 to 36")
    return base


def to_base(ctx: Context) -> Outcome:
    import sympy

    n, base = _one(ctx, "integer"), _base(ctx)
    found_digits = sympy.ntheory.digits(abs(n), base)[1:]
    text = ("-" if n < 0 else "") + "".join(DIGITS[d] for d in found_digits)
    ok = int(text, base) == n
    return Outcome(text, f"{text} (base {base})", [Check("Python int() reads it back", ok)])


def from_base(ctx: Context) -> Outcome:
    digits_text, base = ctx.text("digits"), _base(ctx)
    clean = digits_text.strip().lower()
    negative = clean.startswith("-")
    body = clean.lstrip("+-")
    if not body or any(c not in DIGITS[:base] for c in body):
        raise SolverError("invalid_arguments", f"digits must be digits of base {base}")
    found = int(clean, base)
    horner = 0
    for c in body:
        horner = horner * base + DIGITS.index(c)
    horner = -horner if negative else horner
    return _plain(found, [Check("Horner's rule", found == horner)])
