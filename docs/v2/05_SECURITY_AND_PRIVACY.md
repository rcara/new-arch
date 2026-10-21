# Sécurité et confidentialité V2

## Confirmé (existant)

- Mots de passe Argon2id (m=19 Mio, t=2, p=1).
- Sessions token hashées ; révocation à désactivation.
- CSRF sur mutations cookie ; Host/Origin/loopback.
- Rate limiting tentatives connexion.
- Fichiers hors web root ; téléchargement contrôlé ; pas d’exposition statique du vault.
- Droits indépendants Index / décision / fichier.
- Pas de journalisation du contenu coffre ni des textes de décision dans les audits métier (événements techniques uniquement).

## Risque assumé (ne pas mentir)

**SQLite et journaux restent en clair** (montants, ACL, noms). Un accès disque contourne encore les ACL applicatives sur ces métadonnées.

**Blobs coffre / média** : chiffrement AES-256-GCM optionnel (`cli.py crypto enable`, `FOYER_PASSPHRASE`) — voir `10_ENCRYPTION.md`. Ce n’est pas un chiffrement « cosmétique » : sans la phrase, le contenu des fichiers n’est pas lisible sur le disque.

## Person vs UserAccount

- `person` : membre/contact du foyer.
- `account` : identité connectée (1:1 optionnel avec person).
- La parenté n’accorde aucun droit.

## IDOR / path traversal

- Accès par id toujours vérifié côté serveur.
- `storage_key` hex 64 ; chemins résolus sous `vault/objects` uniquement.

## Liens et recherche

Les relations ne donnent pas d’accès. Création et lecture de liens exigent les droits sur les deux extrémités. La recherche ne déduit pas l’existence d’objets privés pour un non-autorisé.

## Exposition réseau

Défaut : 127.0.0.1. LAN / distant uniquement avec mécanismes explicites (Tunnel documenté) — jamais Internet ouvert par défaut.
