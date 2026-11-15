"""LE MODULE : la ligne de contrôle vers le relais, une ligne par session, le pont vers Home Assistant.

Le déroulé est celui de `Controle.kt` (lot 1) :
1. la ligne de contrôle `wss://<relais>/v1/maison`, avec le jeton de la maison, puis `bonjour` ;
2. à chaque `session`, une seconde ligne `/v1/maison/session/<id>` : le premier message binaire est
   le message 1 de la poignée de main ; la maison demande à son `Autorisation`, répond ;
3. acceptée, la session s'ouvre vers Home Assistant (`url_ha`, le WebSocket de HA) et relaie dans les
   deux sens : un message de HA = un message chiffré ;
4. la ligne de contrôle revient seule si elle tombe : 1 s, puis le double, `attente_max` au plus.

Le module ne mène qu'à `url_ha` : jamais vers un autre appareil du réseau. Il ne garde aucune clé
de Home Assistant : c'est l'app qui envoie la sienne, dans la session. Il ne journalise jamais le
contenu d'une session, seulement ce qui s'y passe (ouverte, refusée, fermée).
"""
import asyncio
import logging
from typing import Optional, Set

import aiohttp
from aiohttp import WSMsgType

from . import controle
from .autorisation import Autorisation, ToutAccepter
from .cles import PaireDeCles
from .poignee import PoigneeMaison, Premier
from .protocole import MAX_MESSAGE, Genre
from .session import AuModule, Fermeture, Message, Session

JOURNAL = logging.getLogger("lia_relais")

# Une trame tient en 65 535 octets ; un peu de marge pour l'enveloppe du WebSocket.
TAILLE_MAX_TRAME = 65535 + 64


