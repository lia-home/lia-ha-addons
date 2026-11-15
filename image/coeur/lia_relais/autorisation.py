"""QUI LA MAISON LAISSE ENTRER — une interface, sans trancher (10/11).

Le propriétaire n'a pas encore choisi entre le concierge (le module n'accepte que des téléphones
qu'il connaît) et la clé du foyer chiffrée de bout en bout (le module reste un tuyau) :
`docs/revue/12-acces-de-dehors.md` § Suite 6. Le module ne décide donc rien lui-même : il demande
à une `Autorisation`. Par défaut, `ToutAccepter` : la porte reste gardée par le relais (un compte
Lia membre du foyer) et par la clé de Home Assistant que l'app envoie.
"""
from typing import Optional, Protocol

from .poignee import Premier
from .protocole import Statut


class Autorisation(Protocol):
    async def decider(self, premier: Premier) -> Statut:
        """Accepter ou refuser un téléphone, d'après le message 1 (sa clé s'il en montre une, motif IK)."""
        ...

    async def au_module(self, premier: Premier, octets: bytes) -> Optional[bytes]:
        """Un message pour le module lui-même (genre AU_MODULE). Rend la réponse à renvoyer, ou None."""
        ...


class ToutAccepter:
    """Accepte tout téléphone qui a passé le relais ; ne répond à aucun message au module."""

    async def decider(self, premier: Premier) -> Statut:
        return Statut.ACCEPTE

    async def au_module(self, premier: Premier, octets: bytes) -> Optional[bytes]:
        return None
