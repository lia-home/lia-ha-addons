"""Une session établie : les trames chiffrées, découpées et recollées (`Session` de Kotlin, lot 1).

Une trame = AESGCM(clé de ce sens, compteur, ∅, genre || données). Une trame fausse, rejouée ou
hors d'ordre ferme la session pour de bon : le compteur ne pardonne pas.
"""
import dataclasses
from typing import List, Optional, Union

from .protocole import MAX_DONNEES, MAX_MESSAGE, Genre


@dataclasses.dataclass(frozen=True)
class Message:
    octets: bytes


@dataclasses.dataclass(frozen=True)
class Fermeture:
    raison: str


@dataclasses.dataclass(frozen=True)
class AuModule:
    octets: bytes


@dataclasses.dataclass(frozen=True)
class Invalide:
    raison: str


Recu = Union[Message, Fermeture, AuModule, Invalide]


class Session:
    def __init__(self, hachage: bytes, envoi, reception):
        self.hachage = hachage
        self._envoi = envoi
        self._reception = reception
        self._morceaux: List[bytes] = []
        self._taille = 0
        self._fermee: Optional[str] = None

    def chiffrer(self, genre: Genre, donnees: bytes) -> List[bytes]:
        """Les trames d'un message : morceaux de MAX_DONNEES octets au plus, tous MORCEAU sauf le dernier."""
        trames, debut = [], 0
        while True:
            fin = min(debut + MAX_DONNEES, len(donnees))
            g = genre if fin == len(donnees) else Genre.MORCEAU
            trames.append(self._envoi.chiffrer(b"", bytes([g]) + donnees[debut:fin]))
            debut = fin
            if fin == len(donnees):
                return trames

    def lire(self, trame: bytes) -> Optional[Recu]:
        """None tant qu'un message en morceaux n'est pas complet ; Invalide ferme la session pour de bon."""
        if self._fermee is not None:
            return Invalide(self._fermee)
        clair = self._reception.dechiffrer(b"", trame)
        if clair is None:
            return self._invalider("trame fausse, rejouée ou hors d'ordre")
        if not clair:
            return self._invalider("trame vide")
        try:
            genre = Genre(clair[0])
        except ValueError:
            return self._invalider("genre de trame inconnu")
        if self._taille + len(clair) - 1 > MAX_MESSAGE:
            return self._invalider("message trop grand")
        self._morceaux.append(clair[1:])
        self._taille += len(clair) - 1
        if genre == Genre.MORCEAU:
            return None
        tout = b"".join(self._morceaux)
        self._morceaux, self._taille = [], 0
        if genre == Genre.FERMETURE:
            return Fermeture(tout.decode("utf-8", "replace"))
        if genre == Genre.AU_MODULE:
            return AuModule(tout)
        return Message(tout)

    def _invalider(self, raison: str) -> Invalide:
        self._fermee = raison
        self._morceaux, self._taille = [], 0
        return Invalide(raison)