class Module:
    def __init__(self, *, relais: str, jeton: str, url_ha: str, cle: PaireDeCles,
                 autorisation: Autorisation = ToutAccepter(), attente_max: float = 60.0,
                 delai_poignee: float = 30.0, verifier_tls_ha: bool = True):
        # `verifier_tls_ha` : à False seulement quand HA sert en https sur 127.0.0.1 (lot 6) — son
        # certificat porte son nom de dehors, pas 127.0.0.1 ; la ligne ne quitte pas la machine.
        self._ssl_ha = None if verifier_tls_ha else False
        self._relais = relais.rstrip("/")
        self._jeton = jeton
        self._url_ha = url_ha
        self._cle = cle
        self._autorisation = autorisation
        self._attente_max = attente_max
        self._delai_poignee = delai_poignee
        self._connecte = False
        self._arret = asyncio.Event()
        self._sessions: Set[asyncio.Task] = set()
        self._http: Optional[aiohttp.ClientSession] = None
        self._ws_controle: Optional[aiohttp.ClientWebSocketResponse] = None

    @property
    def connecte(self) -> bool:
        """La ligne de contrôle est ouverte."""
        return self._connecte

    @property
    def cle_publique(self) -> bytes:
        """La clé publique de la maison : à montrer chez HA, pour que l'app l'épingle (jamais la privée)."""
        return self._cle.publique

    def _entetes(self):
        return {"Authorization": "Bearer " + self._jeton}

    async def tourner(self) -> None:
        """Tient la ligne de contrôle, jusqu'à `arreter`."""
        self._http = aiohttp.ClientSession()
        attente = 1.0
        try:
            while not self._arret.is_set():
                ouverte = False
                try:
                    ouverte = await self._ligne_de_controle()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # le relais refuse, le réseau tombe : on réessaie, sans planter
                    JOURNAL.warning("ligne de contrôle fermée : %s", type(e).__name__)
                self._connecte = False
                if ouverte:
                    attente = 1.0
                if self._arret.is_set():
                    break
                try:
                    await asyncio.wait_for(self._arret.wait(), timeout=min(attente, self._attente_max))
                except asyncio.TimeoutError:
                    pass
                attente = min(attente * 2, self._attente_max)
        finally:
            self._connecte = False
            for t in list(self._sessions):
                t.cancel()
            await asyncio.gather(*self._sessions, return_exceptions=True)
            await self._http.close()

    async def arreter(self) -> None:
        self._arret.set()
        if self._ws_controle is not None:
            await self._ws_controle.close()

    async def _ligne_de_controle(self) -> bool:
        async with self._http.ws_connect(self._relais + controle.CHEMIN_MAISON, headers=self._entetes(),
                                         heartbeat=controle.PING_SECONDES, max_msg_size=64 * 1024) as ws:
            self._ws_controle = ws
            await ws.send_str(controle.encoder(controle.Bonjour()))
            self._connecte = True
            JOURNAL.info("ligne de contrôle ouverte")
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    break
                m = controle.lire(msg.data)
                if isinstance(m, controle.DemandeDeSession):
                    t = asyncio.create_task(self._session(m.id))
                    self._sessions.add(t)
                    t.add_done_callback(self._sessions.discard)
                elif isinstance(m, controle.Fin):
                    JOURNAL.info("le relais ferme la ligne : %s", m.raison)
                    break
            return True

    async def _session(self, id_session: str) -> None:
        try:
            async with self._http.ws_connect(self._relais + controle.chemin_session(id_session),
                                             headers=self._entetes(), heartbeat=controle.PING_SECONDES,
                                             max_msg_size=TAILLE_MAX_TRAME) as ws:
                try:
                    msg = await asyncio.wait_for(ws.receive(), self._delai_poignee)
                except asyncio.TimeoutError:
                    JOURNAL.info("session %s : poignée de main trop lente", id_session)
                    return
                if msg.type != WSMsgType.BINARY:
                    return
                poignee = PoigneeMaison(self._cle)
                premier = poignee.lire_premier(msg.data)
                if premier is None:
                    JOURNAL.info("session %s : poignée de main refusée (rien ne s'accorde)", id_session)
                    return
                statut = await self._autorisation.decider(premier)
                message_2, session = poignee.repondre(statut)
                await ws.send_bytes(message_2)
                if session is None:
                    JOURNAL.info("session %s : téléphone refusé (%s)", id_session, statut.value)
                    return
                JOURNAL.info("session %s ouverte", id_session)
                await self._relayer(ws, session, premier)
                JOURNAL.info("session %s fermée", id_session)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            JOURNAL.warning("session %s : %s", id_session, type(e).__name__)

    async def _relayer(self, ws, session: Session, premier: Premier) -> None:
        verrou = asyncio.Lock()

        async def envoyer(genre: Genre, octets: bytes) -> None:
            # Les trames d'un message partent d'un bloc : deux messages ne s'entremêlent jamais,
            # sinon les compteurs arriveraient dans le désordre et la session tomberait.
            async with verrou:
                for trame in session.chiffrer(genre, octets):
                    await ws.send_bytes(trame)

        try:
            options = {} if self._ssl_ha is None else {"ssl": self._ssl_ha}
            ha = await self._http.ws_connect(self._url_ha, max_msg_size=MAX_MESSAGE, **options)
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            await envoyer(Genre.FERMETURE, "ha injoignable".encode())
            return

        async def vers_ha() -> None:
            async for msg in ws:
                if msg.type != WSMsgType.BINARY:
                    return
                r = session.lire(msg.data)
                if r is None:
                    continue
                if isinstance(r, Message):
                    try:
                        texte = r.octets.decode("utf-8")
                    except UnicodeDecodeError:
                        await envoyer(Genre.FERMETURE, "message illisible".encode())
                        return
                    await ha.send_str(texte)
                elif isinstance(r, AuModule):
                    reponse = await self._autorisation.au_module(premier, r.octets)
                    if reponse is not None:
                        await envoyer(Genre.AU_MODULE, reponse)
                else:  # Fermeture demandée par le téléphone, ou trame Invalide : on ferme.
                    return

        async def depuis_ha() -> None:
            async for msg in ha:
                if msg.type == WSMsgType.TEXT:
                    await envoyer(Genre.FIN, msg.data.encode())
                elif msg.type == WSMsgType.BINARY:
                    await envoyer(Genre.FIN, msg.data)
                else:
                    break
            await envoyer(Genre.FERMETURE, "ha fermé".encode())

        async with ha:
            taches = {asyncio.create_task(vers_ha()), asyncio.create_task(depuis_ha())}
            try:
                await asyncio.wait(taches, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in taches:
                    t.cancel()
                await asyncio.gather(*taches, return_exceptions=True)
