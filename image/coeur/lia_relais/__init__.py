"""Le cœur du module de la maison (lot 4 de l'accès de dehors, 10/11).

Commun à l'add-on (HA OS, lot 5) et à l'intégration (Container, lot 6). Il tient la ligne de
contrôle vers le relais, ouvre une ligne par session, fait la poignée de main chiffrée de bout en
bout et relaie les messages vers Home Assistant. Il ne garde aucune clé de HA : c'est l'app qui
envoie la sienne, dans la session chiffrée.

Le contrat est le lot 1, `relais-protocole/` : la spécification en tête de `Protocole.kt`, et les
vecteurs `relais-protocole/vecteurs/v1.json`, que ce code relit dans ses tests.
"""
