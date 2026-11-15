"""Les états du cadre Noise (révision 34, § 5) et les calculs P-256 — comme `Noise.kt` (lot 1).

Une seule bibliothèque : `cryptography` (fournie par Home Assistant). Les écarts au Noise publié
(P-256 au lieu de 25519) sont dits en tête de `Protocole.kt`.
"""
import hashlib
import hmac
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .protocole import TAILLE_PRIVEE, est_une_cle_publique

HASHLEN = 32
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def sha256(d: bytes) -> bytes:
    return hashlib.sha256(d).digest()


def dh(privee: bytes, publique: bytes) -> Optional[bytes]:
    """ECDH P-256 : la coordonnée x, 32 octets. None si la clé publique n'est pas un point de la courbe."""
    if len(privee) != TAILLE_PRIVEE or not est_une_cle_publique(publique):
        return None
    s = int.from_bytes(privee, "big")
    if not 0 < s < _N:
        return None
    try:
        # `from_encoded_point` vérifie que le point est sur la courbe, et le refuse sinon.
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), publique)
        return ec.derive_private_key(s, ec.SECP256R1()).exchange(ec.ECDH(), pub)
    except ValueError:
        return None


def _hkdf(cle: bytes, materiau: bytes, n: int):
    temp = hmac.new(cle, materiau, hashlib.sha256).digest()
    sorties, precedent = [], b""
    for i in range(1, n + 1):
        precedent = hmac.new(temp, precedent + bytes([i]), hashlib.sha256).digest()
        sorties.append(precedent)
    return sorties


class Chiffre:
    """`CipherState` : une clé (ou aucune) et un compteur qui sert de nonce."""

    def __init__(self, cle: Optional[bytes] = None):
        self._cle = cle
        self._aead = AESGCM(cle) if cle else None
        self._n = 0

    @staticmethod
    def _nonce(n: int) -> bytes:
        return b"\x00" * 4 + n.to_bytes(8, "big")

    def chiffrer(self, ad: bytes, clair: bytes) -> bytes:
        if self._aead is None:
            return clair
        c = self._aead.encrypt(self._nonce(self._n), clair, ad)
        self._n += 1
        return c

    def dechiffrer(self, ad: bytes, chiffre: bytes) -> Optional[bytes]:
        """None si l'étiquette ne correspond pas ; le compteur n'avance qu'en cas de succès."""
        if self._aead is None:
            return chiffre
        try:
            c = self._aead.decrypt(self._nonce(self._n), chiffre, ad)
        except (InvalidTag, ValueError):
            return None
        self._n += 1
        return c


class Symetrique:
    """`SymmetricState`."""

    def __init__(self, nom: bytes):
        self.hachage = nom.ljust(HASHLEN, b"\x00") if len(nom) <= HASHLEN else sha256(nom)
        self._chainage = self.hachage
        self._chiffre = Chiffre()

    def melanger_cle(self, materiau: bytes) -> None:
        self._chainage, k = _hkdf(self._chainage, materiau, 2)
        self._chiffre = Chiffre(k)

    def melanger_hachage(self, d: bytes) -> None:
        self.hachage = sha256(self.hachage + d)

    def chiffrer_et_hacher(self, clair: bytes) -> bytes:
        c = self._chiffre.chiffrer(self.hachage, clair)
        self.melanger_hachage(c)
        return c

    def dechiffrer_et_hacher(self, c: bytes) -> Optional[bytes]:
        clair = self._chiffre.dechiffrer(self.hachage, c)
        if clair is not None:
            self.melanger_hachage(c)
        return clair

    def separer(self):
        """`Split` : (initiateur → répondeur, répondeur → initiateur)."""
        k1, k2 = _hkdf(self._chainage, b"", 2)
        return Chiffre(k1), Chiffre(k2)
