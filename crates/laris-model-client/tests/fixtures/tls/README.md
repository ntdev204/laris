Test-only certificates for the pin and wire tests of T128: `ca.der` signs `leaf.der` (DNS `localhost`), `other.der` is an
unrelated authority, and `leaf.key.der` is the private key of `leaf.der` for the local TLS server of the wire tests.
ECDSA P-256, valid 100 years, made with `openssl`. The keys protect nothing and nothing here is used outside tests.
