"""Les réglages du module, communs à l'intégration et à l'add-on (lot 6). Sans Home Assistant.

- **Le relais** : une adresse `wss://hôte[:port]`, sans chemin, sans identifiants, sans requête.
  `ws://` (sans cadenas) n'est permis que vers le banc : une adresse privée, de boucle, ou un nom en
  `.local` / `.test` (le relais d'essai du i7). Un vrai relais est toujours en `wss://`.
- **Le jeton de la maison** : donné par notre cloud à l'enrôlement (lot 2) ; 16 à 512 caractères
  visibles, sans espace.
- **L'adresse de HA** vue de l'intérieur : le port est celui que HA sert (`hass.http.server_port`),
  jamais une valeur supposée (`docs/revue/12-acces-de-dehors.md` § Suite 3).
"""
import ipaddress
import re
import urllib.parse
from typing import Dict

_JETON = re.compile(r"^[\x21-\x7e]{16,512}$")


def _hote_du_banc(hote: str) -> bool:
    h = hote.lower().rstrip(".")
    if h == "localhost" or h.endswith(".local") or h.endswith(".test"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _relais(relais: str):
    """None si l'adresse est bonne, sinon le code d'erreur."""
    if not relais or any(c.isspace() for c in relais):
        return "relais_illisible"
    try:
        u = urllib.parse.urlsplit(relais)
        _ = u.port  # un port impossible lève ValueError
    except ValueError:
        return "relais_illisible"
    if u.scheme not in ("ws", "wss") or not u.hostname or u.username or u.password:
        return "relais_illisible"
    if u.path not in ("", "/") or u.query or u.fragment:
        return "relais_illisible"
    if u.scheme == "ws" and not _hote_du_banc(u.hostname):
        return "relais_sans_cadenas"
    return None


def valider(relais: str, jeton: str) -> Dict[str, str]:
    """Les erreurs, champ par champ ({} : tout va)."""
    erreurs = {}
    e = _relais(relais)
    if e:
        erreurs["relais"] = e
    if not isinstance(jeton, str) or not _JETON.match(jeton):
        erreurs["jeton"] = "jeton_illisible"
    return erreurs


def url_ha(port: int, tls: bool, hote: str = "127.0.0.1") -> str:
    """Le WebSocket de HA vu de l'intérieur, au port que HA sert.

    `hote` : 127.0.0.1 pour l'intégration (elle tourne dans HA) ; « homeassistant » pour l'add-on, dont
    le conteneur joint HA par ce nom sur le réseau des add-ons (lot 5).
    """
    return "%s://%s:%d/api/websocket" % ("wss" if tls else "ws", hote, port)
