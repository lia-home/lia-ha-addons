"""LIA — ACCÈS DE DEHORS, l'add-on pour HA OS et Supervised (lot 5, 10/11).

Il fait tourner le cœur du module (`coeur/lia_relais`, le lot 4, copié dans l'image) dans un conteneur
à côté de HA : une ligne sortante vers le relais de Lia, une ligne par session, chiffrée de bout en
bout, et le pont vers le WebSocket de HA. Il ne garde aucune clé de HA : l'app envoie la sienne,
dans la session. Rien n'entre dans la maison : c'est lui qui appelle.

Ce que l'add-on ajoute au cœur, comme l'intégration (lot 6) le fait dans HA :
- ses réglages, `/data/options.json`, posés par l'app par `supervisor/api` (`relais`, `jeton`) ;
- la clé de la maison, `/data/cle.json` : une sauvegarde de HA l'emporte avec l'add-on ;
- l'adresse de HA, au port que HA sert, lu chez le Supervisor (`/core/info`) : jamais 8123 supposé ;
- l'entité `binary_sensor.lia_acces_de_dehors` (la même que l'intégration) : la ligne tient-elle,
  et la clé PUBLIQUE, que l'app lit chez HA et épingle. Elle est montrée dès l'installation, avant
  tout réglage : l'app en a besoin pour inscrire la maison (lot 7a).

Le jeton de la maison n'est jamais écrit au journal ni dans l'entité.
"""
import asyncio
import hashlib
import json
import logging
import os
import signal
from typing import Dict, Tuple

import aiohttp

from lia_relais.cles import charger_ou_creer
from lia_relais.module import Module
from lia_relais.reglages import url_ha, valider

JOURNAL = logging.getLogger("lia_addon")

ENTITE = "binary_sensor.lia_acces_de_dehors"
# Le nom de HA sur le réseau des add-ons : 127.0.0.1 serait le conteneur lui-même.
HOTE_HA = "homeassistant"


def lire_options(chemin: str) -> Tuple[str, str]:
    """(relais, jeton) posés par l'app ; vides tant que l'add-on n'est pas réglé."""
    try:
        with open(chemin, encoding="utf-8") as f:
            o = json.load(f)
    except FileNotFoundError:
        return "", ""

    def texte(cle):
        v = o.get(cle)
        return v.strip() if isinstance(v, str) else ""

    return texte("relais"), texte("jeton")


def url_ha_depuis_info(info: dict) -> Tuple[str, bool]:
    """L'adresse du WebSocket de HA, d'après `/core/info` du Supervisor, et s'il sert en https."""
    port = info.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("port de HA illisible : %r" % (port,))
    tls = info.get("ssl") is True
    return url_ha(port, tls, hote=HOTE_HA), tls


def etat_entite(connecte: bool, publique: bytes, erreurs: Dict[str, str], reglee: bool) -> dict:
    attributs = {
        "friendly_name": "Lia — accès de dehors",
        "device_class": "connectivity",
        "icon": "mdi:home-export-outline",
        "cle_publique": publique.hex(),
        "empreinte": hashlib.sha256(publique).hexdigest(),
        "reglee": reglee,
    }
    if erreurs:
        attributs["erreurs"] = erreurs
    return {"state": "on" if connecte else "off", "attributes": attributs}


class Superviseur:
    def __init__(self, http: aiohttp.ClientSession, base: str, jeton: str):
        self._http, self._base = http, base.rstrip("/")
        self._entetes = {"Authorization": "Bearer " + jeton}

    async def info_coeur(self) -> dict:
        async with self._http.get(self._base + "/core/info", headers=self._entetes) as r:
            r.raise_for_status()
            return (await r.json())["data"]

    async def poser_etat(self, etat: dict) -> None:
        async with self._http.post(self._base + "/core/api/states/" + ENTITE, json=etat,
                                   headers=self._entetes) as r:
            r.raise_for_status()


async def _attendre_ha(sup: Superviseur, attente: float, arret: asyncio.Event):
    """Juste après un démarrage, le Supervisor répond avant HA (vu le 10/11) : on attend, sans fin."""
    while not arret.is_set():
        try:
            return url_ha_depuis_info(await sup.info_coeur())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
            JOURNAL.info("HA pas encore prêt (%s) : nouvel essai", type(e).__name__)
        try:
            await asyncio.wait_for(arret.wait(), attente)
        except asyncio.TimeoutError:
            pass
    return None


async def tourner(*, donnees: str = "/data", superviseur: str = "http://supervisor",
                  jeton_superviseur: str = "", periode: float = 10.0, attente_superviseur: float = 5.0,
                  fabrique=Module, arret: asyncio.Event = None) -> None:
    """Tient l'add-on jusqu'à `arret` : la ligne si l'add-on est réglé, l'entité dans tous les cas."""
    arret = arret or asyncio.Event()
    # Une clé abîmée lève ValueError et arrête l'add-on : jamais remplacée en silence (cles.py).
    cle = charger_ou_creer(os.path.join(donnees, "cle.json"))
    relais, jeton = lire_options(os.path.join(donnees, "options.json"))
    reglee = bool(relais or jeton)
    erreurs = valider(relais, jeton) if reglee else {}
    if not reglee:
        JOURNAL.info("pas encore réglé : la clé publique est montrée, la ligne attend ses réglages")
    elif erreurs:
        JOURNAL.warning("réglages refusés : %s", ", ".join("%s=%s" % e for e in sorted(erreurs.items())))

    async with aiohttp.ClientSession() as http:
        sup = Superviseur(http, superviseur, jeton_superviseur)
        module = None
        tache = None
        if reglee and not erreurs:
            adresse = await _attendre_ha(sup, attente_superviseur, arret)
            if adresse is not None:
                url, tls = adresse
                module = fabrique(relais=relais, jeton=jeton, url_ha=url, cle=cle, verifier_tls_ha=not tls)
                tache = asyncio.create_task(module.tourner())
                JOURNAL.info("ligne vers le relais lancée ; HA : %s", url)
        try:
            dernier = None
            while not arret.is_set():
                etat = etat_entite(bool(module and module.connecte), cle.publique, erreurs,
                                   reglee and not erreurs)
                try:
                    await sup.poser_etat(etat)
                    if etat["state"] != dernier:
                        JOURNAL.info("entité : %s", etat["state"])
                    dernier = etat["state"]
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    JOURNAL.info("entité non posée (%s) : nouvel essai", type(e).__name__)
                try:
                    await asyncio.wait_for(arret.wait(), periode)
                except asyncio.TimeoutError:
                    pass
        finally:
            if module is not None:
                await module.arreter()
                await asyncio.gather(tache, return_exceptions=True)


def principal() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    jeton = os.environ.get("SUPERVISOR_TOKEN", "")
    if not jeton:
        raise SystemExit("SUPERVISOR_TOKEN absent : cet add-on ne tourne que sous le Supervisor de HA")

    async def lancer():
        arret = asyncio.Event()
        boucle = asyncio.get_running_loop()
        for s in (signal.SIGTERM, signal.SIGINT):
            boucle.add_signal_handler(s, arret.set)
        await tourner(jeton_superviseur=jeton, arret=arret)

    asyncio.run(lancer())


if __name__ == "__main__":
    principal()
