"""Le contrôle du relais — les chemins, les messages en clair, les codes de fermeture (`Controle.kt`, lot 1)."""
import dataclasses
import json
import re
from typing import Optional, Union

from .protocole import VERSION

CHEMIN_MAISON = "/v1/maison"
PING_SECONDES = 25

NON_AUTORISE = 4401
MAISON_INCONNUE = 4404
VERSION_REFUSEE = 4426
TROP_DE_DEMANDES = 4429
MAISON_HORS_LIGNE = 4503

_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def chemin_session(id_session: str) -> str:
    return "/v1/maison/session/" + id_session


def chemin_app(id_maison: str) -> str:
    return "/v1/app/" + id_maison


def est_un_id_de_session(id_session) -> bool:
    """8 à 64 lettres, chiffres ou tirets : rien d'autre n'entre dans une adresse."""
    return isinstance(id_session, str) and _ID.match(id_session) is not None


@dataclasses.dataclass(frozen=True)
class Bonjour:
    version: int = VERSION


@dataclasses.dataclass(frozen=True)
class DemandeDeSession:
    id: str


@dataclasses.dataclass(frozen=True)
class Fin:
    raison: str


Message = Union[Bonjour, DemandeDeSession, Fin]


def encoder(message: Message) -> str:
    """Le texte exact, le même que celui de Kotlin (`ControleTest`)."""
    if isinstance(message, Bonjour):
        o = {"type": "bonjour", "v": message.version}
    elif isinstance(message, DemandeDeSession):
        o = {"type": "session", "id": message.id}
    else:
        o = {"type": "fin", "raison": message.raison}
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def lire(texte: str) -> Optional[Message]:
    """Le message lu, ou None s'il est illisible ou inconnu (ignoré, sans planter)."""
    try:
        o = json.loads(texte)
    except (ValueError, TypeError):
        return None
    if not isinstance(o, dict):
        return None
    genre = o.get("type")
    if genre == "bonjour":
        v = o.get("v")
        return Bonjour(v) if isinstance(v, int) and not isinstance(v, bool) else None
    if genre == "session":
        i = o.get("id")
        return DemandeDeSession(i) if est_un_id_de_session(i) else None
    if genre == "fin":
        r = o.get("raison")
        return Fin(r if isinstance(r, str) else "")
    return None
