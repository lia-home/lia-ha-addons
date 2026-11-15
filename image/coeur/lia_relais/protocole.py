"""Les constantes du protocole, version 1 — les mêmes que `Protocole.kt` (lot 1)."""
import enum
import json

VERSION = 1
PROLOGUE = b"lia-relais/1"
TAILLE_PRIVEE = 32
TAILLE_PUBLIQUE = 65
TAILLE_ETIQUETTE = 16
MOTIF_NK = 0x01
MOTIF_IK = 0x02
MAX_DONNEES = 65535 - TAILLE_ETIQUETTE - 1
MAX_MESSAGE = 16 * 1024 * 1024
CHARGE_1 = b'{"v":1}'

NOMS_DES_MOTIFS = {
    MOTIF_NK: b"Noise_NK_P256_AESGCM_SHA256",
    MOTIF_IK: b"Noise_IK_P256_AESGCM_SHA256",
}


class Statut(enum.Enum):
    """La réponse de la maison au message 1."""
    ACCEPTE = "accepte"
    TELEPHONE_INCONNU = "telephone_inconnu"

    @property
    def charge(self) -> bytes:
        return ('{"v":1,"statut":"%s"}' % self.value).encode()

    @classmethod
    def lire(cls, charge: bytes):
        """Le statut lu dans la charge du message 2, ou None."""
        try:
            return cls(json.loads(charge.decode())["statut"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            return None


class Genre(enum.IntEnum):
    """Le premier octet du clair d'une trame."""
    MORCEAU = 0x00
    FIN = 0x01
    FERMETURE = 0x02
    AU_MODULE = 0x03


def est_une_cle_publique(octets: bytes) -> bool:
    return len(octets) == TAILLE_PUBLIQUE and octets[0] == 0x04
