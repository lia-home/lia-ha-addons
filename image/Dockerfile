# L'IMAGE DE L'ADD-ON « Lia — accès de dehors » (lot 5) : amd64 et aarch64, PUBLIQUE sur ghcr.io. Publiée
# par le dépôt `lia-home/lia-ha-addons` (son `image.yml`, les vraies versions seulement) ; `domotique`
# ne fait que la construire (`addon-image.yml`). Contexte de construction : `module-maison/` ici, `image/`
# dans le dépôt public (mêmes chemins dessous, `addon/assembler-depot.sh`).
#
#   docker buildx build --platform linux/amd64,linux/arm64 -f module-maison/addon/Dockerfile module-maison
#
# Aucune commande ne tourne sur l'architecture visée : les bibliothèques sont choisies pour elle par
# pip, sur la machine qui construit (paquets précompilés pour Alpine, « musllinux »), puis copiées.
# Pas d'émulateur (QEMU) dans la chaîne : la construction des deux architectures prend une minute.

# python:3.13-alpine, l'index multi-architecture relevé le 10/11 sur le i7. Le changer = une mise à
# jour d'image : accord du propriétaire (CLAUDE.md, D4).
ARG PYTHON=python:3.13-alpine@sha256:1e1f6334529d1fb26a2ef619d7cffb30a7c7d7cc1cc7338ebee283a58d1aeaca

FROM --platform=$BUILDPLATFORM ${PYTHON} AS bibliotheques
ARG TARGETARCH
COPY coeur/exigences.txt /exigences.txt
RUN case "$TARGETARCH" in amd64) a=x86_64 ;; arm64) a=aarch64 ;; *) echo "architecture $TARGETARCH" >&2; exit 1 ;; esac \
 && pip install --no-cache-dir --root-user-action=ignore --disable-pip-version-check \
      --target /bibliotheques --only-binary=:all: --implementation cp --python-version 3.13 \
      --platform "musllinux_1_2_$a" --platform "musllinux_1_1_$a" -r /exigences.txt

FROM ${PYTHON}
ARG VERSION=dev
# Le dépôt PUBLIC que le paquet montre : la fiche de l'add-on (le flux le déduit de `image:` de la fiche).
# Jamais `domotique`, privé.
ARG SOURCE=https://github.com/lia-home/lia-ha-addons
COPY --from=bibliotheques /bibliotheques /usr/local/lib/python3.13/site-packages/
COPY coeur/lia_relais /app/lia_relais
COPY addon/lia_addon.py /app/lia_addon.py
# LIA_VERSION : la version que l'entité montre (`version`), lue par lia_addon.py.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LIA_VERSION=${VERSION}
LABEL io.hass.type="addon" \
      io.hass.version="${VERSION}" \
      org.opencontainers.image.title="Lia — accès de dehors" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.version="${VERSION}"
WORKDIR /app
CMD ["python3", "/app/lia_addon.py"]
