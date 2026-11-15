"""La poignée de main — les deux côtés, d'après la spécification du lot 1 (`Protocole.kt`).

Motif NK : `<- s` ; `-> e, es` ; `<- e, ee`.
Motif IK : `<- s` ; `-> e, es, s, ss` ; `<- e, ee, se`.
Le message 1 part précédé d'UN octet qui dit le motif.

`PoigneeMaison` est ce que fait le module. `PoigneeTelephone` sert aux tests (et à un éventuel
client d'essai) : le vrai téléphone, c'est l'app (Kotlin, lot 8).
"""
import dataclasses
from typing import Optional

from .cles import PaireDeCles, generer
from .noise import Symetrique, dh
from .protocole import (CHARGE_1, MOTIF_IK, MOTIF_NK, NOMS_DES_MOTIFS, PROLOGUE, TAILLE_ETIQUETTE,
                        TAILLE_PUBLIQUE, Statut, est_une_cle_publique)
from .session import Session

DHLEN = TAILLE_PUBLIQUE
S_CHIFFREE = TAILLE_PUBLIQUE + TAILLE_ETIQUETTE


@dataclasses.dataclass(frozen=True)
class Premier:
    """Ce que dit le message 1. `telephone` : la clé du téléphone (motif IK), ou None (NK)."""
    motif: int
    telephone: Optional[bytes]
    charge: bytes


def _debut(motif: int, cle_maison: bytes) -> Symetrique:
    """`Initialize` : le nom du motif, le prologue, puis la pré-clé `<- s` (celle de la maison)."""
    s = Symetrique(NOMS_DES_MOTIFS[motif])
    s.melanger_hachage(PROLOGUE)
    s.melanger_hachage(cle_maison)
    return s


class PoigneeMaison:
    def __init__(self, cle: PaireDeCles, ephemere: Optional[PaireDeCles] = None):
        self._cle = cle
        self._ephemere = ephemere or generer()
        self._etat: Optional[Symetrique] = None
        self._re: Optional[bytes] = None
        self._rs: Optional[bytes] = None
        self._lu = False
        self._repondu = False

    def lire_premier(self, message: bytes) -> Optional[Premier]:
        """Lit le message 1 tel qu'il arrive du fil ; None s'il ne s'accorde pas. Une seule fois."""
        if self._lu or not message:
            return None
        self._lu = True
        motif, corps = message[0], message[1:]
        if motif not in NOMS_DES_MOTIFS:
            return None
        ik = motif == MOTIF_IK
        if len(corps) < DHLEN + (S_CHIFFREE if ik else 0) + TAILLE_ETIQUETTE:
            return None
        s = _debut(motif, self._cle.publique)
        re = corps[:DHLEN]
        if not est_une_cle_publique(re):
            return None
        s.melanger_hachage(re)                                   # -> e
        k = dh(self._cle.privee, re)                             # es
        if k is None:
            return None
        s.melanger_cle(k)
        reste, rs = corps[DHLEN:], None
        if ik:
            rs = s.dechiffrer_et_hacher(reste[:S_CHIFFREE])      # s
            if rs is None or not est_une_cle_publique(rs):
                return None
            k = dh(self._cle.privee, rs)                         # ss
            if k is None:
                return None
            s.melanger_cle(k)
            reste = reste[S_CHIFFREE:]
        charge = s.dechiffrer_et_hacher(reste)
        if charge is None:
            return None
        self._etat, self._re, self._rs = s, re, rs
        return Premier(motif, rs, charge)

    def repondre(self, statut: Statut = Statut.ACCEPTE):
        """Rend (message 2, session) ; la session est None si la maison refuse. Une seule fois."""
        if self._etat is None:
            raise RuntimeError("aucun message 1 lu")
        if self._repondu:
            raise RuntimeError("la maison a déjà répondu")
        self._repondu = True
        s = self._etat
        sortie = self._ephemere.publique                         # <- e
        s.melanger_hachage(self._ephemere.publique)
        s.melanger_cle(dh(self._ephemere.privee, self._re))      # ee
        if self._rs is not None:
            s.melanger_cle(dh(self._ephemere.privee, self._rs))  # se
        sortie += s.chiffrer_et_hacher(statut.charge)
        if statut != Statut.ACCEPTE:
            return sortie, None
        depuis_le_telephone, vers_le_telephone = s.separer()
        return sortie, Session(s.hachage, envoi=vers_le_telephone, reception=depuis_le_telephone)


class PoigneeTelephone:
    def __init__(self, cle_maison: bytes, cle_telephone: Optional[PaireDeCles] = None,
                 ephemere: Optional[PaireDeCles] = None):
        if not est_une_cle_publique(cle_maison):
            raise ValueError("clé de la maison mal formée")
        self._cle_maison = cle_maison
        self._cle_telephone = cle_telephone
        self._ephemere = ephemere or generer()
        self.motif = MOTIF_NK if cle_telephone is None else MOTIF_IK
        self._etat: Optional[Symetrique] = None
        self._reponse_lue = False

    def premier_message(self) -> bytes:
        if self._etat is not None:
            raise RuntimeError("le message 1 est déjà parti")
        s = _debut(self.motif, self._cle_maison)
        sortie = self._ephemere.publique                         # -> e
        s.melanger_hachage(self._ephemere.publique)
        k = dh(self._ephemere.privee, self._cle_maison)          # es
        if k is None:
            raise ValueError("la clé de la maison n'est pas un point de P-256")
        s.melanger_cle(k)
        if self._cle_telephone is not None:
            sortie += s.chiffrer_et_hacher(self._cle_telephone.publique)                # s
            s.melanger_cle(dh(self._cle_telephone.privee, self._cle_maison))            # ss
        sortie += s.chiffrer_et_hacher(CHARGE_1)
        self._etat = s
        return bytes([self.motif]) + sortie

    def lire_reponse(self, message: bytes):
        """Rend (statut, session) ; (None, None) si rien ne s'accorde. Une seule fois."""
        s = self._etat
        if s is None or self._reponse_lue or len(message) < DHLEN + TAILLE_ETIQUETTE:
            return None, None
        self._reponse_lue = True
        re = message[:DHLEN]
        if not est_une_cle_publique(re):
            return None, None
        s.melanger_hachage(re)                                   # <- e
        for privee in [self._ephemere.privee] + ([self._cle_telephone.privee] if self._cle_telephone else []):
            k = dh(privee, re)                                   # ee, puis se
            if k is None:
                return None, None
            s.melanger_cle(k)
        charge = s.dechiffrer_et_hacher(message[DHLEN:])
        statut = Statut.lire(charge) if charge is not None else None
        if statut is None:
            return None, None
        if statut != Statut.ACCEPTE:
            return statut, None
        vers_la_maison, depuis_la_maison = s.separer()
        return statut, Session(s.hachage, envoi=vers_la_maison, reception=depuis_la_maison)
