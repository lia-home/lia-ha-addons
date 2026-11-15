"""La clé de la maison : une paire P-256, créée une fois, gardée sur le disque du module.

Elle ne quitte jamais la maison ; seule la partie publique est montrée (à l'app, par Home
Assistant, pour qu'elle l'épingle). Une sauvegarde de HA l'emporte avec l'add-on ou
l'intégration : une restauration la rend telle quelle.

⚠️ Un fichier abîmé n'est JAMAIS remplacé en silence : une clé neuve changerait l'identité de la
maison, et les téléphones qui ont épinglé l'ancienne ne la reconnaîtraient plus. On refuse, et
on le dit ; c'est à l'humain de trancher (réinstaller le module).
"""
import dataclasses
import json
import os

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .protocole import TAILLE_PRIVEE, est_une_cle_publique


@dataclasses.dataclass(frozen=True)
class PaireDeCles:
    privee: bytes
    publique: bytes

    def __post_init__(self):
        if len(self.privee) != TAILLE_PRIVEE or not est_une_cle_publique(self.publique):
            raise ValueError("paire de clés P-256 mal formée")


def _publique(prive: ec.EllipticCurvePrivateKey) -> bytes:
    return prive.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def generer() -> PaireDeCles:
    """Une paire neuve, tirée au hasard du système."""
    prive = ec.generate_private_key(ec.SECP256R1())
    return PaireDeCles(prive.private_numbers().private_value.to_bytes(32, "big"), _publique(prive))


def charger_ou_creer(chemin: str) -> PaireDeCles:
    """La paire rangée dans [chemin], ou une neuve, écrite lisible par le seul propriétaire du fichier."""
    if os.path.exists(chemin):
        try:
            with open(chemin, encoding="utf-8") as f:
                o = json.load(f)
            paire = PaireDeCles(bytes.fromhex(o["privee"]), bytes.fromhex(o["publique"]))
            # La publique doit aller avec la privée : sinon le fichier a été trafiqué.
            prive = ec.derive_private_key(int.from_bytes(paire.privee, "big"), ec.SECP256R1())
            if _publique(prive) != paire.publique:
                raise ValueError("la clé publique ne va pas avec la clé privée")
            return paire
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ValueError("clé de la maison illisible (%s) : %s — rien n'est remplacé" % (type(e).__name__, chemin)) from None
    os.makedirs(os.path.dirname(os.path.abspath(chemin)), exist_ok=True)
    paire = generer()
    # Créée en 0600 d'emblée (jamais lisible par d'autres, même un instant), et jamais par-dessus un fichier.
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "privee": paire.privee.hex(), "publique": paire.publique.hex()}, f)
    return paire
